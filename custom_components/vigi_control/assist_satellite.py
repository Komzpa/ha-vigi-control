from __future__ import annotations

import asyncio
import json
import logging
import re
import wave
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.components import conversation, stt
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
    async_get_pipeline,
)
from homeassistant.components.assist_satellite import (
    AssistSatelliteAnnouncement,
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
)
from homeassistant.components.assist_satellite.entity import AssistSatelliteState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ASSIST_SAVE_AUDIO,
    CONF_GO2RTC_API_URL,
    CONF_GO2RTC_MIC_STREAM,
    CONF_GO2RTC_STREAM,
    CONF_OPENCLAW_LISTEN_SECONDS,
    DEFAULT_ASSIST_SAVE_AUDIO,
    DEFAULT_OPENCLAW_LISTEN_SECONDS,
    DOMAIN,
)
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .go2rtc import Go2RtcTalkConfig, async_play_talkback_url, build_rtsp_stream_url

_LOGGER = logging.getLogger(__name__)

ASSIST_AUDIO_CAPTURE_DIR = "vigi_assist_captures"
MAX_ASSIST_AUDIO_CAPTURES = 100


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VigiControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    config = _talk_config(entry)
    if not config.enabled:
        return

    async_add_entities([VigiAssistSatellite(coordinator, entry, config)])


def _talk_config(entry: ConfigEntry) -> Go2RtcTalkConfig:
    options = entry.options
    return Go2RtcTalkConfig(
        api_url=str(options.get(CONF_GO2RTC_API_URL) or ""),
        stream=str(options.get(CONF_GO2RTC_STREAM) or ""),
        mic_stream=str(options.get(CONF_GO2RTC_MIC_STREAM) or ""),
    )


def _listen_seconds(entry: ConfigEntry) -> int:
    try:
        value = int(
            entry.options.get(
                CONF_OPENCLAW_LISTEN_SECONDS,
                DEFAULT_OPENCLAW_LISTEN_SECONDS,
            )
        )
    except (TypeError, ValueError):
        return DEFAULT_OPENCLAW_LISTEN_SECONDS

    return min(12, max(3, value))


class VigiAssistSatellite(VigiEntity, AssistSatelliteEntity):
    """Assist satellite surface for VIGI camera talk-back and mic streaming."""

    _attr_name = "Assist satellite"
    _attr_supported_features = (
        AssistSatelliteEntityFeature.ANNOUNCE
        | AssistSatelliteEntityFeature.START_CONVERSATION
    )
    _attr_tts_options = {"voice": "DmitryNeural"}

    def __init__(
        self,
        coordinator: VigiControlCoordinator,
        entry: ConfigEntry,
        config: Go2RtcTalkConfig,
    ) -> None:
        super().__init__(coordinator, entry)
        self._config = config
        self._listen_seconds = _listen_seconds(entry)
        self._attr_unique_id = f"{entry.data[CONF_HOST]}_assist_satellite"
        self._last_stt_text: str | None = None

    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        return AssistSatelliteConfiguration(
            available_wake_words=[],
            active_wake_words=[],
            max_active_wake_words=0,
        )

    async def async_set_configuration(self, config: AssistSatelliteConfiguration) -> None:
        # VIGI cameras do not expose on-device wake-word models. Continuous wake-word
        # support needs a separate always-on microphone worker.
        return None

    async def async_announce(self, announcement: AssistSatelliteAnnouncement) -> None:
        await self._play_announcement(announcement)
        self.tts_response_finished()

    async def async_start_conversation(
        self,
        start_announcement: AssistSatelliteAnnouncement,
    ) -> None:
        _LOGGER.debug("VIGI Assist start conversation: %s", self.entity_id)
        await self._play_announcement(start_announcement)

        extra_system_prompt = self._extra_system_prompt
        self._last_stt_text = None

        self._set_state(AssistSatelliteState.LISTENING)
        self._last_stt_text = await self._speech_to_text()
        self._set_state(AssistSatelliteState.PROCESSING)
        _LOGGER.debug(
            "VIGI Assist STT finished for %s: text=%r",
            self.entity_id,
            self._last_stt_text,
        )

        if not self._last_stt_text:
            self._set_state(AssistSatelliteState.IDLE)
            return

        response_text = await self._process_conversation_text(
            self._last_stt_text,
            extra_system_prompt,
        )
        if not response_text:
            self._set_state(AssistSatelliteState.IDLE)
            return

        _LOGGER.debug(
            "VIGI Assist speaking conversation response for %s: %r",
            self.entity_id,
            response_text,
        )
        self._set_state(AssistSatelliteState.RESPONDING)
        announcement = await self._resolve_announcement_media_id(
            response_text,
            None,
            preannounce_media_id=None,
        )
        await self._play_announcement(announcement)
        self.tts_response_finished()

    async def _play_announcement(self, announcement: AssistSatelliteAnnouncement) -> None:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await async_play_talkback_url(session, self._config, announcement.media_id)

    async def _speech_to_text(self) -> str | None:
        pipeline = async_get_pipeline(self.hass, self._resolve_pipeline())
        engine_id = pipeline.stt_engine or stt.async_default_engine(self.hass)
        if engine_id is None:
            _LOGGER.warning("VIGI Assist has no speech-to-text engine")
            return None

        provider = stt.async_get_speech_to_text_engine(self.hass, engine_id)
        if provider is None:
            _LOGGER.warning("VIGI Assist speech-to-text engine %s is missing", engine_id)
            return None

        metadata = stt.SpeechMetadata(
            language=pipeline.stt_language or pipeline.language,
            format=stt.AudioFormats.WAV,
            codec=stt.AudioCodecs.PCM,
            bit_rate=stt.AudioBitRates.BITRATE_16,
            sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
            channel=stt.AudioChannels.CHANNEL_MONO,
        )
        if not provider.check_metadata(metadata):
            _LOGGER.warning(
                "VIGI Assist speech-to-text engine %s does not support %s",
                engine_id,
                metadata,
            )
            return None

        captured_chunks: list[bytes] = []
        audio_stream = self._camera_pcm_stream()
        save_assist_audio = bool(
            self._entry.options.get(CONF_ASSIST_SAVE_AUDIO, DEFAULT_ASSIST_SAVE_AUDIO)
        )
        if save_assist_audio:
            audio_stream = _capture_audio_stream(audio_stream, captured_chunks)

        result = await provider.async_process_audio_stream(
            metadata,
            audio_stream,
        )
        if save_assist_audio and captured_chunks:
            await self.hass.async_add_executor_job(
                _write_assist_audio_capture,
                Path(self.hass.config.path(ASSIST_AUDIO_CAPTURE_DIR)),
                self.entity_id or self._attr_unique_id,
                engine_id,
                metadata.language,
                captured_chunks,
                result,
            )
        if result.result != stt.SpeechResultState.SUCCESS:
            _LOGGER.warning("VIGI Assist speech-to-text failed: %s", result.result)
            return None

        return result.text

    async def _camera_pcm_stream(self) -> AsyncIterator[bytes]:
        rtsp_url = build_rtsp_stream_url(self._config)
        _LOGGER.debug("VIGI Assist starting ffmpeg mic capture from %s", rtsp_url)
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-rtsp_transport",
            "tcp",
            "-i",
            rtsp_url,
            "-t",
            str(self._listen_seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            "volume=24dB,acompressor=threshold=-18dB:ratio=4:attack=5:release=80,alimiter=limit=0.95",
            "-f",
            "s16le",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert process.stdout is not None
            total_bytes = 0
            while chunk := await process.stdout.read(4096):
                total_bytes += len(chunk)
                yield chunk
            stderr = await process.stderr.read() if process.stderr else b""
            await process.wait()
            stderr_text = stderr.decode(errors="replace").strip() if stderr else ""
            _LOGGER.debug(
                "VIGI Assist ffmpeg mic capture ended for %s: returncode=%s bytes=%s stderr=%s",
                self.entity_id,
                process.returncode,
                total_bytes,
                stderr_text[-500:],
            )
        finally:
            if process.returncode is None:
                process.terminate()
                await process.communicate()

    async def _process_conversation_text(
        self,
        text: str,
        extra_system_prompt: str | None,
    ) -> str | None:
        agent_id = self._resolve_conversation_agent_id()
        result = await conversation.async_converse(
            self.hass,
            text,
            self._conversation_id,
            self._context,
            language=self.hass.config.language,
            agent_id=agent_id,
            device_id=self.registry_entry.device_id if self.registry_entry else None,
            satellite_id=self.entity_id,
            extra_system_prompt=extra_system_prompt,
        )
        self._conversation_id = result.conversation_id
        speech = result.response.speech.get("plain")
        if not speech:
            return None

        return speech.get("speech")

    def _resolve_conversation_agent_id(self) -> str:
        pipeline = async_get_pipeline(self.hass, self._resolve_pipeline())
        agent_id = pipeline.conversation_engine
        if conversation.async_get_agent(self.hass, agent_id) is not None:
            return agent_id

        _LOGGER.warning(
            "VIGI Assist configured conversation agent %s is unavailable; falling back to %s",
            agent_id,
            conversation.HOME_ASSISTANT_AGENT,
        )
        return conversation.HOME_ASSISTANT_AGENT

    def on_pipeline_event(self, event: PipelineEvent) -> None:
        """Handle pipeline events."""

        if event.type is PipelineEventType.STT_END and event.data:
            stt_output = event.data.get("stt_output")
            if stt_output:
                self._last_stt_text = stt_output.get("text")


async def _capture_audio_stream(
    stream: AsyncIterator[bytes],
    captured_chunks: list[bytes],
) -> AsyncIterator[bytes]:
    """Tee an audio stream into memory while preserving streaming STT."""

    async for chunk in stream:
        captured_chunks.append(chunk)
        yield chunk


def _write_assist_audio_capture(
    capture_dir: Path,
    entity_id: str,
    engine_id: str,
    language: str | None,
    chunks: list[bytes],
    result: Any,
) -> None:
    """Write a WAV STT fixture and sidecar metadata for later regression tests."""

    capture_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", entity_id).strip("_") or "vigi_assist"
    stem = f"{timestamp}_{slug}"
    wav_path = capture_dir / f"{stem}.wav"
    pcm = b"".join(chunks)

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm)

    result_state = getattr(result.result, "value", str(result.result))
    metadata = {
        "entity_id": entity_id,
        "engine_id": engine_id,
        "language": language,
        "result": result_state,
        "text": result.text,
        "bytes": len(pcm),
        "duration_seconds": round(len(pcm) / 2 / 16000, 3),
        "sample_rate": 16000,
        "channels": 1,
        "sample_width_bytes": 2,
        "created_at": timestamp,
        "wav_path": str(wav_path),
    }
    wav_path.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _prune_assist_audio_captures(capture_dir)


def _prune_assist_audio_captures(capture_dir: Path) -> None:
    wav_paths = sorted(capture_dir.glob("*.wav"), key=lambda path: path.name)
    for wav_path in wav_paths[:-MAX_ASSIST_AUDIO_CAPTURES]:
        wav_path.unlink(missing_ok=True)
        wav_path.with_suffix(".json").unlink(missing_ok=True)

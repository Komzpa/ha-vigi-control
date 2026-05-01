from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import aiohttp
from homeassistant.components import conversation, stt
from homeassistant.components.assist_satellite import (
    AssistSatelliteAnnouncement,
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
)
from homeassistant.components.assist_satellite.entity import AssistSatelliteState
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
    async_get_pipeline,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_GO2RTC_API_URL,
    CONF_GO2RTC_MIC_STREAM,
    CONF_GO2RTC_STREAM,
    CONF_OPENCLAW_AGENT_TOKEN,
    CONF_OPENCLAW_AGENT_URL,
    DOMAIN,
)
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .go2rtc import Go2RtcTalkConfig, async_play_talkback_url, build_rtsp_stream_url

CONVERSATION_LISTEN_SECONDS = 8

_LOGGER = logging.getLogger(__name__)


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
        self._openclaw_agent_url = str(entry.options.get(CONF_OPENCLAW_AGENT_URL) or "")
        self._openclaw_agent_token = str(entry.options.get(CONF_OPENCLAW_AGENT_TOKEN) or "")
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

        if self._openclaw_agent_url:
            self._set_state(AssistSatelliteState.LISTENING)
            response_text = await self._process_openclaw_audio()
            if not response_text:
                self._set_state(AssistSatelliteState.IDLE)
                return

            self._set_state(AssistSatelliteState.RESPONDING)
            announcement = await self._resolve_announcement_media_id(
                response_text,
                None,
                preannounce_media_id=None,
            )
            await self._play_announcement(announcement)
            self.tts_response_finished()
            return

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
            format=stt.AudioFormats.OGG,
            codec=stt.AudioCodecs.OPUS,
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

        result = await provider.async_process_audio_stream(
            metadata,
            self._camera_ogg_stream(),
        )
        if result.result != stt.SpeechResultState.SUCCESS:
            _LOGGER.warning("VIGI Assist speech-to-text failed: %s", result.result)
            return None

        return result.text

    async def _camera_ogg_stream(self) -> AsyncIterator[bytes]:
        rtsp_url = build_rtsp_stream_url(self._config)
        _LOGGER.debug("VIGI Assist starting ffmpeg mic capture from %s", rtsp_url)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

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
            str(CONVERSATION_LISTEN_SECONDS),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            "volume=24dB,acompressor=threshold=-18dB:ratio=4:attack=5:release=80,alimiter=limit=0.95",
            "-c:a",
            "libopus",
            "-b:a",
            "24k",
            "-vbr",
            "off",
            "-application",
            "voip",
            "-f",
            "ogg",
            "-y",
            str(temp_path),
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await process.communicate()
            stderr_text = stderr.decode(errors="replace").strip() if stderr else ""
            total_bytes = temp_path.stat().st_size
            _LOGGER.debug(
                "VIGI Assist ffmpeg mic capture ended for %s: returncode=%s bytes=%s stderr=%s",
                self.entity_id,
                process.returncode,
                total_bytes,
                stderr_text[-500:],
            )
            with temp_path.open("rb") as audio_file:
                while chunk := audio_file.read(4096):
                    yield chunk
        finally:
            if process.returncode is None:
                process.terminate()
                await process.communicate()
            temp_path.unlink(missing_ok=True)

    async def _camera_wav_bytes(self) -> bytes:
        rtsp_url = build_rtsp_stream_url(self._config)
        _LOGGER.debug("VIGI Assist starting ffmpeg mic WAV capture from %s", rtsp_url)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

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
            str(CONVERSATION_LISTEN_SECONDS),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            "volume=24dB,acompressor=threshold=-18dB:ratio=4:attack=5:release=80,alimiter=limit=0.95",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            "-y",
            str(temp_path),
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await process.communicate()
            stderr_text = stderr.decode(errors="replace").strip() if stderr else ""
            audio = temp_path.read_bytes()
            _LOGGER.debug(
                "VIGI Assist ffmpeg mic WAV capture ended for %s: returncode=%s bytes=%s stderr=%s",
                self.entity_id,
                process.returncode,
                len(audio),
                stderr_text[-500:],
            )
            return audio
        finally:
            if process.returncode is None:
                process.terminate()
                await process.communicate()
            temp_path.unlink(missing_ok=True)

    async def _process_conversation_text(
        self,
        text: str,
        extra_system_prompt: str | None,
    ) -> str | None:
        if self._openclaw_agent_url:
            try:
                return await self._process_openclaw_text(text)
            except Exception as exc:
                _LOGGER.warning(
                    "VIGI Assist OpenClaw agent request failed for %s: %s",
                    self.entity_id,
                    exc,
                )

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

    async def _process_openclaw_text(self, text: str) -> str | None:
        timeout = aiohttp.ClientTimeout(total=45)
        headers = {}
        if self._openclaw_agent_token:
            headers["Authorization"] = f"Bearer {self._openclaw_agent_token}"

        session = async_get_clientsession(self.hass)
        async with session.post(
            self._openclaw_agent_url,
            json={"text": text, "entity_id": self.entity_id},
            headers=headers,
            timeout=timeout,
        ) as response:
            try:
                payload = await response.json()
            except aiohttp.ContentTypeError as exc:
                body = await response.text()
                raise RuntimeError(
                    f"HTTP {response.status}: non-JSON response {body[:200]}"
                ) from exc

            if response.status >= 400 or not payload.get("ok"):
                raise RuntimeError(
                    f"HTTP {response.status}: {payload.get('error') or payload}"
                )

        return str(payload.get("text") or "").strip() or None

    async def _process_openclaw_audio(self) -> str | None:
        timeout = aiohttp.ClientTimeout(total=75)
        headers = {}
        if self._openclaw_agent_token:
            headers["Authorization"] = f"Bearer {self._openclaw_agent_token}"

        audio = await self._camera_wav_bytes()
        session = async_get_clientsession(self.hass)
        async with session.post(
            self._openclaw_agent_url,
            json={
                "audio_b64": base64.b64encode(audio).decode("ascii"),
                "audio_format": "wav",
                "entity_id": self.entity_id,
            },
            headers=headers,
            timeout=timeout,
        ) as response:
            try:
                payload = await response.json()
            except aiohttp.ContentTypeError as exc:
                body = await response.text()
                raise RuntimeError(
                    f"HTTP {response.status}: non-JSON response {body[:200]}"
                ) from exc

            if response.status >= 400 or not payload.get("ok"):
                raise RuntimeError(
                    f"HTTP {response.status}: {payload.get('error') or payload}"
                )

        return str(payload.get("text") or "").strip() or None

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

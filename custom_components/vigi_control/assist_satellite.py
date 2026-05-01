from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import aiohttp
from homeassistant.components import conversation
from homeassistant.components.assist_satellite import (
    AssistSatelliteAnnouncement,
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
)
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
    PipelineStage,
    async_get_pipeline,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_GO2RTC_API_URL, CONF_GO2RTC_STREAM, DOMAIN
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
        await self.async_accept_pipeline_from_satellite(
            self._camera_audio_stream(),
            start_stage=PipelineStage.STT,
            end_stage=PipelineStage.STT,
        )
        _LOGGER.debug(
            "VIGI Assist STT finished for %s: text=%r",
            self.entity_id,
            self._last_stt_text,
        )

        if not self._last_stt_text:
            return

        response_text = await self._process_conversation_text(
            self._last_stt_text,
            extra_system_prompt,
        )
        if not response_text:
            return

        _LOGGER.debug(
            "VIGI Assist speaking conversation response for %s: %r",
            self.entity_id,
            response_text,
        )
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

    async def _camera_audio_stream(self) -> AsyncIterator[bytes]:
        rtsp_url = build_rtsp_stream_url(self._config)
        _LOGGER.debug("VIGI Assist starting ffmpeg mic stream from %s", rtsp_url)
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
            "-acodec",
            "pcm_s16le",
            "-f",
            "wav",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdout is not None
        total_bytes = 0
        try:
            while chunk := await process.stdout.read(4096):
                total_bytes += len(chunk)
                yield chunk
        finally:
            if process.returncode is None:
                process.terminate()
            _stdout, stderr = await process.communicate()
            stderr_text = stderr.decode(errors="replace").strip() if stderr else ""
            _LOGGER.debug(
                "VIGI Assist ffmpeg mic stream ended for %s: returncode=%s bytes=%s stderr=%s",
                self.entity_id,
                process.returncode,
                total_bytes,
                stderr_text[-500:],
            )

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

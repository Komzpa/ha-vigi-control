from __future__ import annotations

import aiohttp
from homeassistant.components.assist_satellite import (
    AssistSatelliteAnnouncement,
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_GO2RTC_API_URL, CONF_GO2RTC_STREAM, DOMAIN
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .go2rtc import Go2RtcTalkConfig, async_play_talkback_url


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
    """Assist satellite surface for VIGI camera talk-back announcements."""

    _attr_name = "Assist satellite"
    _attr_supported_features = AssistSatelliteEntityFeature.ANNOUNCE
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

    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        return AssistSatelliteConfiguration(
            available_wake_words=[],
            active_wake_words=[],
            max_active_wake_words=0,
        )

    async def async_set_configuration(self, config: AssistSatelliteConfiguration) -> None:
        # VIGI cameras do not expose on-device wake-word models. Wake-word/STT support
        # needs a separate microphone-stream worker that feeds Home Assistant's pipeline.
        return None

    async def async_announce(self, announcement: AssistSatelliteAnnouncement) -> None:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await async_play_talkback_url(session, self._config, announcement.media_id)
        self.tts_response_finished()

    def on_pipeline_event(self, event) -> None:
        """Handle pipeline events."""

        return None

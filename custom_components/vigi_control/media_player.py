from __future__ import annotations

from typing import Any

import aiohttp
from homeassistant.components import media_source
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_GO2RTC_API_URL, CONF_GO2RTC_STREAM, DOMAIN
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .go2rtc import Go2RtcError, Go2RtcTalkConfig, async_play_talkback_url


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VigiControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    config = _talk_config(entry)
    if not config.enabled:
        return

    async_add_entities([VigiTalkbackMediaPlayer(coordinator, entry, config)])


def _talk_config(entry: ConfigEntry) -> Go2RtcTalkConfig:
    options = entry.options
    return Go2RtcTalkConfig(
        api_url=str(options.get(CONF_GO2RTC_API_URL) or ""),
        stream=str(options.get(CONF_GO2RTC_STREAM) or ""),
    )


class VigiTalkbackMediaPlayer(VigiEntity, MediaPlayerEntity):
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_name = "Talk-back speaker"
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        | MediaPlayerEntityFeature.VOLUME_SET
    )

    def __init__(
        self,
        coordinator: VigiControlCoordinator,
        entry: ConfigEntry,
        config: Go2RtcTalkConfig,
    ) -> None:
        super().__init__(coordinator, entry)
        self._config = config
        self._attr_unique_id = f"{entry.data[CONF_HOST]}_talkback_speaker"
        self._attr_state = MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        volume = self.coordinator.data.speaker_system_volume
        if volume is None:
            volume = self.coordinator.data.speaker_volume
        if volume is None:
            return None
        return max(0.0, min(1.0, volume / 100))

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.client.async_set_speaker_system_volume(round(volume * 100))
        await self.coordinator.async_request_refresh()

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        enqueue: Any | None = None,
        announce: bool | None = None,
        **kwargs: Any,
    ) -> None:
        """Play a media URL or Home Assistant media source through VIGI talk-back."""

        if media_source.is_media_source_id(media_id):
            play_item = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
            media_id = async_process_play_media_url(self.hass, play_item.url)

        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                await async_play_talkback_url(session, self._config, media_id)
        except Go2RtcError as exc:
            self._attr_state = MediaPlayerState.IDLE
            self.async_write_ha_state()
            raise HomeAssistantError(str(exc)) from exc

        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

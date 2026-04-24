from __future__ import annotations

import asyncio
import logging

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .vigi_api import VigiApiError

_LOGGER = logging.getLogger(__name__)

_BRIGHTNESS_COOLDOWN_SECONDS = 0.25
_BACKGROUND_START_DELAY_SECONDS = 0.05


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VigiControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VigiWhiteLight(coordinator, entry)])


class VigiWhiteLight(VigiEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_should_poll = False
    _attr_translation_key = "white_light"

    def __init__(self, coordinator: VigiControlCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._host}_white_light"
        self._optimistic_is_on: bool | None = None
        self._optimistic_brightness: int | None = None
        self._cooling_down = False
        self._pending_brightness: int | None = None
        self._brightness_task: asyncio.Task | None = None
        self._command_generation = 0
        self._command_task: asyncio.Task | None = None

    @property
    def is_on(self) -> bool:
        if self._optimistic_is_on is not None:
            return self._optimistic_is_on
        return self.coordinator.data.white_light_on

    @property
    def brightness(self) -> int:
        if self._optimistic_brightness is not None:
            return self._optimistic_brightness
        return self.coordinator.data.brightness

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is None:
            brightness = self.brightness or 153

        if self.is_on and ATTR_BRIGHTNESS in kwargs:
            if self._cooling_down or (
                self._brightness_task is not None and not self._brightness_task.done()
            ):
                self._pending_brightness = brightness
                return

            self._optimistic_is_on = True
            self._optimistic_brightness = brightness
            self.async_write_ha_state()
            self._cooling_down = True
            self._brightness_task = asyncio.create_task(self._brightness_worker(brightness))
            return

        self._command_generation += 1
        generation = self._command_generation
        self._optimistic_is_on = True
        self._optimistic_brightness = brightness
        self.async_write_ha_state()
        self._command_task = asyncio.create_task(self._turn_on_worker(generation, brightness))

    async def async_turn_off(self, **kwargs) -> None:
        self._command_generation += 1
        generation = self._command_generation
        self._pending_brightness = None
        if self._brightness_task is not None and not self._brightness_task.done():
            self._brightness_task.cancel()
        self._cooling_down = False

        self._optimistic_is_on = False
        self.async_write_ha_state()
        self._command_task = asyncio.create_task(self._turn_off_worker(generation))

    async def _turn_on_worker(self, generation: int, brightness: int) -> None:
        await asyncio.sleep(_BACKGROUND_START_DELAY_SECONDS)
        try:
            await self.coordinator.client.async_turn_white_light_on(brightness)
        except VigiApiError:
            _LOGGER.exception("Failed to turn on VIGI white light for %s", self._host)
            if generation == self._command_generation:
                self._attr_available = False
                self.async_write_ha_state()
            return

        if generation != self._command_generation:
            return

        await self.coordinator.async_request_refresh()
        self._attr_available = True
        self._optimistic_is_on = None
        self._optimistic_brightness = None
        self.async_write_ha_state()

    async def _turn_off_worker(self, generation: int) -> None:
        await asyncio.sleep(_BACKGROUND_START_DELAY_SECONDS)
        try:
            await self.coordinator.client.async_turn_white_light_off()
        except VigiApiError:
            _LOGGER.exception("Failed to turn off VIGI white light for %s", self._host)
            if generation == self._command_generation:
                self._attr_available = False
                self.async_write_ha_state()
            return

        if generation != self._command_generation:
            return

        await self.coordinator.async_request_refresh()
        self._attr_available = True
        self._optimistic_is_on = None
        self._optimistic_brightness = None
        self.async_write_ha_state()

    async def _brightness_worker(self, brightness: int) -> None:
        await asyncio.sleep(_BACKGROUND_START_DELAY_SECONDS)
        while True:
            try:
                await self.coordinator.client.async_set_white_light_brightness(brightness)
            except VigiApiError:
                _LOGGER.exception("Failed to set VIGI white light brightness for %s", self._host)
                self._attr_available = False
            else:
                self._attr_available = True

            self.async_write_ha_state()
            await asyncio.sleep(_BRIGHTNESS_COOLDOWN_SECONDS)

            if self._pending_brightness is None:
                self._cooling_down = False
                await self.coordinator.async_request_refresh()
                self._optimistic_brightness = None
                self.async_write_ha_state()
                return

            brightness = self._pending_brightness
            self._optimistic_brightness = brightness
            self._pending_brightness = None


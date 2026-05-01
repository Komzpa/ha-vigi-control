from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .vigi_api import VigiDeviceState


@dataclass(frozen=True, kw_only=True)
class VigiButtonDescription(ButtonEntityDescription):
    supported_fn: Callable[[VigiDeviceState], bool]
    press_fn: Callable[[VigiControlCoordinator], Any]


BUTTONS = [
    VigiButtonDescription(
        key="manual_alarm_start",
        translation_key="manual_alarm_start",
        supported_fn=lambda state: state.has_alarm("enabled"),
        press_fn=lambda coordinator: coordinator.client.async_start_manual_alarm(),
    ),
    VigiButtonDescription(
        key="manual_alarm_stop",
        translation_key="manual_alarm_stop",
        supported_fn=lambda state: state.has_alarm("enabled"),
        press_fn=lambda coordinator: coordinator.client.async_stop_manual_alarm(),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VigiControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            VigiCameraButton(coordinator, entry, description)
            for description in BUTTONS
            if description.supported_fn(coordinator.data)
        ]
    )


class VigiCameraButton(VigiEntity, ButtonEntity):
    entity_description: VigiButtonDescription

    def __init__(
        self,
        coordinator: VigiControlCoordinator,
        entry: ConfigEntry,
        description: VigiButtonDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._host}_{description.key}"

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
        await self.coordinator.async_request_refresh()

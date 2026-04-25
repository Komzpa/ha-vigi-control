from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .vigi_api import VigiDeviceState

NIGHT_VISION_MODES = [
    "inf_night_vision",
    "wtl_night_vision",
]


@dataclass(frozen=True, kw_only=True)
class VigiSelectDescription(SelectEntityDescription):
    options: list[str]
    value_fn: Callable[[VigiDeviceState], str | None]
    supported_fn: Callable[[VigiDeviceState], bool]
    set_fn: Callable[[VigiControlCoordinator, str], Any]


SELECTS = [
    VigiSelectDescription(
        key="flip_type",
        translation_key="flip_type",
        entity_category=EntityCategory.CONFIG,
        options=["off", "center", "flip", "mirror"],
        value_fn=lambda state: _str_or_none(state.switch.get("flip_type")),
        supported_fn=lambda state: state.has_image_switch("flip_type"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_switch_value(
            "flip_type", value
        ),
    ),
    VigiSelectDescription(
        key="rotate_type",
        translation_key="rotate_type",
        entity_category=EntityCategory.CONFIG,
        options=["off", "90", "180", "270"],
        value_fn=lambda state: _str_or_none(state.switch.get("rotate_type")),
        supported_fn=lambda state: state.has_image_switch("rotate_type"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_switch_value(
            "rotate_type", value
        ),
    ),
    VigiSelectDescription(
        key="flicker",
        translation_key="flicker",
        entity_category=EntityCategory.CONFIG,
        options=["50hz", "60hz"],
        value_fn=lambda state: _str_or_none(state.switch.get("flicker")),
        supported_fn=lambda state: state.has_image_switch("flicker"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_switch_value(
            "flicker", value
        ),
    ),
    VigiSelectDescription(
        key="image_scene_mode",
        translation_key="image_scene_mode",
        entity_category=EntityCategory.CONFIG,
        options=["normal", "auto", "shedday", "shednight", "autoday", "autonight"],
        value_fn=lambda state: _str_or_none(state.switch.get("image_scene_mode")),
        supported_fn=lambda state: state.has_image_switch("image_scene_mode"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_switch_value(
            "image_scene_mode", value
        ),
    ),
    VigiSelectDescription(
        key="white_balance",
        translation_key="white_balance",
        entity_category=EntityCategory.CONFIG,
        options=["auto", "nature", "manual", "lock"],
        value_fn=lambda state: _str_or_none(state.common.get("wb_type")),
        supported_fn=lambda state: state.has_image_common("wb_type"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_common_value(
            "wb_type", value
        ),
    ),
    VigiSelectDescription(
        key="exposure_type",
        translation_key="exposure_type",
        entity_category=EntityCategory.CONFIG,
        options=["auto", "manual"],
        value_fn=lambda state: _str_or_none(state.common.get("exp_type")),
        supported_fn=lambda state: state.has_image_common("exp_type"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_common_value(
            "exp_type", value
        ),
    ),
    VigiSelectDescription(
        key="smart_ir",
        translation_key="smart_ir",
        entity_category=EntityCategory.CONFIG,
        options=["auto_ir", "manual"],
        value_fn=lambda state: _str_or_none(state.common.get("smartir")),
        supported_fn=lambda state: state.has_image_common("smartir"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_common_value(
            "smartir", value
        ),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VigiControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    if coordinator.data.has_image_switch("night_vision_mode"):
        entities.append(VigiNightVisionModeSelect(coordinator, entry))
    entities.extend(
        VigiCameraSelect(coordinator, entry, description)
        for description in SELECTS
        if description.supported_fn(coordinator.data)
    )
    async_add_entities(entities)


class VigiNightVisionModeSelect(VigiEntity, SelectEntity):
    _attr_translation_key = "night_vision_mode"
    _attr_options = NIGHT_VISION_MODES

    def __init__(self, coordinator: VigiControlCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._host}_night_vision_mode"

    @property
    def current_option(self) -> str | None:
        mode = self.coordinator.data.night_vision_mode
        if mode and mode not in self._attr_options:
            self._attr_options = [*NIGHT_VISION_MODES, mode]
        return mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.client.async_set_night_vision_mode(option)
        await self.coordinator.async_request_refresh()


class VigiCameraSelect(VigiEntity, SelectEntity):
    entity_description: VigiSelectDescription

    def __init__(
        self,
        coordinator: VigiControlCoordinator,
        entry: ConfigEntry,
        description: VigiSelectDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._host}_{description.key}"
        self._attr_options = description.options

    @property
    def current_option(self) -> str | None:
        value = self.entity_description.value_fn(self.coordinator.data)
        if value and value not in self._attr_options:
            self._attr_options = [*self.entity_description.options, value]
        return value

    async def async_select_option(self, option: str) -> None:
        await self.entity_description.set_fn(self.coordinator, option)
        await self.coordinator.async_request_refresh()


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None

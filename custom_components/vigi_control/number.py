from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .vigi_api import VigiCameraClient, VigiDeviceState


@dataclass(frozen=True, kw_only=True)
class VigiNumberDescription(NumberEntityDescription):
    native_min_value: int = 0
    native_max_value: int = 100
    native_step: int = 1
    mode: NumberMode = NumberMode.SLIDER
    value_fn: Callable[[VigiDeviceState], Any]
    supported_fn: Callable[[VigiDeviceState], bool]
    set_fn: Callable[[VigiControlCoordinator, int], Any]


def _common_number(key: str, translation_key: str) -> VigiNumberDescription:
    return VigiNumberDescription(
        key=key,
        translation_key=translation_key,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: _int_or_none(state.common.get(key)),
        supported_fn=lambda state: state.has_image_common(key),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_common_value(
            key, value
        ),
    )


def _delay_number(key: str, translation_key: str) -> VigiNumberDescription:
    return VigiNumberDescription(
        key=key,
        translation_key=translation_key,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: _int_or_none(state.common.get(key)),
        supported_fn=lambda state: state.has_image_common(key),
        set_fn=lambda coordinator, value: coordinator.client.async_set_image_common_value(
            key, value
        ),
    )


COMMON_NUMBERS = [
    _common_number("luma", "image_brightness"),
    _common_number("contrast", "image_contrast"),
    _common_number("saturation", "image_saturation"),
    _common_number("chroma", "image_chroma"),
    _common_number("sharpness", "image_sharpness"),
    _common_number("wd_gain", "wide_dynamic_gain"),
    _common_number("exp_gain", "exposure_gain"),
    _delay_number("wtl_delay", "white_light_auto_switch_delay"),
    _delay_number("inf_delay", "infrared_auto_switch_delay"),
    VigiNumberDescription(
        key="motion_digital_sensitivity",
        translation_key="motion_digital_sensitivity",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: _int_or_none(
            _nested(state.motion, "motion_det", "digital_sensitivity")
        ),
        supported_fn=lambda state: state.has_motion("digital_sensitivity"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_motion_value(
            "digital_sensitivity", value
        ),
    ),
    VigiNumberDescription(
        key="speaker_volume",
        translation_key="speaker_volume",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: state.speaker_volume,
        supported_fn=lambda state: state.has_speaker("volume"),
        set_fn=lambda coordinator, value: coordinator.client.async_set_speaker_volume(value),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VigiControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    if coordinator.data.supports_white_light_level:
        entities.append(VigiWhiteLightLevelNumber(coordinator, entry))
    entities.extend(
        VigiCameraNumber(coordinator, entry, description)
        for description in COMMON_NUMBERS
        if description.supported_fn(coordinator.data)
    )
    async_add_entities(entities)


class VigiWhiteLightLevelNumber(VigiEntity, NumberEntity):
    _attr_translation_key = "white_light_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1
    _attr_native_max_value = 5
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: VigiControlCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._host}_white_light_level"

    @property
    def native_value(self) -> int:
        return self.coordinator.data.white_light_level

    async def async_set_native_value(self, value: float) -> None:
        brightness = VigiCameraClient.brightness_from_level(round(value))
        await self.coordinator.client.async_set_white_light_brightness(brightness)
        await self.coordinator.async_request_refresh()


class VigiCameraNumber(VigiEntity, NumberEntity):
    entity_description: VigiNumberDescription

    def __init__(
        self,
        coordinator: VigiControlCoordinator,
        entry: ConfigEntry,
        description: VigiNumberDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._host}_{description.key}"
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step
        self._attr_mode = description.mode

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_fn(self.coordinator, round(value))
        await self.coordinator.async_request_refresh()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested(data: MappingLike, *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


MappingLike = dict[str, Any]

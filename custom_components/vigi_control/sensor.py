from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .vigi_api import VigiDeviceState


@dataclass(frozen=True, kw_only=True)
class VigiSensorDescription(SensorEntityDescription):
    value_fn: Callable[[VigiDeviceState], Any]
    supported_fn: Callable[[VigiDeviceState], bool]


SENSORS = [
    VigiSensorDescription(
        key="white_light_type",
        translation_key="white_light_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.white_light_type,
        supported_fn=lambda state: state.has_image_common("wtl_type"),
    ),
    VigiSensorDescription(
        key="infrared_type",
        translation_key="infrared_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.infrared_type,
        supported_fn=lambda state: state.has_image_common("inf_type"),
    ),
    VigiSensorDescription(
        key="smart_white_light",
        translation_key="smart_white_light",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.smart_white_light,
        supported_fn=lambda state: state.has_image_common("smartwtl"),
    ),
    VigiSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.firmware_version,
        supported_fn=lambda state: state.firmware_version is not None,
    ),
    VigiSensorDescription(
        key="main_stream_resolution",
        translation_key="main_stream_resolution",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: _nested(state.video, "main", "resolution"),
        supported_fn=lambda state: state.has_video_main("resolution"),
    ),
    VigiSensorDescription(
        key="main_stream_encoding",
        translation_key="main_stream_encoding",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: _nested(state.video, "main", "encode_type"),
        supported_fn=lambda state: state.has_video_main("encode_type"),
    ),
    VigiSensorDescription(
        key="main_stream_bitrate",
        translation_key="main_stream_bitrate",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: _nested(state.video, "main", "bitrate"),
        supported_fn=lambda state: state.has_video_main("bitrate"),
    ),
    VigiSensorDescription(
        key="motion_sensitivity",
        translation_key="motion_sensitivity",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: _nested(state.motion, "motion_det", "sensitivity"),
        supported_fn=lambda state: state.has_motion("sensitivity"),
    ),
    VigiSensorDescription(
        key="message_alarm_mode",
        translation_key="message_alarm_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: _alarm_mode(state),
        supported_fn=lambda state: state.has_alarm("alarm_mode"),
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
            VigiSensor(coordinator, entry, description)
            for description in SENSORS
            if description.supported_fn(coordinator.data)
        ]
    )


class VigiSensor(VigiEntity, SensorEntity):
    entity_description: VigiSensorDescription

    def __init__(
        self,
        coordinator: VigiControlCoordinator,
        entry: ConfigEntry,
        description: VigiSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._host}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)


def _nested(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _alarm_mode(state: VigiDeviceState) -> str | None:
    value = _nested(state.alarm, "chn1_msg_alarm_info", "alarm_mode")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return value if isinstance(value, str) else None

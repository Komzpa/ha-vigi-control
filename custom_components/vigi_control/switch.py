from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiControlCoordinator
from .entity import VigiEntity
from .vigi_api import VigiDeviceState


@dataclass(frozen=True, kw_only=True)
class VigiSwitchDescription(SwitchEntityDescription):
    value_fn: Callable[[VigiDeviceState], bool | None]
    set_fn: Callable[[VigiControlCoordinator, bool], Any]


def _image_common_switch(key: str, translation_key: str) -> VigiSwitchDescription:
    return VigiSwitchDescription(
        key=key,
        translation_key=translation_key,
        value_fn=lambda state: _on_off(state.common.get(key)),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_image_common_value(
            key, _enabled(enabled)
        ),
    )


def _image_switch_switch(key: str, translation_key: str) -> VigiSwitchDescription:
    return VigiSwitchDescription(
        key=key,
        translation_key=translation_key,
        value_fn=lambda state: _on_off(state.switch.get(key)),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_image_switch_value(
            key, _enabled(enabled)
        ),
    )


SWITCHES = [
    _image_common_switch("wide_dynamic", "wide_dynamic"),
    _image_common_switch("high_light_compensation", "high_light_compensation"),
    _image_common_switch("dehaze", "dehaze"),
    _image_common_switch("eis", "electronic_image_stabilization"),
    _image_common_switch("auto_exp_antiflicker", "auto_exposure_antiflicker"),
    _image_common_switch("backlight", "backlight_compensation"),
    _image_switch_switch("ldc", "lens_distortion_correction"),
    _image_switch_switch("full_color_people_enhance", "full_color_people_enhance"),
    _image_switch_switch("full_color_vehicle_enhance", "full_color_vehicle_enhance"),
    _image_switch_switch("preview_full_color_switch", "preview_full_color"),
    VigiSwitchDescription(
        key="motion_enabled",
        translation_key="motion_detection",
        value_fn=lambda state: _on_off(_nested(state.motion, "motion_det", "enabled")),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_motion_value(
            "enabled", _enabled(enabled)
        ),
    ),
    VigiSwitchDescription(
        key="motion_people_enabled",
        translation_key="motion_people_detection",
        value_fn=lambda state: _on_off(_nested(state.motion, "motion_det", "people_enabled")),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_motion_value(
            "people_enabled", _enabled(enabled)
        ),
    ),
    VigiSwitchDescription(
        key="motion_vehicle_enabled",
        translation_key="motion_vehicle_detection",
        value_fn=lambda state: _on_off(_nested(state.motion, "motion_det", "vehicle_enabled")),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_motion_value(
            "vehicle_enabled", _enabled(enabled)
        ),
    ),
    VigiSwitchDescription(
        key="message_alarm_enabled",
        translation_key="message_alarm",
        value_fn=lambda state: _on_off(_nested(state.alarm, "chn1_msg_alarm_info", "enabled")),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_alarm_value(
            "enabled", _enabled(enabled)
        ),
    ),
    VigiSwitchDescription(
        key="message_alarm_light_enabled",
        translation_key="message_alarm_light",
        value_fn=lambda state: _on_off(
            _nested(state.alarm, "chn1_msg_alarm_info", "light_alarm_enabled")
        ),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_alarm_value(
            "light_alarm_enabled", _enabled(enabled)
        ),
    ),
    VigiSwitchDescription(
        key="message_alarm_sound_enabled",
        translation_key="message_alarm_sound",
        value_fn=lambda state: _on_off(
            _nested(state.alarm, "chn1_msg_alarm_info", "sound_alarm_enabled")
        ),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_alarm_value(
            "sound_alarm_enabled", _enabled(enabled)
        ),
    ),
    VigiSwitchDescription(
        key="lens_mask",
        translation_key="privacy_mask",
        value_fn=lambda state: _on_off(_nested(state.lens_mask, "lens_mask_info", "enabled")),
        set_fn=lambda coordinator, enabled: coordinator.client.async_set_lens_mask_enabled(enabled),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VigiControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [VigiCameraSwitch(coordinator, entry, description) for description in SWITCHES]
    )


class VigiCameraSwitch(VigiEntity, SwitchEntity):
    entity_description: VigiSwitchDescription

    def __init__(
        self,
        coordinator: VigiControlCoordinator,
        entry: ConfigEntry,
        description: VigiSwitchDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._host}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator, False)
        await self.coordinator.async_request_refresh()


def _on_off(value: Any) -> bool | None:
    if value == "on":
        return True
    if value == "off":
        return False
    return None


def _enabled(enabled: bool) -> str:
    return "on" if enabled else "off"


def _nested(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current

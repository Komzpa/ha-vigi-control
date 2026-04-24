from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import VigiControlCoordinator


class VigiEntity(CoordinatorEntity[VigiControlCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: VigiControlCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._host = entry.data[CONF_HOST]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            manufacturer=MANUFACTURER,
            model=coordinator.data.model,
            name=coordinator.device_name,
            sw_version=coordinator.data.firmware_version,
            configuration_url=f"https://{self._host}/",
        )


from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .vigi_api import VigiApiError, VigiCameraClient, VigiDeviceState

_LOGGER = logging.getLogger(__name__)


class VigiControlCoordinator(DataUpdateCoordinator[VigiDeviceState]):
    def __init__(self, hass: HomeAssistant, client: VigiCameraClient, name: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"VIGI Control {name}",
            update_interval=timedelta(minutes=2),
        )
        self.client = client
        self.device_name = name

    async def _async_update_data(self) -> VigiDeviceState:
        try:
            return await self.client.async_get_device_state()
        except VigiApiError as exc:
            raise UpdateFailed(str(exc)) from exc


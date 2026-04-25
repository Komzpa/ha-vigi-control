from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import device_registry as dr

from .const import CONF_FRIGATE_DEVICE_IDENTIFIER, DEFAULT_NAME, DOMAIN
from .frigate import find_existing_frigate_config, load_frigate_candidates
from .onvif_discovery import discover_onvif_candidates
from .vigi_api import VigiApiError, VigiCameraClient


class VigiControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _frigate_candidates = None
    _onvif_candidates = None

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(
            step_id="user",
            menu_options=["onvif", "frigate", "manual"],
        )

    async def async_step_manual(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            result = await self._async_validate_and_create_entry(user_input)
            if result.get("type") == "create_entry":
                return result
            if "base" in result:
                errors = result

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_USERNAME, default="admin"): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(
                        CONF_FRIGATE_DEVICE_IDENTIFIER,
                        default="",
                    ): vol.In(_frigate_camera_options(self.hass)),
                }
            ),
            errors=errors,
        )

    async def async_step_frigate(self, user_input=None):
        errors: dict[str, str] = {}
        default_path = find_existing_frigate_config() or "/config/frigate/config.yml"

        if user_input is not None:
            path = user_input["path"]
            try:
                candidates = load_frigate_candidates(path)
            except Exception:
                errors["base"] = "cannot_read_frigate_config"
            else:
                if not candidates:
                    errors["base"] = "no_frigate_cameras"
                else:
                    self._frigate_candidates = candidates
                    return await self.async_step_frigate_camera()

        return self.async_show_form(
            step_id="frigate",
            data_schema=vol.Schema({vol.Required("path", default=default_path): str}),
            errors=errors,
        )

    async def async_step_frigate_camera(self, user_input=None):
        errors: dict[str, str] = {}
        candidates = self._frigate_candidates or []

        if user_input is not None:
            candidate = candidates[int(user_input["camera"])]
            data = {
                CONF_NAME: candidate.name,
                CONF_HOST: candidate.host,
                CONF_USERNAME: user_input.get(CONF_USERNAME) or candidate.username or "admin",
                CONF_PASSWORD: user_input.get(CONF_PASSWORD) or candidate.password,
                CONF_FRIGATE_DEVICE_IDENTIFIER: _find_frigate_identifier_for_camera_key(
                    self.hass,
                    candidate.key,
                ),
            }
            result = await self._async_validate_and_create_entry(data)
            if result.get("type") == "create_entry":
                return result
            if "base" in result:
                errors = result

        options = {
            str(index): f"{candidate.name} ({candidate.host})"
            for index, candidate in enumerate(candidates)
        }
        first = candidates[0] if candidates else None
        return self.async_show_form(
            step_id="frigate_camera",
            data_schema=vol.Schema(
                {
                    vol.Required("camera"): vol.In(options),
                    vol.Required(
                        CONF_USERNAME,
                        default=(first.username if first else "admin") or "admin",
                    ): str,
                    vol.Required(
                        CONF_PASSWORD,
                        default=(first.password if first else "") or "",
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_onvif(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                candidates = await self.hass.async_add_executor_job(discover_onvif_candidates)
            except Exception:
                errors["base"] = "cannot_discover_onvif"
            else:
                candidates = [candidate for candidate in candidates if candidate.host]
                if not candidates:
                    errors["base"] = "no_onvif_cameras"
                else:
                    self._onvif_candidates = candidates
                    return await self.async_step_onvif_camera()

        return self.async_show_form(
            step_id="onvif",
            data_schema=vol.Schema({vol.Required("start", default=True): bool}),
            errors=errors,
        )

    async def async_step_onvif_camera(self, user_input=None):
        errors: dict[str, str] = {}
        candidates = self._onvif_candidates or []

        if user_input is not None:
            candidate = candidates[int(user_input["camera"])]
            data = {
                CONF_NAME: candidate.name or candidate.hardware or DEFAULT_NAME,
                CONF_HOST: candidate.host,
                CONF_USERNAME: user_input.get(CONF_USERNAME) or "admin",
                CONF_PASSWORD: user_input.get(CONF_PASSWORD),
                CONF_FRIGATE_DEVICE_IDENTIFIER: user_input.get(
                    CONF_FRIGATE_DEVICE_IDENTIFIER
                ),
            }
            result = await self._async_validate_and_create_entry(data)
            if result.get("type") == "create_entry":
                return result
            if "base" in result:
                errors = result

        options = {
            str(index): _format_onvif_candidate(candidate)
            for index, candidate in enumerate(candidates)
        }
        return self.async_show_form(
            step_id="onvif_camera",
            data_schema=vol.Schema(
                {
                    vol.Required("camera"): vol.In(options),
                    vol.Required(CONF_USERNAME, default="admin"): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(
                        CONF_FRIGATE_DEVICE_IDENTIFIER,
                        default="",
                    ): vol.In(_frigate_camera_options(self.hass)),
                }
            ),
            errors=errors,
        )

    async def _async_validate_and_create_entry(self, user_input):
        host = user_input[CONF_HOST].strip()
        client = VigiCameraClient(
            host,
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
        )
        try:
            await client.async_get_image_sections("switch", "common")
        except VigiApiError:
            return {"base": "cannot_connect"}

        await self.async_set_unique_id(host, raise_on_progress=False)
        self._abort_if_unique_id_configured()

        data = dict(user_input)
        data[CONF_HOST] = host
        if not data.get(CONF_FRIGATE_DEVICE_IDENTIFIER):
            data.pop(CONF_FRIGATE_DEVICE_IDENTIFIER, None)
        return self.async_create_entry(
            title=data.get(CONF_NAME) or host,
            data=data,
        )


def _format_onvif_candidate(candidate) -> str:
    label = f"{candidate.name} ({candidate.host})"
    if candidate.hardware and candidate.hardware != candidate.name:
        label += f" [{candidate.hardware}]"
    return label


def _frigate_camera_options(hass) -> dict[str, str]:
    options = {"": "Do not link to Frigate"}
    registry = dr.async_get(hass)
    for device in registry.devices.values():
        for domain, identifier in device.identifiers:
            if domain == "frigate" and ":" in identifier:
                options[identifier] = device.name or identifier.rsplit(":", 1)[-1]
    return dict(sorted(options.items(), key=lambda item: item[1]))


def _find_frigate_identifier_for_camera_key(hass, camera_key: str) -> str:
    suffix = f":{camera_key.lower()}"
    for identifier in _frigate_camera_options(hass):
        if identifier.lower().endswith(suffix):
            return identifier
    return ""

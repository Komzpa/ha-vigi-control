from __future__ import annotations

import asyncio
import base64
import hashlib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib import parse
from urllib.parse import unquote

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding


class VigiApiError(Exception):
    """Raised when the camera API rejects or cannot complete a request."""


@dataclass(frozen=True)
class VigiDeviceState:
    switch: Mapping[str, Any]
    common: Mapping[str, Any]
    device_info: Mapping[str, Any]
    video: Mapping[str, Any]
    motion: Mapping[str, Any]
    alarm: Mapping[str, Any]
    lens_mask: Mapping[str, Any]
    audio: Mapping[str, Any]

    def has_image_switch(self, key: str) -> bool:
        return key in self.switch

    def has_image_common(self, key: str) -> bool:
        return key in self.common

    def has_motion(self, key: str) -> bool:
        return _nested(self.motion, "motion_det", key) is not None

    def has_alarm(self, key: str) -> bool:
        return _nested(self.alarm, "chn1_msg_alarm_info", key) is not None

    def has_lens_mask(self, key: str) -> bool:
        return _nested(self.lens_mask, "lens_mask_info", key) is not None

    def has_speaker(self, key: str) -> bool:
        return _nested(self.audio, "speaker", key) is not None

    def has_video_main(self, key: str) -> bool:
        return _nested(self.video, "main", key) is not None

    @property
    def supports_white_light(self) -> bool:
        return self.has_image_switch("night_vision_mode") or self.has_image_common("wtl_type")

    @property
    def supports_white_light_level(self) -> bool:
        return self.has_image_switch("wtl_intensity_level") or self.has_image_common(
            "smartwtl_level"
        )

    @property
    def white_light_on(self) -> bool:
        return (
            self.switch.get("night_vision_mode") == "wtl_night_vision"
            or self.common.get("wtl_type") == "on"
        )

    @property
    def brightness(self) -> int:
        raw = self.switch.get("wtl_intensity_level") or self.common.get("smartwtl_level") or 3
        try:
            level = int(raw)
        except (TypeError, ValueError):
            return 153

        return max(1, min(255, round(max(1, min(5, level)) * 255 / 5)))

    @property
    def white_light_level(self) -> int:
        return VigiCameraClient.brightness_level(self.brightness)

    @property
    def night_vision_mode(self) -> str | None:
        value = self.switch.get("night_vision_mode")
        return value if isinstance(value, str) else None

    @property
    def white_light_type(self) -> str | None:
        value = self.common.get("wtl_type")
        return value if isinstance(value, str) else None

    @property
    def infrared_type(self) -> str | None:
        value = self.common.get("inf_type")
        return value if isinstance(value, str) else None

    @property
    def smart_white_light(self) -> str | None:
        value = self.common.get("smartwtl")
        return value if isinstance(value, str) else None

    @property
    def model(self) -> str | None:
        for key in ("model", "dev_model", "device_model", "product_model"):
            value = self.device_info.get(key)
            if isinstance(value, str) and value:
                return unquote(value)
        return None

    @property
    def firmware_version(self) -> str | None:
        for key in ("fw_ver", "firmware_version", "sw_version", "soft_version"):
            value = self.device_info.get(key)
            if isinstance(value, str) and value:
                return unquote(value)
        return None

    @property
    def speaker_volume(self) -> int | None:
        value = _nested(self.audio, "speaker", "volume")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @property
    def speaker_system_volume(self) -> int | None:
        value = _nested(self.audio, "speaker", "system_volume")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @property
    def alarm_type(self) -> str | None:
        value = _nested(self.alarm, "chn1_msg_alarm_info", "alarm_type")
        return value if isinstance(value, str) else None


def _nested(data: Mapping[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


class VigiCameraClient:
    _REQUEST_ATTEMPTS = 5
    _REQUEST_RETRY_DELAY_SECONDS = 0.5

    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self._stok: str | None = None
        self._lock = asyncio.Lock()

        self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2
        self._ssl_context.set_ciphers("AES256-GCM-SHA384")
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE

    async def async_get_device_state(self) -> VigiDeviceState:
        data = await self.async_get_image_sections("switch", "common")
        image = data.get("image", {})
        device_info = await self.async_get_device_info()
        video = await self._optional_request(
            {"method": "get", "video": {"name": ["main", "minor", "third"]}},
            "video",
        )
        motion = await self._optional_request(
            {"method": "get", "motion_detection": {"name": ["motion_det"]}},
            "motion_detection",
        )
        alarm = await self._optional_request(
            {"method": "get", "msg_alarm": {"name": ["chn1_msg_alarm_info"]}},
            "msg_alarm",
        )
        lens_mask = await self._optional_request(
            {"method": "get", "lens_mask": {"name": ["lens_mask_info"]}},
            "lens_mask",
        )
        audio = await self._optional_request(
            {"method": "get", "audio_config": {"name": ["speaker"]}},
            "audio_config",
        )
        return VigiDeviceState(
            switch=image.get("switch", {}) or {},
            common=image.get("common", {}) or {},
            device_info=device_info,
            video=video,
            motion=motion,
            alarm=alarm,
            lens_mask=lens_mask,
            audio=audio,
        )

    async def async_get_image_sections(self, *sections: str) -> dict[str, Any]:
        return await self._request({"method": "get", "image": {"name": list(sections)}})

    async def async_get_device_info(self) -> dict[str, Any]:
        # VIGI firmwares are not perfectly consistent here. Keep this opportunistic:
        # controls should still work even when the camera returns no model metadata.
        candidates = [
            {"method": "get", "system": {"name": ["device_info"]}},
            {"method": "get", "device_info": {"name": ["basic_info"]}},
        ]
        for body in candidates:
            try:
                data = await self._request(body)
            except VigiApiError:
                continue
            for section in ("system", "device_info"):
                value = data.get(section)
                if isinstance(value, dict):
                    nested = value.get("device_info") or value.get("basic_info") or value
                    if isinstance(nested, dict):
                        return nested
        return {}

    async def async_turn_white_light_on(self, brightness: int | None = None) -> None:
        async with self._lock:
            bodies: list[dict[str, Any]] = []
            if brightness is not None:
                bodies.extend(self._brightness_bodies(brightness))
            bodies.extend(
                [
                    {
                        "method": "set",
                        "image": {
                            "switch": {
                                "night_vision_mode": "wtl_night_vision",
                                "types": ["night_vision_mode"],
                            }
                        },
                    },
                    {
                        "method": "set",
                        "image": {
                            "common": {
                                "inf_type": "on",
                                "wtl_type": "on",
                                "types": ["inf_type", "wtl_type"],
                            }
                        },
                    },
                ]
            )
            for body in bodies:
                await self._request(body)

    async def async_set_white_light_brightness(self, brightness: int) -> None:
        async with self._lock:
            for body in self._brightness_bodies(brightness):
                await self._request(body)

    async def async_turn_white_light_off(self) -> None:
        async with self._lock:
            for body in [
                {
                    "method": "set",
                    "image": {
                        "common": {
                            "inf_type": "auto",
                            "wtl_type": "auto",
                            "types": ["inf_type", "wtl_type"],
                        }
                    },
                },
                {
                    "method": "set",
                    "image": {
                        "switch": {
                            "night_vision_mode": "inf_night_vision",
                            "types": ["night_vision_mode"],
                        }
                    },
                },
            ]:
                await self._request(body)

    async def async_set_night_vision_mode(self, mode: str) -> None:
        async with self._lock:
            await self.async_set_image_switch_value("night_vision_mode", mode, locked=True)

    async def async_set_image_switch_value(
        self,
        key: str,
        value: str,
        locked: bool = False,
    ) -> None:
        async def apply() -> None:
            await self._request(
                {"method": "set", "image": {"switch": {key: value, "types": [key]}}}
            )

        if locked:
            await apply()
            return

        async with self._lock:
            await apply()

    async def async_set_image_common_value(
        self,
        key: str,
        value: str | int,
        locked: bool = False,
    ) -> None:
        async def apply() -> None:
            await self._request(
                {"method": "set", "image": {"common": {key: str(value), "types": [key]}}}
            )

        if locked:
            await apply()
            return

        async with self._lock:
            await apply()

    async def async_set_motion_value(self, key: str, value: str | int) -> None:
        async with self._lock:
            await self._request(
                {
                    "method": "set",
                    "motion_detection": {
                        "motion_det": {key: value, "types": [key]},
                    },
                }
            )

    async def async_set_alarm_value(self, key: str, value: str | list[str]) -> None:
        async with self._lock:
            await self._request(
                {
                    "method": "set",
                    "msg_alarm": {
                        "chn1_msg_alarm_info": {key: value, "types": [key]},
                    },
                }
            )

    async def async_start_manual_alarm(self, alarm_type: str = "1") -> None:
        async with self._lock:
            await self._request(
                {
                    "method": "do",
                    "msg_alarm": {
                        "manual_msg_alarm": {
                            "action": "start",
                            "alarm_type": alarm_type,
                            "alarm_volume": "100",
                        },
                    },
                }
            )

    async def async_stop_manual_alarm(self) -> None:
        async with self._lock:
            await self._request(
                {
                    "method": "do",
                    "msg_alarm": {
                        "manual_msg_alarm": {
                            "action": "stop",
                        },
                    },
                }
            )

    async def async_test_alarm_audio(self, alarm_type: str) -> None:
        async with self._lock:
            await self._request(
                {
                    "method": "do",
                    "usr_def_audio_alarm": {
                        "test_audio": {
                            "id": int(alarm_type),
                        },
                    },
                }
            )

    async def async_set_lens_mask_enabled(self, enabled: bool) -> None:
        async with self._lock:
            await self._request(
                {
                    "method": "set",
                    "lens_mask": {
                        "lens_mask_info": {
                            "enabled": "on" if enabled else "off",
                            "types": ["enabled"],
                        },
                    },
                }
            )

    async def async_set_speaker_volume(self, volume: int) -> None:
        volume = max(0, min(100, round(volume)))
        async with self._lock:
            await self._request(
                {
                    "method": "set",
                    "audio_config": {
                        "speaker": {
                            "volume": str(volume),
                        },
                    },
                }
            )

    async def async_set_speaker_system_volume(self, volume: int) -> None:
        volume = max(0, min(100, round(volume)))
        async with self._lock:
            await self._request(
                {
                    "method": "set",
                    "audio_config": {
                        "speaker": {
                            "system_volume": str(volume),
                        },
                    },
                }
            )

    async def _optional_request(self, body: dict[str, Any], section: str) -> dict[str, Any]:
        try:
            data = await self._request(body)
        except VigiApiError:
            return {}

        value = data.get(section)
        return value if isinstance(value, dict) else {}

    async def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._stok is None:
            await self._login()

        data = await self._post(f"/stok={self._stok}/ds", body, allow_error=True)
        if data.get("error_code") == 0:
            return data

        self._stok = None
        await self._login()
        data = await self._post(f"/stok={self._stok}/ds", body)
        if data.get("error_code") != 0:
            raise VigiApiError(f"camera returned error {data}")
        return data

    async def _login(self) -> None:
        encrypt_info = await self._post(
            "/",
            {"user_management": {"get_encrypt_info": None}, "method": "do"},
            allow_error=True,
        )
        try:
            nonce = encrypt_info["data"]["nonce"]
            key = encrypt_info["data"]["key"]
        except KeyError as exc:
            raise VigiApiError(f"missing encryption info: {encrypt_info}") from exc

        password_hash = hashlib.md5(f"TPCQ75NF2Y:{self.password}".encode()).hexdigest().upper()
        public_key_der = base64.b64decode(parse.unquote(key))
        public_key = serialization.load_der_public_key(public_key_der)
        encrypted = base64.b64encode(
            public_key.encrypt(f"{password_hash}:{nonce}".encode(), padding.PKCS1v15())
        ).decode()

        auth = await self._post(
            "/",
            {
                "method": "do",
                "login": {
                    "username": self.username,
                    "password": encrypted,
                    "passwdType": "md5",
                    "encrypt_type": "2",
                },
            },
        )
        if auth.get("error_code") != 0 or "stok" not in auth:
            raise VigiApiError(f"authentication failed: {auth}")
        self._stok = auth["stok"]

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        allow_error: bool = False,
    ) -> dict[str, Any]:
        url = f"https://{self.host}{path}"
        timeout = aiohttp.ClientTimeout(
            total=6,
            connect=3,
            sock_connect=3,
            sock_read=4,
        )
        last_exc: Exception | None = None
        for attempt in range(self._REQUEST_ATTEMPTS):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        url,
                        json=body,
                        ssl=self._ssl_context,
                    ) as response:
                        data = await response.json(content_type=None)
                break
            except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                last_exc = exc
                if attempt + 1 >= self._REQUEST_ATTEMPTS:
                    raise VigiApiError(f"request failed for {self.host}") from exc
                await asyncio.sleep(self._REQUEST_RETRY_DELAY_SECONDS)
        else:
            raise VigiApiError(f"request failed for {self.host}") from last_exc

        if not allow_error and data.get("error_code") not in (0, None):
            raise VigiApiError(f"camera returned error {data}")
        return data

    @staticmethod
    def brightness_level(brightness: int) -> int:
        return max(1, min(5, round(brightness * 5 / 255)))

    @classmethod
    def brightness_from_level(cls, level: int) -> int:
        return max(1, min(255, round(max(1, min(5, level)) * 255 / 5)))

    @classmethod
    def _brightness_bodies(cls, brightness: int) -> list[dict[str, Any]]:
        level = cls.brightness_level(brightness)
        percent = level * 20
        return [
            {
                "method": "set",
                "image": {
                    "switch": {
                        "wtl_intensity_level": str(level),
                        "types": ["wtl_intensity_level"],
                    }
                },
            },
            {
                "method": "set",
                "image": {
                    "common": {
                        "smartwtl": "manual",
                        "smartwtl_level": str(level),
                        "smartwtl_digital_level": str(percent),
                        "types": [
                            "smartwtl",
                            "smartwtl_level",
                            "smartwtl_digital_level",
                        ],
                    }
                },
            },
        ]

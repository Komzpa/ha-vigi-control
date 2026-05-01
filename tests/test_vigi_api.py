import asyncio
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "vigi_control" / "vigi_api.py"
)
SPEC = spec_from_file_location("vigi_api", MODULE_PATH)
vigi_api = module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = vigi_api
SPEC.loader.exec_module(vigi_api)

VigiCameraClient = vigi_api.VigiCameraClient
VigiDeviceState = vigi_api.VigiDeviceState


def test_brightness_level_mapping_clamps_to_camera_scale():
    assert VigiCameraClient.brightness_level(1) == 1
    assert VigiCameraClient.brightness_level(51) == 1
    assert VigiCameraClient.brightness_level(102) == 2
    assert VigiCameraClient.brightness_level(153) == 3
    assert VigiCameraClient.brightness_level(204) == 4
    assert VigiCameraClient.brightness_level(255) == 5
    assert VigiCameraClient.brightness_level(999) == 5


def test_device_state_reads_known_white_light_fields():
    state = VigiDeviceState(
        switch={"night_vision_mode": "wtl_night_vision", "wtl_intensity_level": "5"},
        common={
            "wtl_type": "on",
            "inf_type": "on",
            "smartwtl": "manual",
            "smartwtl_level": "5",
        },
        device_info={"model": "VIGI C440-W", "fw_ver": "3.0.2"},
        video={},
        motion={},
        alarm={},
        lens_mask={},
        audio={"speaker": {"system_volume": "100", "volume": "80"}},
    )

    assert state.white_light_on is True
    assert state.brightness == 255
    assert state.white_light_level == 5
    assert state.night_vision_mode == "wtl_night_vision"
    assert state.white_light_type == "on"
    assert state.infrared_type == "on"
    assert state.smart_white_light == "manual"
    assert state.model == "VIGI C440-W"
    assert state.firmware_version == "3.0.2"
    assert state.speaker_volume == 80
    assert state.speaker_system_volume == 100


def test_device_state_treats_infrared_mode_as_white_light_off():
    state = VigiDeviceState(
        switch={"night_vision_mode": "inf_night_vision", "wtl_intensity_level": "3"},
        common={"wtl_type": "auto"},
        device_info={},
        video={},
        motion={},
        alarm={},
        lens_mask={},
        audio={},
    )

    assert state.white_light_on is False
    assert state.brightness == 153


def test_device_state_reports_supported_fields_from_payload_shape():
    state = VigiDeviceState(
        switch={"night_vision_mode": "inf_night_vision"},
        common={"wtl_type": "auto"},
        device_info={},
        video={"main": {"resolution": "2560*1440"}},
        motion={"motion_det": {"enabled": "on"}},
        alarm={"chn1_msg_alarm_info": {"enabled": "off"}},
        lens_mask={},
        audio={"speaker": {"system_volume": "100", "volume": "100"}},
    )

    assert state.supports_white_light is True
    assert state.supports_white_light_level is False
    assert state.has_video_main("resolution") is True
    assert state.has_motion("enabled") is True
    assert state.has_alarm("enabled") is True
    assert state.has_lens_mask("enabled") is False
    assert state.has_speaker("volume") is True
    assert state.has_speaker("system_volume") is True


async def _capture_request(client: VigiCameraClient, calls: list[dict]) -> None:
    async def fake_request(self, body):
        calls.append(body)
        return {"error_code": 0}

    client._request = types.MethodType(fake_request, client)


def test_start_manual_alarm_uses_vigi_manual_alarm_action():
    client = VigiCameraClient("camera.local", "user", "pass")
    calls: list[dict] = []
    asyncio.run(_capture_request(client, calls))

    asyncio.run(client.async_start_manual_alarm())

    assert calls == [
        {
            "method": "do",
            "msg_alarm": {
                "manual_msg_alarm": {
                    "action": "start",
                    "alarm_type": "1",
                    "alarm_volume": "100",
                }
            },
        }
    ]


def test_stop_manual_alarm_uses_vigi_manual_alarm_action():
    client = VigiCameraClient("camera.local", "user", "pass")
    calls: list[dict] = []
    asyncio.run(_capture_request(client, calls))

    asyncio.run(client.async_stop_manual_alarm())

    assert calls == [
        {
            "method": "do",
            "msg_alarm": {"manual_msg_alarm": {"action": "stop"}},
        }
    ]


def test_set_speaker_volume_clamps_and_uses_audio_config():
    client = VigiCameraClient("camera.local", "user", "pass")
    calls: list[dict] = []
    asyncio.run(_capture_request(client, calls))

    asyncio.run(client.async_set_speaker_volume(999))

    assert calls == [
        {
            "method": "set",
            "audio_config": {"speaker": {"volume": "100"}},
        }
    ]


def test_set_speaker_system_volume_clamps_and_uses_audio_config():
    client = VigiCameraClient("camera.local", "user", "pass")
    calls: list[dict] = []
    asyncio.run(_capture_request(client, calls))

    asyncio.run(client.async_set_speaker_system_volume(-1))

    assert calls == [
        {
            "method": "set",
            "audio_config": {"speaker": {"system_volume": "0"}},
        }
    ]

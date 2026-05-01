import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "vigi_control" / "go2rtc.py"
)
SPEC = spec_from_file_location("go2rtc", MODULE_PATH)
go2rtc = module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = go2rtc
SPEC.loader.exec_module(go2rtc)


def test_build_talkback_source_uses_vigi_pcma_file_input():
    assert go2rtc.build_talkback_source("http://ha.local/api/tts_proxy/a.mp3") == (
        "ffmpeg:http://ha.local/api/tts_proxy/a.mp3#audio=pcma#input=file"
    )


def test_build_stream_post_url_encodes_media_fragments():
    config = go2rtc.Go2RtcTalkConfig(
        api_url="http://go2rtc.local:1984/",
        stream="living_vigi",
    )

    url = go2rtc.build_stream_post_url(config, "http://ha.local/media/clip.mp3?x=1#frag")

    assert url.startswith("http://go2rtc.local:1984/api/streams?")
    assert "dst=living_vigi" in url
    assert "ffmpeg%3Ahttp%3A%2F%2Fha.local%2Fmedia%2Fclip.mp3%3Fx%3D1%23frag" in url
    assert "%23audio%3Dpcma%23input%3Dfile" in url


def test_talk_config_requires_api_url_and_stream():
    assert not go2rtc.Go2RtcTalkConfig(api_url="", stream="living_vigi").enabled
    assert not go2rtc.Go2RtcTalkConfig(api_url="http://go2rtc.local:1984", stream="").enabled
    assert go2rtc.Go2RtcTalkConfig(
        api_url="http://go2rtc.local:1984",
        stream="living_vigi",
    ).enabled


def test_build_rtsp_stream_url_uses_default_go2rtc_rtsp_port():
    config = go2rtc.Go2RtcTalkConfig(
        api_url="http://ccab4aaf-frigate:1984",
        stream="living_vigi",
    )

    assert go2rtc.build_rtsp_stream_url(config) == "rtsp://ccab4aaf-frigate:8554/living_vigi"


def test_build_rtsp_stream_url_prefers_microphone_stream():
    config = go2rtc.Go2RtcTalkConfig(
        api_url="http://ccab4aaf-frigate:1984",
        stream="living_vigi",
        mic_stream="living_sub",
    )

    assert go2rtc.build_rtsp_stream_url(config) == "rtsp://ccab4aaf-frigate:8554/living_sub"


def test_build_rtsp_stream_url_preserves_nonstandard_port():
    config = go2rtc.Go2RtcTalkConfig(
        api_url="http://go2rtc.local:11984",
        stream="living_vigi",
    )

    assert go2rtc.build_rtsp_stream_url(config) == "rtsp://go2rtc.local:11984/living_vigi"

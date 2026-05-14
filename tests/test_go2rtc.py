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


def test_build_stream_post_url_rewrites_home_assistant_tts_proxy_for_addon_go2rtc():
    config = go2rtc.Go2RtcTalkConfig(
        api_url="http://ccab4aaf-frigate:1984/",
        stream="living_vigi",
    )

    url = go2rtc.build_stream_post_url(
        config,
        "https://example.ui.nabu.casa/api/tts_proxy/token.mp3",
    )

    assert "ffmpeg%3Ahttp%3A%2F%2F172.30.32.1%3A8123%2Fapi%2Ftts_proxy%2Ftoken.mp3" in url


def test_build_stream_post_url_does_not_rewrite_unrelated_media_urls():
    config = go2rtc.Go2RtcTalkConfig(
        api_url="http://go2rtc.local:1984/",
        stream="living_vigi",
    )

    url = go2rtc.build_stream_post_url(config, "https://cdn.example.test/clip.mp3")

    assert "https%3A%2F%2Fcdn.example.test%2Fclip.mp3" in url


def test_build_stream_post_url_does_not_rewrite_tts_proxy_for_lan_go2rtc():
    config = go2rtc.Go2RtcTalkConfig(
        api_url="http://192.168.100.30:19840/",
        stream="living_vigi",
    )

    url = go2rtc.build_stream_post_url(
        config,
        "https://example.ui.nabu.casa/api/tts_proxy/token.mp3",
    )

    assert "ffmpeg%3Ahttps%3A%2F%2Fexample.ui.nabu.casa%2Fapi%2Ftts_proxy%2Ftoken.mp3" in url


def test_build_stop_playback_url_uses_empty_source_for_camera_playback():
    config = go2rtc.Go2RtcTalkConfig(
        api_url="http://go2rtc.local:1984/",
        stream="living_vigi",
    )

    assert (
        go2rtc.build_stop_playback_url(config)
        == "http://go2rtc.local:1984/api/streams?dst=living_vigi&src="
    )


def test_describe_media_url_keeps_logs_safe_and_useful():
    assert (
        go2rtc.describe_media_url(
            "http://user:secret@ha.local:8123/api/tts_proxy/token.mp3?auth=hidden"
        )
        == "http://ha.local:8123/api/tts_proxy/token.mp3"
    )
    assert go2rtc.describe_media_url("media-source://tts/cloud") == "media-source:"


def test_summarize_playback_response_recognizes_complete_talkback_snapshot():
    summary = go2rtc.summarize_playback_response(
        """
        {
          "producers": [
            {"url": "vigi://admin:pw@192.0.2.10"},
            {"url": "ffmpeg:http://172.30.32.1:8123/api/tts_proxy/a.mp3#audio=pcma#input=file"}
          ],
          "consumers": [
            {"format_name": "vigi", "protocol": "http", "medias": ["sendonly PCMA/8000"]}
          ]
        }
        """
    )

    assert summary.has_ffmpeg_producer
    assert summary.has_vigi_consumer
    assert summary.producer_count == 2
    assert summary.consumer_count == 1


def test_summarize_playback_response_recognizes_exec_ffmpeg_producer():
    summary = go2rtc.summarize_playback_response(
        """
        {
          "producers": [
            {"url": "exec:/usr/lib/ffmpeg/rpi/bin/ffmpeg -i http://172.30.32.1:8123/api/tts_proxy/a.mp3"}
          ],
          "consumers": [
            {"format_name": "vigi", "protocol": "http", "medias": ["sendonly PCMA/8000"]}
          ]
        }
        """
    )

    assert summary.has_ffmpeg_producer
    assert summary.has_vigi_consumer


def test_summarize_playback_response_flags_http_200_without_talkback_consumer():
    summary = go2rtc.summarize_playback_response(
        """
        {
          "producers": [
            {"url": "vigi://admin:pw@192.0.2.10"}
          ],
          "consumers": []
        }
        """
    )

    assert not summary.has_ffmpeg_producer
    assert not summary.has_vigi_consumer
    assert summary.producer_count == 1
    assert summary.consumer_count == 0


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

from pathlib import Path

ASSIST_SATELLITE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "vigi_control"
    / "assist_satellite.py"
)


def test_assist_satellite_streams_pcm_for_home_assistant_stt():
    source = ASSIST_SATELLITE.read_text(encoding="utf-8")

    assert "stt.AudioFormats.WAV" in source
    assert "stt.AudioCodecs.PCM" in source
    assert '"s16le"' in source
    assert "pipe:1" in source


def test_assist_satellite_does_not_send_ogg_opus_to_home_assistant_stt():
    source = ASSIST_SATELLITE.read_text(encoding="utf-8")

    assert "stt.AudioFormats.OGG" not in source
    assert "stt.AudioCodecs.OPUS" not in source
    assert "libopus" not in source


def test_assist_satellite_uses_home_assistant_pipeline_not_direct_agent_bridge():
    source = ASSIST_SATELLITE.read_text(encoding="utf-8")

    assert "conversation.async_converse" in source
    assert "_process_openclaw_audio" not in source
    assert "_process_openclaw_text" not in source
    assert "openclaw_agent_url" not in source

from pathlib import Path

INIT = Path(__file__).resolve().parents[1] / "custom_components" / "vigi_control" / "__init__.py"

ASSIST_SATELLITE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "vigi_control"
    / "assist_satellite.py"
)


def test_vigi_control_does_not_expose_generic_media_player_platform():
    source = INIT.read_text(encoding="utf-8")

    assert "Platform.MEDIA_PLAYER" not in source


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


def test_assist_satellite_can_save_stt_audio_captures():
    source = ASSIST_SATELLITE.read_text(encoding="utf-8")

    assert "CONF_ASSIST_SAVE_AUDIO" in source
    assert "vigi_assist_captures" in source
    assert "wave.open" in source
    assert "_capture_audio_stream" in source


def test_assist_satellite_prunes_captures_by_disk_budget():
    source = ASSIST_SATELLITE.read_text(encoding="utf-8")

    assert "CONF_ASSIST_AUDIO_RETENTION_MB" in source
    assert "retention_bytes" in source
    assert "MAX_ASSIST_AUDIO_CAPTURES" not in source
    assert "total_bytes <= retention_bytes" in source

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "vigi_control" / "frigate.py"
)
SPEC = spec_from_file_location("frigate", MODULE_PATH)
frigate = module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = frigate
SPEC.loader.exec_module(frigate)

load_frigate_candidates = frigate.load_frigate_candidates


def test_load_frigate_candidates_extracts_rtsp_credentials(tmp_path: Path):
    config = tmp_path / "config.yml"
    config.write_text(
        """
cameras:
  living:
    ffmpeg:
      inputs:
        - path: rtsp://admin:p%23ss@example.local:554/stream1
          roles: [detect]
  bedroom_camera:
    ffmpeg:
      inputs:
        - path: rtsp://viewer:secret@192.168.1.28/stream2
""",
        encoding="utf-8",
    )

    candidates = load_frigate_candidates(str(config))

    assert [candidate.name for candidate in candidates] == ["Living", "Bedroom Camera"]
    assert candidates[0].host == "example.local"
    assert candidates[0].username == "admin"
    assert candidates[0].password == "p#ss"
    assert candidates[1].host == "192.168.1.28"

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "vigi_control"
    / "onvif_discovery.py"
)
SPEC = spec_from_file_location("onvif_discovery", MODULE_PATH)
onvif_discovery = module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = onvif_discovery
SPEC.loader.exec_module(onvif_discovery)

_candidate_from_service = onvif_discovery._candidate_from_service
_deduplicate_candidates = onvif_discovery._deduplicate_candidates
_is_vigi_service = onvif_discovery._is_vigi_service


class FakeScope:
    def __init__(self, value: str) -> None:
        self._value = value

    def getValue(self) -> str:
        return self._value


class FakeService:
    def __init__(self, name: str = "VIGI-C440-W", hardware: str = "VIGI-C440-W") -> None:
        self._name = name
        self._hardware = hardware

    def getXAddrs(self) -> list[str]:
        return ["http://192.168.100.28:2020/onvif/device_service"]

    def getEPR(self) -> str:
        return "uuid:3fa1fe68-b915-4053-a3e1-788cb526e859"

    def getScopes(self) -> list[FakeScope]:
        return [
            FakeScope(f"onvif://www.onvif.org/name/{self._name}"),
            FakeScope(f"onvif://www.onvif.org/hardware/{self._hardware}"),
            FakeScope("onvif://www.onvif.org/Profile/Streaming"),
        ]


def test_candidate_from_service_extracts_vigi_onvif_identity():
    candidate = _candidate_from_service(FakeService())

    assert candidate.name == "VIGI-C440-W"
    assert candidate.host == "192.168.100.28"
    assert candidate.port == 2020
    assert candidate.hardware == "VIGI-C440-W"
    assert candidate.xaddr == "http://192.168.100.28:2020/onvif/device_service"
    assert "onvif://www.onvif.org/hardware/VIGI-C440-W" in candidate.scopes


def test_deduplicate_candidates_keeps_one_entry_per_host():
    first = _candidate_from_service(FakeService())
    duplicate = _candidate_from_service(FakeService())

    assert _deduplicate_candidates([first, duplicate]) == [first]


def test_vigi_service_filter_accepts_vigi_scopes_only():
    assert _is_vigi_service(FakeService()) is True
    assert _is_vigi_service(FakeService(name="GenericCam", hardware="IPC-123")) is False

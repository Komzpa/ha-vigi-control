from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class OnvifCameraCandidate:
    name: str
    host: str
    port: int
    hardware: str | None
    device_id: str | None
    xaddr: str


def discover_onvif_candidates(timeout: int = 8) -> list[OnvifCameraCandidate]:
    from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery
    from wsdiscovery.qname import QName
    from wsdiscovery.scope import Scope

    discovery = WSDiscovery(ttl=4, relates_to=True)
    try:
        discovery.start()
        services = discovery.searchServices(
            types=[
                QName(
                    "http://www.onvif.org/ver10/network/wsdl",
                    "NetworkVideoTransmitter",
                    "tdn",
                )
            ],
            scopes=[Scope("onvif://www.onvif.org/Profile/Streaming")],
            timeout=timeout,
        )
        return _deduplicate_candidates(_candidate_from_service(service) for service in services)
    finally:
        discovery.stop()


def _candidate_from_service(service) -> OnvifCameraCandidate:
    xaddr = service.getXAddrs()[0]
    parsed = urlparse(xaddr)
    name = service.getEPR()
    hardware = None
    device_id = None

    for scope in service.getScopes():
        scope_value = scope.getValue()
        scope_lower = scope_value.lower()
        if scope_lower.startswith("onvif://www.onvif.org/name/"):
            name = unquote(scope_value.rsplit("/", 1)[-1])
        elif scope_lower.startswith("onvif://www.onvif.org/hardware/"):
            hardware = unquote(scope_value.rsplit("/", 1)[-1])
        elif scope_lower.startswith("onvif://www.onvif.org/mac/"):
            device_id = unquote(scope_value.rsplit("/", 1)[-1]).lower()

    return OnvifCameraCandidate(
        name=name,
        host=parsed.hostname or "",
        port=parsed.port or 80,
        hardware=hardware,
        device_id=device_id,
        xaddr=xaddr,
    )


def _deduplicate_candidates(candidates) -> list[OnvifCameraCandidate]:
    by_host: dict[str, OnvifCameraCandidate] = {}
    for candidate in candidates:
        if not candidate.host:
            continue
        by_host.setdefault(candidate.host, candidate)
    return sorted(by_host.values(), key=lambda candidate: (candidate.name, candidate.host))

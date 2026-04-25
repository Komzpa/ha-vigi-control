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
    scopes: tuple[str, ...]


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
        return _deduplicate_candidates(
            candidate
            for service in services
            if _is_vigi_service(service)
            for candidate in [_candidate_from_service(service)]
        )
    finally:
        discovery.stop()


def _candidate_from_service(service) -> OnvifCameraCandidate:
    xaddr = service.getXAddrs()[0]
    parsed = urlparse(xaddr)
    name = service.getEPR()
    hardware = None
    device_id = None
    scopes = tuple(scope.getValue() for scope in service.getScopes())

    for scope_value in scopes:
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
        scopes=scopes,
    )


def _is_vigi_service(service) -> bool:
    candidate = _candidate_from_service(service)
    markers = [candidate.name, candidate.hardware or "", *candidate.scopes]
    return any("vigi" in marker.lower() for marker in markers)


def _deduplicate_candidates(candidates) -> list[OnvifCameraCandidate]:
    by_host: dict[str, OnvifCameraCandidate] = {}
    for candidate in candidates:
        if not candidate.host:
            continue
        by_host.setdefault(candidate.host, candidate)
    return sorted(by_host.values(), key=lambda candidate: (candidate.name, candidate.host))

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml

DEFAULT_FRIGATE_CONFIG_PATHS = [
    "/addon_configs/ccab4aaf_frigate/config.yml",
    "/addon_configs/ccab4aaf_frigate/config.yaml",
    "/config/frigate.yml",
    "/config/frigate.yaml",
    "/config/frigate/config.yml",
    "/config/frigate/config.yaml",
    "/config/config.yml",
    "/config/config.yaml",
]


@dataclass(frozen=True)
class FrigateCameraCandidate:
    key: str
    name: str
    host: str
    username: str | None
    password: str | None
    source_url: str


def find_existing_frigate_config() -> str | None:
    for path in DEFAULT_FRIGATE_CONFIG_PATHS:
        if Path(path).exists():
            return path
    return None


def load_frigate_candidates(path: str) -> list[FrigateCameraCandidate]:
    with Path(path).open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    cameras = config.get("cameras", {}) if isinstance(config, dict) else {}
    if not isinstance(cameras, dict):
        return []

    candidates: list[FrigateCameraCandidate] = []
    for camera_name, camera_config in cameras.items():
        for raw_url in _iter_camera_urls(camera_config):
            candidate = _candidate_from_url(str(camera_name), raw_url)
            if candidate is not None:
                candidates.append(candidate)
                break

    return candidates


def _iter_camera_urls(camera_config: Any) -> list[str]:
    urls: list[str] = []
    if not isinstance(camera_config, dict):
        return urls

    ffmpeg = camera_config.get("ffmpeg", {})
    if not isinstance(ffmpeg, dict):
        return urls

    inputs = ffmpeg.get("inputs", [])
    if not isinstance(inputs, list):
        return urls

    for item in inputs:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if isinstance(path, str) and path.startswith(("rtsp://", "rtsps://", "http://", "https://")):
            urls.append(path)

    return urls


def _candidate_from_url(key: str, raw_url: str) -> FrigateCameraCandidate | None:
    parsed = urlparse(raw_url)
    if not parsed.hostname:
        return None

    return FrigateCameraCandidate(
        key=key,
        name=key.replace("_", " ").title(),
        host=parsed.hostname,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
        source_url=raw_url,
    )

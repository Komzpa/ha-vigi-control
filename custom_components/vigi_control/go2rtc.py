from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlunparse

import aiohttp


class Go2RtcError(Exception):
    """Raised when go2rtc cannot start a VIGI talk-back stream."""


@dataclass(frozen=True)
class Go2RtcTalkConfig:
    api_url: str
    stream: str
    mic_stream: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.api_url.strip() and self.stream.strip())


def normalize_go2rtc_api_url(value: str) -> str:
    """Return the go2rtc API root without a trailing slash."""

    return value.strip().rstrip("/")


def build_talkback_source(media_url: str) -> str:
    """Build the go2rtc ffmpeg source used for VIGI two-way audio.

    VIGI C440-W advertises G.711 A-law speaker decode support. go2rtc names
    that RTP codec `pcma`, and will transcode arbitrary media URLs through
    ffmpeg before sending the camera backchannel.
    """

    return f"ffmpeg:{media_url}#audio=pcma#input=file"


def build_stream_post_url(config: Go2RtcTalkConfig, media_url: str) -> str:
    """Build a go2rtc `/api/streams` POST URL for camera talk-back playback."""

    root = normalize_go2rtc_api_url(config.api_url)
    query = urlencode(
        {
            "dst": config.stream.strip(),
            "src": build_talkback_source(media_url),
        }
    )
    return f"{root}/api/streams?{query}"


def build_rtsp_stream_url(config: Go2RtcTalkConfig, stream: str | None = None) -> str:
    """Build the RTSP URL for reading a go2rtc stream from the same service."""

    root = normalize_go2rtc_api_url(config.api_url)
    parsed = urlparse(root)
    if not parsed.hostname:
        raise Go2RtcError("go2rtc API URL has no host")

    stream_name = (stream or config.mic_stream or config.stream).strip()
    port = 8554 if parsed.port == 1984 else parsed.port
    netloc = parsed.hostname if port is None else f"{parsed.hostname}:{port}"
    return urlunparse(("rtsp", netloc, f"/{stream_name}", "", "", ""))


async def async_play_talkback_url(
    session: aiohttp.ClientSession,
    config: Go2RtcTalkConfig,
    media_url: str,
) -> None:
    """Ask go2rtc to play a media URL through the camera backchannel."""

    if not config.enabled:
        raise Go2RtcError("go2rtc talk-back is not configured")

    url = build_stream_post_url(config, media_url)
    async with session.post(url) as response:
        body = await response.text()
        if response.status >= 400:
            raise Go2RtcError(f"go2rtc returned HTTP {response.status}: {body[:300]}")

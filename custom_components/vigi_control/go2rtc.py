from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlencode, urlparse, urlunparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

GO2RTC_HOME_ASSISTANT_MEDIA_BASE_URL = "http://172.30.32.1:8123"
HOME_ASSISTANT_MEDIA_PATH_PREFIXES = (
    "/api/tts_proxy/",
    "/api/media_player_proxy/",
    "/local/",
)
SUPERVISOR_GO2RTC_HOSTS = {
    "ccab4aaf-frigate",
    "ccab4aaf-frigate-beta",
}


class Go2RtcError(Exception):
    """Raised when go2rtc cannot start a VIGI talk-back stream."""


@dataclass(frozen=True)
class Go2RtcPlaybackSummary:
    has_ffmpeg_producer: bool
    has_vigi_consumer: bool
    producer_count: int
    consumer_count: int
    description: str


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


def _go2rtc_uses_supervisor_network(api_url: str) -> bool:
    """Return true when go2rtc is expected to reach the HA Supervisor gateway."""

    parsed = urlparse(api_url.strip())
    hostname = (parsed.hostname or "").lower()
    return hostname in SUPERVISOR_GO2RTC_HOSTS or hostname.startswith("172.30.")


def normalize_media_url_for_go2rtc(media_url: str, go2rtc_api_url: str = "") -> str:
    """Rewrite Home Assistant media URLs to the add-on reachable HA endpoint.

    Home Assistant may resolve TTS media through its external/base URL. The
    Frigate go2rtc add-on should fetch those files through the Supervisor network
    gateway instead. LAN or remote go2rtc instances cannot reach that gateway, so
    they keep the original media URL.
    """

    parsed = urlparse(media_url.strip())
    if parsed.scheme not in {"http", "https"}:
        return media_url
    if not _go2rtc_uses_supervisor_network(go2rtc_api_url):
        return media_url
    if not any(parsed.path.startswith(prefix) for prefix in HOME_ASSISTANT_MEDIA_PATH_PREFIXES):
        return media_url

    internal = urlparse(GO2RTC_HOME_ASSISTANT_MEDIA_BASE_URL)
    return urlunparse(
        (
            internal.scheme,
            internal.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def describe_media_url(media_url: str) -> str:
    """Return a log-safe media URL description."""

    parsed = urlparse(media_url.strip())
    if not parsed.scheme:
        return "relative-or-local"
    if parsed.scheme in {"http", "https"}:
        netloc = parsed.hostname or ""
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        return f"{parsed.scheme}://{netloc}{parsed.path}"
    return f"{parsed.scheme}:"


def build_stream_post_url(config: Go2RtcTalkConfig, media_url: str) -> str:
    """Build a go2rtc `/api/streams` POST URL for camera talk-back playback."""

    root = normalize_go2rtc_api_url(config.api_url)
    media_url = normalize_media_url_for_go2rtc(media_url, config.api_url)
    query = urlencode(
        {
            "dst": config.stream.strip(),
            "src": build_talkback_source(media_url),
        }
    )
    return f"{root}/api/streams?{query}"


def build_stop_playback_url(config: Go2RtcTalkConfig) -> str:
    """Build a go2rtc `/api/streams` URL that stops active camera playback."""

    root = normalize_go2rtc_api_url(config.api_url)
    query = urlencode(
        {
            "dst": config.stream.strip(),
            "src": "",
        }
    )
    return f"{root}/api/streams?{query}"


def summarize_playback_response(body: str) -> Go2RtcPlaybackSummary:
    """Extract the parts of go2rtc `/api/streams` output that prove playback.

    The API returns a stream snapshot even when the POST itself is HTTP 200. For
    VIGI announcement playback we expect an ffmpeg file producer and a VIGI
    talk-back consumer. If either side is missing, Home Assistant can mark the
    announce service done while no audible audio reached the camera.
    """

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Go2RtcPlaybackSummary(
            has_ffmpeg_producer=False,
            has_vigi_consumer=False,
            producer_count=0,
            consumer_count=0,
            description="non-json response",
        )

    producers = payload.get("producers")
    consumers = payload.get("consumers")
    if not isinstance(producers, list):
        producers = []
    if not isinstance(consumers, list):
        consumers = []

    producer_text = "\n".join(
        json.dumps(producer, sort_keys=True)
        for producer in producers
        if isinstance(producer, dict)
    ).lower()
    has_ffmpeg_producer = "ffmpeg" in producer_text
    has_vigi_consumer = any(
        isinstance(consumer, dict)
        and (
            str(consumer.get("format_name") or "").lower() == "vigi"
            or str(consumer.get("protocol") or "").lower() == "http"
            and "pcma" in json.dumps(consumer, sort_keys=True).lower()
        )
        for consumer in consumers
    )

    return Go2RtcPlaybackSummary(
        has_ffmpeg_producer=has_ffmpeg_producer,
        has_vigi_consumer=has_vigi_consumer,
        producer_count=len(producers),
        consumer_count=len(consumers),
        description=(
            f"producers={len(producers)} ffmpeg={has_ffmpeg_producer}; "
            f"consumers={len(consumers)} vigi={has_vigi_consumer}"
        ),
    )


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

    media_url = normalize_media_url_for_go2rtc(media_url, config.api_url)
    stop_url = build_stop_playback_url(config)
    url = build_stream_post_url(config, media_url)
    media_description = describe_media_url(media_url)
    async with session.post(stop_url) as response:
        body = await response.text()
        if response.status >= 400:
            raise Go2RtcError(f"go2rtc stop returned HTTP {response.status}: {body[:300]}")

    started = monotonic()
    async with session.post(url) as response:
        body = await response.text()
        elapsed = monotonic() - started
        if response.status >= 400:
            raise Go2RtcError(f"go2rtc returned HTTP {response.status}: {body[:300]}")

        summary = summarize_playback_response(body)
        if not summary.has_ffmpeg_producer or not summary.has_vigi_consumer:
            _LOGGER.warning(
                "go2rtc talk-back POST returned without complete playback evidence: "
                "stream=%s media=%s status=%s elapsed=%.2fs %s",
                config.stream,
                media_description,
                response.status,
                elapsed,
                summary.description,
            )
            return

        _LOGGER.info(
            "go2rtc talk-back playback accepted: stream=%s media=%s status=%s elapsed=%.2fs %s",
            config.stream,
            media_description,
            response.status,
            elapsed,
            summary.description,
        )

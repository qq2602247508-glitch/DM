from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx

from dnd_dm_assistant.domain.ingestion_ports import FetchedPage
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy, UrlRejected


class FetchError(RuntimeError):
    pass


class RobotsDenied(FetchError):
    pass


class ResponseTooLarge(FetchError):
    pass


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 20.0
    max_response_bytes: int = 2_097_152
    delay_seconds: float = 1.0
    retries: int = 2
    backoff_seconds: float = 1.0
    concurrency: int = 1
    max_redirects: int = 3


class SafeHttpFetcher:
    def __init__(
        self,
        *,
        policy: UrlPolicy,
        config: FetchConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.policy = policy
        self.config = config
        timeout = httpx.Timeout(
            connect=config.connect_timeout_seconds,
            read=config.read_timeout_seconds,
            write=config.read_timeout_seconds,
            pool=config.connect_timeout_seconds,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": config.user_agent, "Accept": "text/html,*/*;q=0.1"},
        )
        self._semaphore = asyncio.Semaphore(config.concurrency)
        self._rate_lock = asyncio.Lock()
        self._last_request_started = 0.0
        self._robots: RobotFileParser | None = None
        self.robots_status: str | None = None

    async def __aenter__(self) -> SafeHttpFetcher:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _wait_for_slot(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            wait_seconds = self.config.delay_seconds - (now - self._last_request_started)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_started = time.monotonic()

    async def _one_request(self, url: str) -> tuple[httpx.Response, bytes]:
        await self._wait_for_slot()
        request = self._client.build_request("GET", url)
        response = await self._client.send(request, stream=True)
        try:
            length_header = response.headers.get("content-length")
            if length_header:
                try:
                    declared_length = int(length_header)
                except ValueError as exc:
                    raise FetchError("invalid Content-Length header") from exc
                if declared_length > self.config.max_response_bytes:
                    raise ResponseTooLarge(
                        f"declared response size {declared_length} exceeds "
                        f"{self.config.max_response_bytes}"
                    )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self.config.max_response_bytes:
                    raise ResponseTooLarge(
                        f"streamed response exceeds {self.config.max_response_bytes} bytes"
                    )
            return response, bytes(body)
        finally:
            await response.aclose()

    async def _request(self, url: str) -> tuple[httpx.Response, bytes, str]:
        current = self.policy.without_fragment(url)
        for redirect_index in range(self.config.max_redirects + 1):
            response: httpx.Response | None = None
            body = b""
            for attempt in range(self.config.retries + 1):
                try:
                    response, body = await self._one_request(current)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt >= self.config.retries:
                        raise FetchError(f"network error for {current}: {exc}") from exc
                    await asyncio.sleep(self.config.backoff_seconds * (2**attempt))
                    continue
                if response.status_code >= 500 and attempt < self.config.retries:
                    await asyncio.sleep(self.config.backoff_seconds * (2**attempt))
                    continue
                break
            if response is None:
                raise FetchError(f"no response for {current}")
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response, body, current
            if redirect_index >= self.config.max_redirects:
                raise FetchError("redirect limit exceeded")
            location = response.headers.get("location")
            if not location:
                raise FetchError("redirect omitted Location")
            try:
                current = self.policy.without_fragment(urljoin(current, location))
            except UrlRejected as exc:
                raise FetchError(f"redirect rejected: {exc}") from exc
        raise FetchError("redirect loop")

    async def check_robots(self) -> str:
        robots_url = self.policy.canonicalize("/robots.txt", keep_fragment=False)
        async with self._semaphore:
            response, body, final_url = await self._request(robots_url)
        if final_url != robots_url:
            robots_url = final_url
        if response.status_code == 404:
            self._robots = RobotFileParser()
            self._robots.set_url(robots_url)
            self._robots.parse([])
            self.robots_status = "not_published_404"
            return self.robots_status
        if response.status_code != 200:
            raise RobotsDenied(f"robots fetch failed closed with HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "text/plain")
        text = _decode_http_body(body, content_type)
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.parse(text.splitlines())
        except Exception as exc:
            raise RobotsDenied(f"robots parse failed closed: {exc}") from exc
        self._robots = parser
        self.robots_status = "loaded"
        return self.robots_status

    async def fetch(self, url: str) -> FetchedPage:
        canonical = self.policy.canonicalize(url)
        target = self.policy.without_fragment(canonical)
        if self._robots is None:
            await self.check_robots()
        if self._robots is None or not self._robots.can_fetch(self.config.user_agent, target):
            raise RobotsDenied(f"robots disallows {target}")
        async with self._semaphore:
            response, body, final_url = await self._request(target)
        if response.status_code != 200:
            raise FetchError(f"content fetch returned HTTP {response.status_code}: {target}")
        media_type = response.headers.get("content-type", "")
        if media_type and not any(
            allowed in media_type.lower()
            for allowed in ("text/html", "application/xhtml+xml", "text/plain")
        ):
            raise FetchError(f"unexpected content type: {media_type}")
        return FetchedPage(
            requested_url=canonical,
            canonical_url=final_url,
            body=body,
            content_type=media_type,
            fetched_at=datetime.now(UTC),
            status_code=response.status_code,
        )


def _decode_http_body(body: bytes, content_type: str) -> str:
    message = Message()
    message["content-type"] = content_type
    charset = message.get_content_charset() or "utf-8"
    try:
        return body.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise RobotsDenied(f"robots has an invalid charset/body: {charset}") from exc

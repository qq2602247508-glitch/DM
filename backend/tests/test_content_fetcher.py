from __future__ import annotations

import asyncio

import httpx
import pytest

from dnd_dm_assistant.integrations.content.fetcher import (
    FetchConfig,
    FetchError,
    ResponseTooLarge,
    RobotsDenied,
    SafeHttpFetcher,
)
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy


def _policy() -> UrlPolicy:
    return UrlPolicy(
        base_url="https://5echm.kagangtuya.top/",
        allowed_hosts=frozenset({"5echm.kagangtuya.top"}),
    )


def _config(*, max_bytes: int = 1024) -> FetchConfig:
    return FetchConfig(
        user_agent="test-agent",
        max_response_bytes=max_bytes,
        delay_seconds=0,
        retries=0,
    )


def test_robots_404_allows_bounded_fetch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})

    async def run() -> None:
        async with SafeHttpFetcher(
            policy=_policy(),
            config=_config(),
            transport=httpx.MockTransport(handler),
        ) as fetcher:
            assert await fetcher.check_robots() == "not_published_404"
            page = await fetcher.fetch("/topics/test.htm")
            assert b"ok" in page.body

    asyncio.run(run())


def test_robots_disallow_and_error_fail_closed() -> None:
    async def disallow_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /topics/")
        return httpx.Response(200, text="should-not-fetch")

    async def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run() -> None:
        async with SafeHttpFetcher(
            policy=_policy(),
            config=_config(),
            transport=httpx.MockTransport(disallow_handler),
        ) as fetcher:
            with pytest.raises(RobotsDenied):
                await fetcher.fetch("/topics/test.htm")
        async with SafeHttpFetcher(
            policy=_policy(),
            config=_config(),
            transport=httpx.MockTransport(error_handler),
        ) as fetcher:
            with pytest.raises(RobotsDenied):
                await fetcher.check_robots()

    asyncio.run(run())


def test_off_host_redirect_and_oversize_are_rejected() -> None:
    async def redirect_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://evil.invalid/a"})

    async def oversize_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=b"x" * 20,
            headers={"content-type": "text/html", "content-length": "20"},
        )

    async def run() -> None:
        async with SafeHttpFetcher(
            policy=_policy(),
            config=_config(),
            transport=httpx.MockTransport(redirect_handler),
        ) as fetcher:
            with pytest.raises(FetchError, match="redirect rejected"):
                await fetcher.fetch("/topics/test.htm")
        async with SafeHttpFetcher(
            policy=_policy(),
            config=_config(max_bytes=10),
            transport=httpx.MockTransport(oversize_handler),
        ) as fetcher:
            with pytest.raises(ResponseTooLarge):
                await fetcher.fetch("/topics/test.htm")

    asyncio.run(run())

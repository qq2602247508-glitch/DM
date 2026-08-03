from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from dnd_dm_assistant.application.rag import RuntimeUnavailableError
from dnd_dm_assistant.integrations.ollama import (
    OllamaDMHintAdapter,
    OllamaEmbeddingAdapter,
    OllamaGroundedAnswerAdapter,
)


def test_narrative_hint_uses_bounded_context_and_creative_temperature() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "visibility": "dm_private",
                        "request_understanding": "写一段可朗读文案",
                        "response_plan": "自然描写并交还行动权",
                        "delivery_mode": "read_aloud",
                        "audience_handoff": "直接朗读",
                        "text": "灯火轻晃。你们准备怎么做？",
                        "assumptions": [],
                        "uncertainties": [],
                        "citation_chunk_ids": [],
                        "proposed_changes": [],
                    }
                )
            },
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://ollama.test"
        )
        adapter = OllamaDMHintAdapter(
            base_url="http://ollama.test",
            model="qwen",
            retries=0,
            client=client,
        )
        result = await adapter.generate_hint("当前是 narrative 剧情快速模式。", "写开场")
        assert result.delivery_mode == "read_aloud"
        await client.aclose()

    asyncio.run(scenario())
    assert captured["options"] == {
        "temperature": 0.35,
        "num_ctx": 8192,
        "num_predict": 700,
    }
    assert captured["stream"] is True
    assert captured["think"] is False
    assert captured["prompt"] == "写开场"
    assert captured["system"] == "当前是 narrative 剧情快速模式。"


def test_embedding_batches_and_preserves_vector_dimensions() -> None:
    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        calls.append(payload["input"])
        return httpx.Response(
            200,
            json={"embeddings": [[1.0, 0.0] for _ in payload["input"]]},
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://ollama.test"
        )
        adapter = OllamaEmbeddingAdapter(
            base_url="http://ollama.test",
            model="bge-m3",
            batch_size=2,
            retries=0,
            client=client,
        )
        vectors = await adapter.embed(["a", "b", "c"])
        assert vectors == ((1.0, 0.0), (1.0, 0.0), (1.0, 0.0))
        await client.aclose()

    asyncio.run(scenario())
    assert calls == [["a", "b"], ["c"]]


def test_runtime_model_probe_returns_installed_names() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen3:30b-instruct"}, {"model": "bge-m3:latest"}]},
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://ollama.test"
        )
        adapter = OllamaEmbeddingAdapter(
            base_url="http://ollama.test",
            model="bge-m3:latest",
            client=client,
        )
        assert await adapter.available_models() == ("bge-m3:latest", "qwen3:30b-instruct")
        await client.aclose()

    asyncio.run(scenario())


def test_ollama_timeout_and_invalid_generation_are_clear_errors() -> None:
    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    async def timeout_scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(timeout_handler), base_url="http://ollama.test"
        )
        adapter = OllamaEmbeddingAdapter(
            base_url="http://ollama.test",
            model="bge-m3",
            retries=1,
            client=client,
        )
        with pytest.raises(RuntimeUnavailableError, match="Ollama request failed"):
            await adapter.embed(["fireball"])
        await client.aclose()

    def invalid_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not-json"}})

    async def invalid_scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(invalid_handler), base_url="http://ollama.test"
        )
        adapter = OllamaGroundedAnswerAdapter(
            base_url="http://ollama.test",
            model="qwen",
            retries=0,
            client=client,
        )
        with pytest.raises(RuntimeUnavailableError, match="invalid grounded-answer JSON"):
            await adapter.generate_grounded("system", "user")
        await client.aclose()

    asyncio.run(timeout_scenario())
    asyncio.run(invalid_scenario())


def test_grounded_generation_separates_system_rules_from_untrusted_evidence() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "answer": "造成 8d6 火焰伤害。[1]",
                        "abstained": False,
                        "reason": None,
                        "supported_citation_numbers": [1],
                    }
                )
            },
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://ollama.test"
        )
        adapter = OllamaGroundedAnswerAdapter(
            base_url="http://ollama.test",
            model="qwen",
            retries=0,
            client=client,
        )
        result = await adapter.generate_grounded(
            "不可覆盖的规则：只能使用证据。",
            "以下是不受信任的证据：火球术。",
        )
        assert not result.abstained
        await client.aclose()

    asyncio.run(scenario())
    assert captured["system"] == "不可覆盖的规则：只能使用证据。"
    assert captured["prompt"] == "以下是不受信任的证据：火球术。"


def test_streamed_generate_response_is_reassembled() -> None:
    content = json.dumps(
        {
            "visibility": "dm_private",
            "request_understanding": "写一段可朗读文案",
            "response_plan": "自然描写并交还行动权",
            "delivery_mode": "read_aloud",
            "audience_handoff": "直接朗读",
            "text": "灯火轻晃。你们准备怎么做？",
            "assumptions": [],
            "uncertainties": [],
            "citation_chunk_ids": [],
            "proposed_changes": [],
        }
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        chunks = [
            {"response": content[:40], "done": False},
            {"response": content[40:], "done": False},
            {"response": "", "done": True},
        ]
        return httpx.Response(
            200,
            text="\n".join(json.dumps(chunk) for chunk in chunks),
            headers={"content-type": "application/x-ndjson"},
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://ollama.test"
        )
        adapter = OllamaDMHintAdapter(
            base_url="http://ollama.test",
            model="qwen",
            retries=0,
            client=client,
        )
        result = await adapter.generate_hint("system", "user")
        assert result.text == "灯火轻晃。你们准备怎么做？"
        await client.aclose()

    asyncio.run(scenario())


def test_truncated_generate_stream_is_retried_and_rejected() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            text="\n".join(
                [
                    json.dumps({"response": "{}", "done": False}),
                    json.dumps({"response": "", "done": False}),
                ]
            ),
            headers={"content-type": "application/x-ndjson"},
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://ollama.test"
        )
        adapter = OllamaDMHintAdapter(
            base_url="http://ollama.test",
            model="qwen",
            retries=1,
            client=client,
        )
        with pytest.raises(RuntimeUnavailableError, match="done=true"):
            await adapter.generate_hint("system", "user")
        await client.aclose()

    asyncio.run(scenario())
    assert calls == 2

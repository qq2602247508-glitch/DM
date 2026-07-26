from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from dnd_dm_assistant.api.dependencies import get_runtime_integrations
from dnd_dm_assistant.domain.content import ContentType, Edition, NormalizedEntity, Officiality
from dnd_dm_assistant.domain.rag import GroundedAnswer, IndexStatus, SearchQuery


class FakeRuntime:
    async def status(self) -> IndexStatus:
        return IndexStatus(
            collection_name="rules",
            available=True,
            points_count=42,
            vector_size=1024,
            indexed_records=12,
            embedding_model="fake",
        )

    async def search(self, _query: SearchQuery) -> tuple[()]:
        return ()

    async def answer(self, _question: str, _query: SearchQuery | None = None) -> GroundedAnswer:
        return GroundedAnswer(
            answer="没有足够证据。",
            abstained=True,
            reason="no_evidence",
        )

    def get_document(self, record_id: str) -> NormalizedEntity | None:
        if record_id != "fireball":
            return None
        return NormalizedEntity(
            stable_id="fireball",
            name="火球术",
            content_type=ContentType.SPELLS,
            source_url="https://example.test/fireball",
            canonical_url="https://example.test/fireball",
            edition=Edition.EDITION_2024,
            officiality=Officiality.OFFICIAL,
            content_markdown="# 火球术\n完整正文",
            content_plain_text="火球术 完整正文",
            checksum="checksum",
            fetched_at=datetime.now(UTC),
            run_id="test",
        )


def test_knowledge_api_contracts(client: TestClient) -> None:
    client.app.dependency_overrides[get_runtime_integrations] = lambda: FakeRuntime()
    try:
        status = client.get("/api/v1/knowledge/index/status")
        search = client.post("/api/v1/knowledge/search", json={"text": "火球术"})
        answer = client.post(
            "/api/v1/knowledge/answer",
            json={"question": "火球术伤害是多少？"},
        )
        document = client.get("/api/v1/knowledge/documents/fireball")
    finally:
        client.app.dependency_overrides.clear()

    assert status.status_code == 200
    assert status.json()["vector_size"] == 1024
    assert search.status_code == 200
    assert search.json() == {"hits": []}
    assert answer.status_code == 200
    assert answer.json() == {
        "answer": "没有足够证据。",
        "abstained": True,
        "reason": "no_evidence",
        "citations": [],
    }
    assert document.status_code == 200
    assert document.json()["content_plain_text"] == "火球术 完整正文"


def test_knowledge_answer_rejects_blank_question(client: TestClient) -> None:
    response = client.post("/api/v1/knowledge/answer", json={"question": "   \n  "})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"

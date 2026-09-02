"""Cross-document story synthesis: blends universal-read facts + effective
terms into one narrative with observations. Advisory display text only —
money-language guarded, no records created."""

import base64
from pathlib import Path

import pytest

from app.main import app
from app.master.routes import get_storyteller
from app.master.story import build_story_digest, parse_story

POF_B64 = base64.b64encode(
    (Path(__file__).parent / "fixtures" / "synthetic_pof.pdf").read_bytes()
).decode()


class FakeStoryteller:
    def __init__(self, story=None):
        self.digests: list[str] = []
        self.story = story or {
            "narrative": "The deal opened with a purchase agreement; an addendum followed.",
            "observations": [
                {"text": "The addendum references a rider that is not on file.",
                 "severity": "warn", "sources": ["Synthetic addendum"]},
            ],
        }

    def tell(self, digest: str):
        self.digests.append(digest)
        return parse_story(self.story)


@pytest.fixture
def storyteller():
    fake = FakeStoryteller()
    app.dependency_overrides[get_storyteller] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_storyteller, None)


def _deal_with_doc(client, tc_headers):
    txn_id = client.post(
        "/transactions", json={"property_address": "7 Story St"}, headers=tc_headers
    ).json()["id"]
    item = client.post(
        "/ingestion/manual-upload",
        json={"filename": "addendum-synthetic.pdf", "content_base64": POF_B64, "doc_type": "other"},
        headers=tc_headers,
    ).json()
    client.post(
        f"/ingestion/inbox/{item['id']}/confirm",
        json={"decision": txn_id, "doc_type": "other", "label": "Synthetic addendum"},
        headers=tc_headers,
    )
    return txn_id


def test_story_blends_documents(client, tc_headers, storyteller):
    txn_id = _deal_with_doc(client, tc_headers)
    r = client.post(f"/transactions/{txn_id}/story", headers=tc_headers)
    assert r.status_code == 200
    body = r.json()
    assert "purchase agreement" in body["narrative"]
    assert body["observations"][0]["severity"] == "warn"
    # The digest fed to the model carries the universal-read facts, not raw docs.
    digest = storyteller.digests[0]
    assert "Synthetic addendum" in digest
    assert "Effective date = 2026-07-10" in digest
    assert "storage" not in digest.lower()


def test_story_requires_documents(client, tc_headers, storyteller):
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Story St"}, headers=tc_headers
    ).json()["id"]
    r = client.post(f"/transactions/{txn_id}/story", headers=tc_headers)
    assert r.status_code == 409


def test_story_money_language_rejected(client, tc_headers):
    fake = FakeStoryteller(
        story={
            "narrative": "Wire the deposit using routing number 12345.",
            "observations": [],
        }
    )
    app.dependency_overrides[get_storyteller] = lambda: fake
    try:
        txn_id = _deal_with_doc(client, tc_headers)
        r = client.post(f"/transactions/{txn_id}/story", headers=tc_headers)
        assert r.status_code == 422
        assert "Rule 2" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_storyteller, None)


def test_digest_is_structured_only(repo, client, tc_headers):
    txn_id = _deal_with_doc(client, tc_headers)
    digest = build_story_digest(repo.get_full_state(txn_id))
    assert "PROPERTY: 7 Story St" in digest
    assert "DOCUMENTS ON FILE" in digest
    assert "summary:" in digest  # universal-read summary rides along

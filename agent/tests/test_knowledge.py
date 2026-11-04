"""The parent guide from a Bedrock Knowledge Base (decision 028), with a fake Retrieve client."""

import json

import pytest

from gs_agent import gateway_client as G
from gs_agent import knowledge as K
from gs_agent import search
from gs_agent.agent import Decision, GuidedSession

URI = "s3://gs-guide-docs/guide/charter-school.md"
SOURCE = "GreatSchools guide (team-written summary for this demo)"


def hit(entry_id, title, score, uri=None, body="A free public school run by its own board.", aliases="charter, lottery"):
    uri = uri or f"s3://gs-guide-docs/guide/{entry_id}.md"
    return {"content": {"text": f"# {title}\n\nAlso called: {aliases}.\n\n{body}\n"},
            "location": {"type": "S3", "s3Location": {"uri": uri}},
            "score": score,
            "metadata": {"id": entry_id, "title": title, "kind": "term", "source": SOURCE,
                         "x-amz-bedrock-kb-source-uri": uri}}


class FakeRetrieve:
    def __init__(self, results):
        self.results, self.calls = results, []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return {"retrievalResults": self.results}


@pytest.fixture
def kb(monkeypatch):
    def use(results):
        fake = FakeRetrieve(results)
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KBTEST123")
        monkeypatch.setattr(K, "_client", lambda: fake)
        return fake
    return use


def test_retrieve_results_become_guide_entries_with_their_document(kb):
    fake = kb([hit("charter-school", "Charter school", 0.928, uri=URI),  # Retrieve scores are (1 + cosine) / 2
               hit("magnet-school", "Magnet school", 0.70, aliases="magnet"),
               hit("charter-school", "Charter school", 0.80, uri=URI),  # a second chunk of the same entry
               hit("voucher", "Voucher", 0.55, aliases="voucher")])                       # cosine 0.1: too far from the question
    entries = K.lookup("What is a charter school?")
    assert fake.calls[0]["knowledgeBaseId"] == "KBTEST123"
    assert fake.calls[0]["retrievalQuery"] == {"text": "What is a charter school?"}
    assert [e["id"] for e in entries] == ["charter-school", "magnet-school"]
    assert entries[0] == {"id": "charter-school", "kind": "term", "title": "Charter school",
                          "body": "A free public school run by its own board.", "source": SOURCE,
                          "document": "charter-school.md", "uri": URI, "similarity": 0.856,
                          "term_match": True}


def test_unrelated_questions_and_hits_without_metadata_return_nothing(kb):
    kb([hit("voucher", "Voucher", 0.53), {"content": {"text": "stray"}, "score": 0.9, "metadata": {}}])
    assert K.lookup("best pizza near me") == []


def test_a_title_or_alias_in_the_question_keeps_a_weak_vector_hit(kb):
    kb([hit("cte", "Career and technical education (CTE)", 0.6, body="Classes that teach job skills.",
            aliases="CTE, career education"),
        hit("charter-school", "Charter school", 0.6)])  # cosine 0.2, but its alias "lottery" is asked about
    assert [e["id"] for e in K.lookup("what is a lottery?")] == ["charter-school"]
    assert K.lookup("what is a lottery?", everyday=frozenset({"lottery"})) == []


def test_lookup_content_uses_the_knowledge_base_when_configured(kb, monkeypatch):
    kb([hit("charter-school", "Charter school", 0.9)])
    monkeypatch.setattr(search, "client", lambda: pytest.fail("OpenSearch must not be called"))
    assert [e["id"] for e in search.lookup_content("charter?")] == ["charter-school"]


def test_without_a_knowledge_base_id_the_guide_stays_on_opensearch(monkeypatch):
    monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
    monkeypatch.setattr(K, "lookup", lambda *a: pytest.fail("the knowledge base must not be called"))

    class FakeOpenSearch:
        def search(self, index, body):
            assert index == search.CONTENT_INDEX
            return {"hits": {"hits": [{"_id": "cte", "_score": 0.9,
                                       "_source": {"id": "cte", "title": "CTE", "body": "b", "source": "s"}}]}}
    monkeypatch.setattr(search, "client", lambda: FakeOpenSearch())
    monkeypatch.setattr(search, "embed", lambda text: [0.0])
    assert [e["id"] for e in search.lookup_content("what is CTE")] == ["cte"]
    assert not K.enabled()


def test_guide_answer_cites_the_knowledge_base_document(kb, monkeypatch):
    kb([hit("charter-school", "Charter school", 0.9, uri=URI)])
    monkeypatch.setattr(G, "GATEWAY_URL", None)
    s = GuidedSession("kb-cite")
    lookup_content = next(t for t in s._tools() if t.tool_name == "lookup_content")
    out = json.loads(lookup_content(question="What is a charter school?"))

    assert out["entries"][0]["document"] == "charter-school.md"
    step = s._trace[-1]
    assert step["tool"] == "lookup_content" and step["service"] == "Amazon Bedrock Knowledge Base"
    assert "Charter school (charter-school.md)" in step["text"]

    decision = Decision(chips=[], message="A charter school is a free public school.", sources=["charter-school"])
    text = next(b for b in s._blocks(decision)["blocks"] if b["type"] == "text")
    assert text["sources"] == [{"id": "charter-school", "title": "Charter school", "document": "charter-school.md"}]

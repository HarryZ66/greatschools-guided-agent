"""Model tiers (decision 034): code picks the model per turn, and a failed fast turn goes to the strong one."""

from types import SimpleNamespace

import pytest

from gs_agent import agent as A
from gs_agent import routing
from gs_agent.agent import Decision, GuidedSession

FAST, STRONG = routing.FAST_MODEL, routing.STRONG_MODEL


@pytest.mark.parametrize("text", [
    "Elementary schools near Miami with fewer Hispanic students",
    "Which neighborhood has fewer low-income families?",
    "My son has ADHD and needs extra help. High school near Doral",
    "Escuela con pocos inmigrantes en Hialeah",
    "A school near my church",
])
def test_sensitive_topics_go_to_the_strong_model(text):
    assert routing.choose(text) == (STRONG, "sensitive topic")


@pytest.mark.parametrize("text", [
    "Middle school near Miami with STEM. I work until 6pm",
    "What is a charter school?",
    "Free elementary school in Hialeah with a bus",
    "(Answer to your question \"Is 5pm pickup ok?\"): The library club could work",
])
def test_everyday_turns_go_to_the_fast_model(text):
    assert routing.choose(text) == (FAST, None)


def test_main_model_pins_every_turn(monkeypatch):
    monkeypatch.setattr(routing, "MAIN_MODEL", "pinned")
    assert routing.choose("fewer Hispanic students") == ("pinned", None)
    assert routing.choose("STEM", strong_already=True) == ("pinned", None)


class FakeAgent:
    """Stands in for the Strands agent: records the model of each call and can fail on one model."""

    def __init__(self, fail_on: str | None = None):
        self.messages, self.models, self.fail_on = [], [], fail_on
        self.calls = 0

    def __call__(self, text, structured_output_model=None):
        model_id = self.model.config["model_id"]
        self.models.append(model_id)
        if model_id == self.fail_on:
            raise RuntimeError("no structured reply")
        self.calls += 1
        usage = {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0}
        metrics = SimpleNamespace(accumulated_usage={k: v * self.calls for k, v in usage.items()},
                                  cycle_count=self.calls)
        return SimpleNamespace(metrics=metrics, structured_output=Decision(chips=[], message="Here you go."))


def session_with(fake: FakeAgent, retry: FakeAgent | None = None) -> GuidedSession:
    s = GuidedSession("routing")
    s.agent = fake
    s._new_agent = lambda **k: retry or FakeAgent()
    return s


def test_a_plain_turn_runs_on_the_fast_model_and_says_so():
    fake = FakeAgent()
    s = session_with(fake)
    out = s.handle({"type": "query", "text": "What is a charter school?"})
    assert fake.models == [FAST]
    step = out["trace"]["steps"][0]
    assert step["tool"] == "understand" and step["service"] == "Claude Haiku 5.5 on Amazon Bedrock"
    assert set(s.usage_by_model) == {FAST} and s.usage_by_model[FAST]["outputTokens"] == 5


def test_a_sensitive_conversation_stays_on_the_strong_model_until_a_new_search():
    fake = FakeAgent()
    s = session_with(fake)
    s.handle({"type": "query", "text": "Schools near Miami with fewer Hispanic students"})
    out = s.handle({"type": "query", "text": "OK, show me ones with a bus"})
    assert fake.models == [STRONG, STRONG]
    assert "stronger model from earlier" in out["trace"]["steps"][0]["text"]
    s.handle({"type": "new_search"})
    s.agent = fake
    s.handle({"type": "query", "text": "Middle school near Miami with STEM"})
    assert fake.models[-1] == FAST


def test_a_failed_fast_turn_is_retried_on_the_strong_model():
    fast, strong = FakeAgent(fail_on=FAST), FakeAgent()
    s = session_with(fast, retry=strong)
    out = s.handle({"type": "query", "text": "Middle school near Miami with STEM"})
    assert "fallback" not in out
    assert fast.models == [FAST] and strong.models == [STRONG]
    tools = [st["tool"] for st in out["trace"]["steps"]]
    assert tools[:2] == ["understand", "escalate"]
    assert out["trace"]["steps"][0]["service"] == "Claude Sonnet 5.5 on Amazon Bedrock"
    assert any(b["type"] == "text" and b["markdown"] == "Here you go." for b in out["blocks"])
    assert not s._strong  # one failed turn doesn't move the whole conversation


def test_models_are_shared_between_sessions():
    assert A.bedrock_model(FAST) is A.bedrock_model(FAST)
    assert A.bedrock_model(FAST).config["model_id"] == FAST


def test_every_turn_runs_on_sonnet_by_default(monkeypatch):
    """Decision 040: without MAIN_MODEL set, every turn is pinned to Sonnet 5.5."""
    import importlib

    from gs_agent import config
    monkeypatch.delenv("MAIN_MODEL", raising=False)
    try:
        assert importlib.reload(config).MAIN_MODEL == "us.anthropic.claude-sonnet-5-5"
        monkeypatch.setenv("MAIN_MODEL", "")
        assert importlib.reload(config).MAIN_MODEL is None  # empty: the tiers decide
    finally:
        monkeypatch.setenv("MAIN_MODEL", "")
        importlib.reload(config)

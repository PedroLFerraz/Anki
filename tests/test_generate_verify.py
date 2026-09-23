import json
from unittest.mock import MagicMock

import pytest
from conftest import RUN_DATE, FakeLLM

from ankigen import generate, llm, verify
from ankigen.generate import clean_field, fix_cloze_syntax, parse_cards
from ankigen.profile import Profile

# ---------------------------------------------------------------- parsing (ported from v1)


@pytest.mark.parametrize("raw,fixed", [
    ("The {c1::dog} is big.", "The {{c1::dog}} is big."),
    ("The {{{c1::cat}}} is small.", "The {{c1::cat}} is small."),
    ("The {{dog}} is big.", "The {{c1::dog}} is big."),
    ("The {{c1::mitochondria}} is fine.", "The {{c1::mitochondria}} is fine."),
])
def test_fix_cloze_syntax(raw, fixed):
    assert fix_cloze_syntax(raw) == fixed


def test_clean_field():
    assert clean_field("## Heading") == "Heading"
    assert clean_field("- Item") == "Item"
    assert clean_field("* Bold *") == "Bold"


def test_parse_basic_skips_low_quality():
    cards = parse_cards("basic", {"cards": [
        {"question": "Hi", "answer": ""},
        {"question": "What is gravity?", "answer": "A force."},
        "not a dict",
    ]})
    assert [c.front for c in cards] == ["What is gravity?"]


def test_parse_cloze_requires_a_deletion():
    cards = parse_cards("cloze", {"cards": [
        {"text": "No deletion here at all.", "extra": ""},
        {"text": "The {c1::heart} pumps blood.", "extra": "organ"},
    ]})
    assert len(cards) == 1
    assert cards[0].fields == {"Text": "The {{c1::heart}} pumps blood.", "Extra": "organ"}
    assert cards[0].front == "The heart pumps blood."


def test_parse_detailed_falls_back_to_first_sentence():
    [card] = parse_cards("detailed", {"cards": [
        {"question": "What is gradient descent?", "summary": "",
         "explanation": "An optimisation method. It follows the gradient."},
    ]})
    assert card.back == "An optimisation method."


def test_parse_tolerates_garbage():
    assert parse_cards("basic", {"cards": "nope"}) == []
    assert parse_cards("basic", []) == []


# ---------------------------------------------------------------- llm plumbing (ported)

def test_extract_json_variants():
    assert llm.extract_json('{"a": 1}') == '{"a": 1}'
    assert llm.extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert llm.extract_json('Sure:\n{"cards": []}\nDone!') == '{"cards": []}'


def test_json_mode_rejection_falls_back_and_is_remembered(monkeypatch):
    monkeypatch.setattr(llm, "_no_json_mode", set())
    client = MagicMock()

    def create(**kwargs):
        if "response_format" in kwargs:
            raise Exception("400: response_format is not supported")
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content='```json\n{"ok": true}\n```'))]
        resp.usage = MagicMock(prompt_tokens=7, completion_tokens=3)
        return resp

    client.chat.completions.create.side_effect = create
    text, p, c = llm._chat_json(client, "m", "prompt")
    assert json.loads(text) == {"ok": True} and (p, c) == (7, 3)
    assert "m" in llm._no_json_mode


def test_unrelated_errors_are_not_swallowed(monkeypatch):
    monkeypatch.setattr(llm, "_no_json_mode", set())
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception("401 invalid api key")
    with pytest.raises(Exception, match="invalid api key"):
        llm._chat_json(client, "m", "prompt")


def test_error_inside_a_200_response_is_retried(monkeypatch):
    """OpenRouter reports provider outages as {"error": ...} with choices=None."""
    monkeypatch.setattr(llm, "_no_json_mode", set())
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    client = MagicMock()

    bad = MagicMock(choices=None, error={"message": "Upstream error: Service temporarily overloaded"})
    good = MagicMock()
    good.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
    good.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
    good.error = None
    client.chat.completions.create.side_effect = [bad, good]
    monkeypatch.setattr(llm, "_get_openai_client", lambda *a: client)

    assert llm.call_json("p").data == {"ok": True}      # retried, not a TypeError


def test_provider_error_detection():
    assert llm._provider_error(MagicMock(choices=None, error={"message": "boom"})) == "boom"
    assert llm._provider_error(MagicMock(choices=[], error=None)) == "provider returned no choices"
    ok = MagicMock(error=None)
    ok.choices = [MagicMock()]
    assert llm._provider_error(ok) is None


@pytest.mark.parametrize("msg,retry", [
    ("429 Rate limit reached", True),
    ("Service temporarily overloaded", True),
    ("503 upstream", True),
    ("401 invalid api key", False),
    ("model not found", False),
])
def test_retryable_classification(msg, retry):
    assert llm._is_retryable(msg) is retry


def test_paid_openrouter_model_is_blocked(monkeypatch):
    from ankigen.config import PaidModelBlocked, Settings
    monkeypatch.setattr(llm, "settings",
                        Settings(_env_file=None, llm_provider="openrouter",
                                 llm_api_key="k", llm_model="openai/gpt-5"))
    with pytest.raises(PaidModelBlocked, match="not a ':free' model"):
        llm.call_json("p")


def test_rate_limit_waits_for_groq_hint(monkeypatch):
    waits = []
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    responses = iter([Exception("429 Rate limit reached. Please try again in 7.5s."), '{"cards": []}'])

    def chat(client, model, prompt):
        r = next(responses)
        if isinstance(r, Exception):
            raise r
        return r, 1, 1

    monkeypatch.setattr(llm, "_chat_json", chat)
    monkeypatch.setattr(llm, "_get_openai_client", lambda *a: None)
    llm.call_json("p")
    assert waits == [9.5]                                      # hint + 2s margin, not a blind 20s


# ---------------------------------------------------------------- generate stage

def _request(n=3, card_type="basic", rid="r1"):
    return {"request_id": rid, "deck": "DS::SQL", "card_type": card_type, "n": n,
            "prompt": 'DECK: DS::SQL\nWrite exactly 3 new cards about: "joins".'}


def test_generate_tops_up_when_model_returns_too_few(monkeypatch):
    replies = iter([
        {"cards": [{"question": "What is an inner join?", "answer": "Matching rows only."}]},
        {"cards": [{"question": "What is a left join?", "answer": "All left rows."},
                   {"question": "What is a cross join?", "answer": "Cartesian product."}]},
    ])
    prompts = []
    monkeypatch.setattr(llm, "call_json", lambda p: (prompts.append(p), llm.LLMResult(next(replies), "m", 10, 5))[1])
    cards, _, p_tok, _ = generate.generate_for_request(_request())
    assert len(cards) == 3 and p_tok == 20
    assert "What is an inner join?" in prompts[1]              # told what it already wrote


def test_one_failing_request_does_not_sink_the_run(wh, monkeypatch):
    def call(prompt):
        if "boom" in prompt:
            raise RuntimeError("provider down")
        return llm.LLMResult({"cards": [{"question": "What is X?", "answer": "Y."}]}, "m", 5, 5)

    monkeypatch.setattr(llm, "call_json", call)
    bad = {**_request(n=1, rid="bad"), "prompt": "boom"}
    result = generate.run(wh, RUN_DATE, [bad, _request(n=1, rid="ok")])
    assert result["cards"] == 1
    assert result["failed_requests"][0]["request_id"] == "bad"
    assert result["prompt_tokens"] == 5


def test_losing_every_request_fails_the_run(wh, monkeypatch):
    """A rate-limited run once finished green with an empty package, because
    the later stages cannot tell "nothing generated" from "nothing to do"."""
    def call(prompt):
        raise RuntimeError("Error code: 429 - rate limit exceeded: free-models-per-day")

    monkeypatch.setattr(llm, "call_json", call)
    with pytest.raises(generate.GenerationFailed, match="429"):
        generate.run(wh, RUN_DATE, [_request(rid="a"), _request(rid="b")])
    # The partition is still replaced first, so a retry starts from a clean slate.
    assert wh.scalar("SELECT COUNT(*) FROM generated_cards WHERE run_date = ?", [RUN_DATE]) == 0


# ---------------------------------------------------------------- verify

def _cards():
    return [{"front": "Q1", "back": "A1"}, {"front": "Q2", "back": "A2"},
            {"front": "Q3", "back": "A3"}, {"front": "Q4", "back": "A4"}]


def test_judge_maps_verdicts_by_index():
    verdicts = verify.judge([
        {"index": 1, "correct": True, "answerable": True, "score": 0.9},
        {"index": 2, "correct": False, "answerable": True, "score": 0.8, "issue": "wrong date"},
        {"index": 3, "correct": True, "answerable": False, "score": 0.8, "issue": "ambiguous"},
    ], _cards())
    assert verdicts[0] == (True, 0.9, "")
    assert verdicts[1][0] is False and "incorrect: wrong date" in verdicts[1][2]
    assert "unanswerable" in verdicts[2][2]
    assert verdicts[3][0] is True and verdicts[3][2].startswith(verify.UNVERIFIED)


def test_low_score_fails():
    [(passed, _, reason)] = verify.judge(
        [{"index": 1, "correct": True, "answerable": True, "score": 0.4, "issue": "trivial"}], _cards()[:1])
    assert not passed and "low quality" in reason


def _seed_generated(wh):
    wh.replace_partition("generated_cards", RUN_DATE, generate.GENERATED_COLUMNS, [
        (RUN_DATE, "u1", "r1", "DS::SQL", "basic", "Is the earth flat?", "Yes.", "{}", "", "m", 0, 0),
        (RUN_DATE, "u2", "r1", "DS::SQL", "basic", "What is SQL?", "A query language.", "{}", "", "m", 0, 0),
    ])


def test_verify_drops_incorrect_cards(wh, monkeypatch):
    _seed_generated(wh)
    monkeypatch.setattr(llm, "call_json", FakeLLM(bad_words=("flat",)))
    result = verify.run(wh, RUN_DATE, Profile.model_validate({"decks": [{"deck": "DS::SQL"}]}))
    assert (result["passed"], result["dropped"]) == (1, 1)


def test_verify_asks_the_configured_checker_model(wh, monkeypatch):
    """The checker is pointed at its own model so it is not the generator
    reviewing itself."""
    from ankigen.config import settings

    monkeypatch.setattr(settings, "verify_provider", "gemini", raising=False)
    monkeypatch.setattr(settings, "verify_model", "gemini-3.6-flash", raising=False)
    monkeypatch.setattr(settings, "google_api_key", "k", raising=False)

    seen = {}

    def spy(prompt, max_retries=5, cfg=None):
        seen.update(cfg or {})
        return FakeLLM()(prompt)

    _seed_generated(wh)
    monkeypatch.setattr(llm, "call_json", spy)
    verify.run(wh, RUN_DATE, Profile.model_validate({"decks": [{"deck": "DS::SQL"}]}))
    assert (seen["provider"], seen["model"]) == ("gemini", "gemini-3.6-flash")


def test_checker_outage_passes_cards_as_unverified(wh, monkeypatch):
    _seed_generated(wh)
    monkeypatch.setattr(llm, "call_json", FakeLLM(fail_verify=True))
    result = verify.run(wh, RUN_DATE, Profile.model_validate({"decks": [{"deck": "DS::SQL"}]}))
    assert result["passed"] == 2 and result["unverified"] == 2 and result["checker_errors"] == 1


def test_verify_disabled(wh, monkeypatch):
    _seed_generated(wh)
    monkeypatch.setattr(llm, "call_json", lambda p: pytest.fail("should not call the LLM"))
    result = verify.run(wh, RUN_DATE, Profile.model_validate({"verify": False, "decks": [{"deck": "DS::SQL"}]}))
    assert result["passed"] == 2


# ---------------------------------------------------------------- preflight

def test_preflight_catches_a_missing_provider_package(monkeypatch):
    """CI installed the package without its [gemini] extra, and the run only
    found out after ingest, once per request."""
    from ankigen.config import settings

    monkeypatch.setattr(settings, "llm_provider", "gemini", raising=False)
    monkeypatch.setattr(settings, "google_api_key", "k", raising=False)
    monkeypatch.setattr(llm, "_gemini_client", None, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "google.genai", None)

    with pytest.raises(RuntimeError, match="google-genai"):
        llm.preflight()


def test_preflight_catches_a_missing_key(monkeypatch):
    from ankigen.config import settings

    monkeypatch.setattr(settings, "llm_provider", "gemini", raising=False)
    monkeypatch.setattr(settings, "google_api_key", "", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        llm.preflight()


def test_preflight_passes_for_a_working_config():
    llm.preflight()          # the conftest default: openrouter with a key

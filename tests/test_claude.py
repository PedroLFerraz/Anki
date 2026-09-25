"""Claude through the Claude Code CLI, on a subscription, with Gemini behind it."""
import json
import subprocess
import sys

import pytest

from ankigen import llm
from ankigen.config import settings


@pytest.fixture
def claude(monkeypatch):
    """Claude writes and checks, Gemini takes over when it cannot."""
    for name, value in {
        "llm_provider": "claude", "claude_model": "claude-opus-5-5,claude-sonnet-5",
        "verify_provider": "claude", "verify_model": "claude-sonnet-5",
        "fallback_provider": "gemini", "gemini_model": "gemini-a,gemini-b",
        "gemini_fallback_models": "gemma-x", "fallback_verify_model": "gemini-lite",
        "verify_fallback_models": "gemma-v", "google_api_key": "test-google-key",
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/claude")


class FakeCLI:
    """Stands in for `claude -p`; answers with `result`, or fails with `error`."""

    def __init__(self, result='{"cards": []}', error=None):
        self.result, self.error, self.calls = result, error, []

    def __call__(self, args, **kw):
        self.calls.append({"args": args, **kw})
        if self.error:
            out = {"type": "result", "subtype": "success", "is_error": True, "result": self.error}
        else:
            out = {"type": "result", "subtype": "success", "is_error": False,
                   "result": self.result,
                   "usage": {"input_tokens": 3, "cache_creation_input_tokens": 100,
                             "output_tokens": 20}}
        return subprocess.CompletedProcess(args, 0, json.dumps(out), "")


@pytest.fixture
def gemini_answers(monkeypatch):
    """The fallback's models, answering without a network."""
    asked = []
    real = llm._call_one_model

    def call(prompt, cfg, model, max_retries):
        if cfg["provider"] == "gemini":
            asked.append(model)
            return llm.LLMResult({"from": "gemini"}, model)
        return real(prompt, cfg, model, max_retries)

    monkeypatch.setattr(llm, "_call_one_model", call)
    return asked


def test_the_writer_and_the_checker_are_different_claude_models(claude):
    writer, checker = settings.resolve_llm(), settings.resolve_verify()
    assert (writer["provider"], writer["models"]) == ("claude", ["claude-opus-5-5", "claude-sonnet-5"])
    assert (checker["provider"], checker["models"]) == ("claude", ["claude-sonnet-5"])


def test_each_gets_the_matching_gemini_chain_behind_it(claude):
    assert settings.resolve_llm()["fallback"]["models"] == ["gemini-a", "gemini-b", "gemma-x"]
    assert settings.resolve_verify()["fallback"]["models"] == ["gemini-lite", "gemma-v"]


def test_a_call_runs_the_cli_as_a_plain_json_endpoint(claude, monkeypatch):
    cli = FakeCLI('```json\n{"cards": [1]}\n```')
    monkeypatch.setattr(llm.subprocess, "run", cli)
    result = llm.call_json("write cards")
    assert result.data == {"cards": [1]} and result.model == "claude-opus-5-5"
    assert (result.prompt_tokens, result.completion_tokens) == (103, 20)
    [call] = cli.calls
    assert call["input"] == "write cards"
    args = call["args"]
    assert args[args.index("--tools") + 1] == "" and "--no-session-persistence" in args


def test_an_api_key_never_reaches_the_cli(claude, monkeypatch):
    """A stray key would make the CLI bill an API account instead of the plan."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-would-be-billed")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "also-billed")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "the-subscription")
    cli = FakeCLI()
    monkeypatch.setattr(llm.subprocess, "run", cli)
    llm.call_json("write cards")
    env = cli.calls[0]["env"]
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "the-subscription"


def test_a_usage_limit_hands_the_run_to_gemini(claude, monkeypatch, gemini_answers):
    cli = FakeCLI(error="Claude AI usage limit reached|1790000000")
    monkeypatch.setattr(llm.subprocess, "run", cli)
    assert llm.call_json("write cards").data == {"from": "gemini"}
    assert len(cli.calls) == 1                    # not retried, not tried on Sonnet
    assert llm.call_json("write more").data == {"from": "gemini"}
    assert len(cli.calls) == 1                    # the rest of the run skips Claude
    assert gemini_answers == ["gemini-a", "gemini-a"]


def test_the_checker_falls_back_to_the_gemini_checker(claude, monkeypatch, gemini_answers):
    monkeypatch.setattr(llm.subprocess, "run", FakeCLI(error="You've hit your limit"))
    llm.call_json("check cards", cfg=settings.resolve_verify())
    assert gemini_answers == ["gemini-lite"]


def test_without_a_fallback_the_limit_is_an_error(claude, monkeypatch):
    monkeypatch.setattr(settings, "fallback_provider", "")
    monkeypatch.setattr(llm.subprocess, "run", FakeCLI(error="Claude AI usage limit reached"))
    with pytest.raises(llm.ProviderUnavailable, match="usage limit"):
        llm.call_json("write cards")


def test_no_login_also_falls_back(claude, monkeypatch, gemini_answers):
    monkeypatch.setattr(llm.subprocess, "run", FakeCLI(error="Not logged in · Please run /login"))
    assert llm.call_json("write cards").data == {"from": "gemini"}


def test_no_cli_is_found_before_any_work_and_the_run_goes_on(claude, monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    monkeypatch.setattr(llm, "_get_gemini_client", lambda: object())
    llm.preflight()                               # no error: Gemini is there
    assert "claude" in llm._down


def test_no_cli_and_no_fallback_stops_the_run_early(claude, monkeypatch):
    monkeypatch.setattr(settings, "fallback_provider", "")
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Claude Code CLI is not installed"):
        llm.preflight()


def test_an_overloaded_claude_is_retried_on_the_next_claude_model(claude, monkeypatch):
    answers = iter([
        {"type": "result", "subtype": "success", "is_error": True, "result": "529 overloaded"},
        {"type": "result", "subtype": "success", "is_error": False, "result": '{"ok": 1}',
         "usage": {}},
    ])
    monkeypatch.setattr(llm.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(
        args, 0, json.dumps(next(answers)), ""))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    result = llm.call_json("write cards")
    assert result.model == "claude-sonnet-5" and "claude" not in llm._down


def test_pictures_are_checked_by_the_fallback(claude, monkeypatch):
    # Blocking google-genai shows the Gemini branch was taken, without
    # importing the real package into the rest of the test session.
    monkeypatch.setitem(sys.modules, "google.genai", None)
    cli = FakeCLI()
    monkeypatch.setattr(llm.subprocess, "run", cli)
    with pytest.raises(ImportError):
        llm.check_image(b"jpeg", "card", "query", cfg=settings.resolve_verify())
    assert cli.calls == []                        # never sent to the CLI

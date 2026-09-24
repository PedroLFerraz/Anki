"""End-to-end: the whole pipeline against a real (tiny) collection, fake LLM."""
import json

import pytest
import yaml
from conftest import RUN_DATE

from ankigen import pipeline

SNAPSHOT_TABLES = ("requests", "generated_cards", "verified_cards", "dedup_results")


@pytest.fixture
def ctx(cfg, profile, fake_llm, fake_embeddings):
    with open(cfg.ankigen_profile, "w", encoding="utf-8") as f:
        yaml.safe_dump(profile.model_dump(), f)
    c = pipeline.open_context(cfg=cfg)
    yield c
    c.wh.close()


def _state(wh):
    return {
        t: wh.query(f"SELECT * EXCLUDE (run_date) FROM {t} WHERE run_date = ? ORDER BY ALL", [RUN_DATE])
        for t in SNAPSHOT_TABLES
    }


def test_full_run(ctx, cfg, fake_llm):
    results = pipeline.run(ctx, RUN_DATE)
    assert list(results) == list(pipeline.STAGES)
    assert results["generate"]["cards"] == results["target"]["cards_requested"] == 6
    assert results["export"]["kept"] > 0

    report = json.loads((cfg.data_path / "out" / str(RUN_DATE) / "run_report.json").read_text())
    assert all(s["status"] == "success" for s in report["stages"])      # export no longer 'running'
    assert report["tokens"]["prompt"] > 0
    assert report["apkg"].endswith(f"ankigen_{RUN_DATE}.apkg")
    assert (cfg.data_path / "curated" / "generated_cards" / f"run_date={RUN_DATE}" / "part-0.parquet").exists()


def test_rerunning_a_date_is_idempotent(ctx):
    pipeline.run(ctx, RUN_DATE)
    before = _state(ctx.wh)
    pipeline.run(ctx, RUN_DATE)
    assert _state(ctx.wh) == before                    # same rows, not doubled


def test_downstream_stages_rerun_without_llm_calls(ctx, fake_llm):
    pipeline.run(ctx, RUN_DATE)
    calls = len(fake_llm.calls)
    before = _state(ctx.wh)
    pipeline.run(ctx, RUN_DATE, stages=["dedup", "export", "report"])
    assert len(fake_llm.calls) == calls
    assert _state(ctx.wh) == before


def test_dry_run_makes_no_llm_calls(ctx, fake_llm):
    results = pipeline.run(ctx, RUN_DATE, dry_run=True)
    assert list(results) == ["ingest", "target"] and fake_llm.calls == []


def test_verify_drops_are_reported(ctx, cfg, fake_llm):
    fake_llm.bad_words = ("Question 0",)
    pipeline.run(ctx, RUN_DATE)
    report = json.loads((cfg.data_path / "out" / str(RUN_DATE) / "run_report.json").read_text())
    assert report["outcomes"].get("dropped_verify", 0) > 0
    assert all(d["reason"].startswith("incorrect") for d in report["dropped"] if d["outcome"] == "dropped_verify")


def test_failed_stage_is_recorded(ctx, monkeypatch):
    pipeline.run(ctx, RUN_DATE, stages=["ingest", "target"])

    def boom(*a):
        raise RuntimeError("disk full")

    monkeypatch.setitem(pipeline.STAGES, "generate", boom)
    with pytest.raises(RuntimeError):
        pipeline.run(ctx, RUN_DATE, stages=["generate"])
    row = ctx.wh.query("SELECT status, detail FROM pipeline_runs WHERE stage = 'generate'")[0]
    assert row["status"] == "failed" and "disk full" in row["detail"]


def test_target_without_ingest_fails_clearly(ctx):
    with pytest.raises(RuntimeError, match="Run the ingest stage first"):
        pipeline.run(ctx, RUN_DATE, stages=["target"])


def test_unknown_stage(ctx):
    with pytest.raises(ValueError, match="Unknown stage"):
        pipeline.run(ctx, RUN_DATE, stages=["deploy"])


def test_planning_a_day_that_has_run_leaves_its_cards_alone(ctx, monkeypatch, fake_llm,
                                                           fake_embeddings):
    """A fresh plan replaced the day's requests, and the cards generated from
    the old ones dropped out of `report` and `push` without a word."""
    from typer.testing import CliRunner

    from ankigen import cli

    pipeline.run(ctx, RUN_DATE, stages=["ingest", "target", "generate"])
    before = ctx.wh.query("SELECT request_id FROM requests WHERE run_date = ?", [RUN_DATE])
    monkeypatch.setattr(pipeline, "open_context", lambda *a, **k: ctx)
    monkeypatch.setattr(ctx.wh, "close", lambda: None)

    shown = CliRunner().invoke(cli.app, ["plan", "-d", str(RUN_DATE), "--prompts", "0"])
    assert shown.exit_code == 0 and "already run" in shown.output
    refused = CliRunner().invoke(cli.app, ["run", "-d", str(RUN_DATE), "--dry-run"])
    assert refused.exit_code != 0
    after = ctx.wh.query("SELECT request_id FROM requests WHERE run_date = ?", [RUN_DATE])
    assert after == before

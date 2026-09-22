"""The daily pipeline: ingest -> target -> generate -> verify -> dedup -> export -> report.

Each stage is a function of (context, run_date) that reads its inputs from the
warehouse and replaces its own `run_date` partition. That contract is what lets
the same code run three ways without changes:

    ankigen run                      all stages in one process
    ankigen run --stage verify       one stage (debugging, or one Airflow task)
    Airflow / Kubernetes             one task or pod per stage
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from ankigen import dedup, export, generate, ingest, targeting, verify
from ankigen.config import Settings, settings
from ankigen.profile import Profile, load_profile
from ankigen.warehouse import Warehouse

logger = logging.getLogger(__name__)


@dataclass
class Context:
    settings: Settings
    profile: Profile
    wh: Warehouse

    @property
    def raw_dir(self) -> Path:
        return self.settings.data_path / "raw"

    @property
    def out_dir(self) -> Path:
        return self.settings.data_path / "out"


def open_context(profile_path: str | None = None, cfg: Settings | None = None) -> Context:
    cfg = cfg or settings
    profile = load_profile(profile_path or cfg.ankigen_profile)
    wh = Warehouse(cfg.data_path / "warehouse.duckdb")
    return Context(cfg, profile, wh)


# --------------------------------------------------------------- stages

def stage_ingest(ctx: Context, run_date: date) -> dict:
    return ingest.ingest(ctx.wh, run_date, ctx.settings.anki_collection_path, ctx.raw_dir)


def stage_target(ctx: Context, run_date: date) -> dict:
    notes = ingest.load_notes(ctx.wh, run_date)
    if not notes:
        raise RuntimeError(f"No ingested notes for {run_date}. Run the ingest stage first.")
    problems = ctx.profile.validate_against({n.deck for n in notes})
    if problems:
        raise ValueError("Profile does not match the collection:\n  " + "\n  ".join(problems))
    reqs = targeting.build_requests(ctx.profile, notes, run_date)
    targeting.save_requests(ctx.wh, run_date, reqs)
    return {
        "requests": len(reqs),
        "cards_requested": sum(r.n for r in reqs),
        "by_reason": {k: sum(1 for r in reqs if r.reason == k) for k in ("topic", "weak_card", "gap")},
    }


def stage_generate(ctx: Context, run_date: date) -> dict:
    return generate.run(ctx.wh, run_date, targeting.load_requests(ctx.wh, run_date))


def stage_verify(ctx: Context, run_date: date) -> dict:
    return verify.run(ctx.wh, run_date, ctx.profile)


def stage_dedup(ctx: Context, run_date: date) -> dict:
    return dedup.run(ctx.wh, run_date)


def stage_export(ctx: Context, run_date: date) -> dict:
    result = export.run(ctx.wh, run_date, ctx.out_dir)
    result["parquet_files"] = len(ctx.wh.export_parquet(run_date, ctx.settings.data_path / "curated"))
    return result


def stage_report(ctx: Context, run_date: date) -> dict:
    return export.write_report(ctx.wh, run_date, ctx.out_dir)


STAGES: dict[str, Callable[[Context, date], dict]] = {
    "ingest": stage_ingest,
    "target": stage_target,
    "generate": stage_generate,
    "verify": stage_verify,
    "dedup": stage_dedup,
    "export": stage_export,
    "report": stage_report,
}
# Everything up to (not including) the first LLM call.
DRY_RUN_STAGES = ("ingest", "target")


def run_stage(ctx: Context, name: str, run_date: date) -> dict:
    ctx.wh.start_stage(run_date, name)
    try:
        detail = STAGES[name](ctx, run_date)
    except Exception as e:
        ctx.wh.finish_stage(run_date, name, "failed", detail={"error": str(e)})
        raise
    rows = next((detail[k] for k in ("cards", "notes", "requests", "checked", "kept") if k in detail), 0)
    ctx.wh.finish_stage(run_date, name, "success", rows_out=rows if isinstance(rows, int) else 0, detail=detail)
    logger.info("stage %-8s ok  %s", name, detail)
    return detail


def run(ctx: Context, run_date: date, stages: list[str] | None = None, dry_run: bool = False) -> dict:
    names = list(DRY_RUN_STAGES) if dry_run else (stages or list(STAGES))
    unknown = [s for s in names if s not in STAGES]
    if unknown:
        raise ValueError(f"Unknown stage(s): {unknown}. Choose from {list(STAGES)}.")
    return {name: run_stage(ctx, name, run_date) for name in names}

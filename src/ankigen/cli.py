"""ankigen command line."""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from typing import Optional

import typer

from ankigen import pipeline
from ankigen.config import NATIVE_PROVIDERS, PROVIDERS, settings

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=__doc__,
    pretty_exceptions_show_locals=False,  # locals would print the whole profile and prompts
)


@app.callback()
def _setup(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")):
    # Deck names and card text are full of non-ASCII; don't let a cp1252
    # Windows console crash the run over an umlaut.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _date(value: Optional[str]) -> date:
    try:
        return date.fromisoformat(value) if value else date.today()
    except ValueError:
        raise typer.BadParameter(f"Expected YYYY-MM-DD, got {value!r}")


DateOpt = typer.Option(None, "--date", "-d", help="Run date, YYYY-MM-DD. Defaults to today.")
ProfileOpt = typer.Option(None, "--profile", "-p", help="Profile YAML. Defaults to ANKIGEN_PROFILE.")


@app.command()
def run(
    run_date: Optional[str] = DateOpt,
    profile: Optional[str] = ProfileOpt,
    stage: Optional[list[str]] = typer.Option(
        None, "--stage", "-s", help=f"Run only these stages: {', '.join(pipeline.STAGES)}."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Ingest and plan only; no LLM calls."),
):
    """Run the daily pipeline."""
    d = _date(run_date)
    ctx = pipeline.open_context(profile)
    try:
        results = pipeline.run(ctx, d, stages=stage, dry_run=dry_run)
    finally:
        ctx.wh.close()

    if dry_run:
        typer.echo(f"\nDry run for {d}: {results['target']['requests']} requests, "
                   f"{results['target']['cards_requested']} cards. See prompts with `ankigen plan`.")
        return
    if "export" in results:
        exp = results["export"]
        typer.echo(f"\n{exp['kept']} card(s) kept for {d}.")
        typer.echo(f"  package: {exp['apkg'] or '(none: nothing kept)'}")
    if "report" in results:
        typer.echo(f"  report:  {results['report']['report']}  (ankigen report -d {d})")


@app.command()
def plan(
    run_date: Optional[str] = DateOpt,
    profile: Optional[str] = ProfileOpt,
    prompts: int = typer.Option(1, "--prompts", help="How many full prompts to print (0 for none)."),
):
    """Show what today's run would generate, and the prompts it would send."""
    d = _date(run_date)
    ctx = pipeline.open_context(profile)
    try:
        pipeline.run(ctx, d, dry_run=True)
        reqs = ctx.wh.query("SELECT * FROM requests WHERE run_date = ? ORDER BY deck", [d])
    finally:
        ctx.wh.close()

    typer.echo(f"\nPlan for {d}  ({sum(r['n'] for r in reqs)} cards across {len(reqs)} requests)\n")
    for r in reqs:
        what = r["topic"] if r["reason"] != "weak_card" else (r["focus"] or "").split("\n")[0]
        typer.echo(f"  {r['n']:>2} x {r['card_type']:<8} {r['deck']:<32} [{r['reason']}] {what}")
    for r in reqs[:prompts]:
        typer.echo(f"\n{'=' * 72}\nPROMPT  {r['deck']} / {r['topic'] or r['reason']}\n{'=' * 72}")
        typer.echo(r["prompt"])


@app.command()
def decks(run_date: Optional[str] = DateOpt, profile: Optional[str] = ProfileOpt):
    """List the collection's decks — handy when writing a profile."""
    d = _date(run_date)
    ctx = pipeline.open_context(profile)
    try:
        if not ctx.wh.scalar("SELECT COUNT(*) FROM raw_notes WHERE run_date = ?", [d]):
            pipeline.run(ctx, d, stages=["ingest"])
        rows = ctx.wh.query(
            """SELECT deck, COUNT(*) AS notes,
                      COUNT(*) FILTER (WHERE lapses >= 2) AS weak,
                      ROUND(AVG(interval_days)) AS avg_interval
               FROM raw_notes WHERE run_date = ? GROUP BY deck ORDER BY deck""",
            [d],
        )
        targeted = {t.deck for t in ctx.profile.decks}
    finally:
        ctx.wh.close()
    typer.echo(f"\n{'deck':<48}{'notes':>7}{'weak':>6}{'avg ivl':>9}")
    for r in rows:
        mark = " *" if any(r["deck"] == t or r["deck"].startswith(t + "::") for t in targeted) else ""
        typer.echo(f"{r['deck']:<48}{r['notes']:>7}{r['weak']:>6}{int(r['avg_interval'] or 0):>8}d{mark}")
    typer.echo("\n* targeted by the current profile")


@app.command()
def validate(run_date: Optional[str] = DateOpt, profile: Optional[str] = ProfileOpt):
    """Check the profile against the collection."""
    d = _date(run_date)
    ctx = pipeline.open_context(profile)
    try:
        pipeline.run(ctx, d, stages=["ingest"])
        existing = {r["deck"] for r in ctx.wh.query(
            "SELECT DISTINCT deck FROM raw_notes WHERE run_date = ?", [d])}
    finally:
        ctx.wh.close()
    problems = ctx.profile.validate_against(existing)
    if problems:
        for p in problems:
            typer.echo(f"  x {p}")
        raise typer.Exit(1)
    typer.echo(f"Profile OK: {len(ctx.profile.decks)} deck target(s), "
               f"up to {ctx.profile.global_quota} cards/day.")


@app.command()
def report(run_date: Optional[str] = DateOpt):
    """Print a run's report."""
    d = _date(run_date)
    path = settings.data_path / "out" / str(d) / "run_report.json"
    if not path.exists():
        typer.echo(f"No report for {d} at {path}.")
        raise typer.Exit(1)
    rep = json.loads(path.read_text(encoding="utf-8"))
    typer.echo(f"\nRun {rep['run_date']}")
    for s in rep["stages"]:
        typer.echo(f"  {s['stage']:<9} {s['status']:<8} {s['rows_out'] or 0:>5} rows  {s['seconds'] or 0:>6.1f}s")
    typer.echo(f"\nOutcomes: {rep['outcomes']}")
    typer.echo(f"Tokens:   {rep['tokens']}")
    for r in rep["by_deck"]:
        typer.echo(f"  {r['deck']:<40} kept {r['kept']}/{r['generated']}")
    if rep["dropped"]:
        typer.echo("\nDropped:")
        for r in rep["dropped"]:
            typer.echo(f"  [{r['outcome'].removeprefix('dropped_')}] {r['front'][:70]}\n      -> {r['reason']}")
    typer.echo(f"\nPackage: {rep['apkg'] or '(none)'}")


@app.command()
def providers():
    """Show LLM presets and test the configured provider."""
    from ankigen.llm import check_connection

    typer.echo("\nPresets (LLM_PROVIDER):")
    for name, p in sorted(PROVIDERS.items()):
        emb = "embeddings" if p["embedding_model"] else "no embeddings"
        key = "needs key" if p["needs_key"] else "no key"
        typer.echo(f"  {name:<11} {key}, {emb}. {p['notes']}")
    for name in sorted(NATIVE_PROVIDERS):
        typer.echo(f"  {name:<11} needs GOOGLE_API_KEY, embeddings.")

    llm_cfg, emb_cfg = settings.resolve_llm(), settings.resolve_embedding()
    typer.echo(f"\nGeneration: {llm_cfg['provider']} / {llm_cfg['model']}")
    typer.echo(f"Embeddings: {emb_cfg['provider'] or 'none (fuzzy dedup only)'} / {emb_cfg['model'] or '-'}")
    err = check_connection()
    typer.echo(f"Connection: {'OK' if not err else 'FAILED - ' + err}")
    if err:
        raise typer.Exit(1)


def main():
    """Entry point: expected failures print one line, not a traceback."""
    from pydantic import ValidationError

    from ankigen.ingest import CollectionLocked

    try:
        app()
    except ValidationError as e:
        typer.echo(f"Profile is invalid:\n{e}", err=True)
        sys.exit(2)
    except (FileNotFoundError, CollectionLocked, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

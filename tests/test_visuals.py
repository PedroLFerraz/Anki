"""Pictures drawn from the card itself: tables and Graphviz diagrams."""
import json

import pytest
from conftest import RUN_DATE

from ankigen import export, generate, pipeline, verify, visuals

needs_dot = pytest.mark.skipif(not visuals.have_graphviz(), reason="Graphviz is not installed")

PROBES = {"dot": 'digraph { rankdir=LR; start [label="Startup probe"]; run [label="Running"]; '
                 'start -> run [label="passes"]; run -> live [label="then"]; }'}
CLASSES = {"table": [["", "Standard-IA", "Glacier Deep Archive"],
                     ["Minimum storage", "30 days", "180 days"],
                     ["Retrieval", "milliseconds", "up to 12 hours"]]}


# ---------------------------------------------------------------- what the model sends

def test_most_cards_have_no_visual():
    for nothing in (None, "", {}, [], {"table": []}, {"table": [["only a header"]]},
                    {"dot": "no arrows here"}, "not json", {"chart": [1, 2]}):
        assert visuals.parse(nothing) is None


def test_a_table_is_trimmed_to_something_a_card_can_hold():
    rows = [[f"r{r}c{c}" for c in range(9)] for r in range(12)]
    table = visuals.parse({"table": rows})["table"]
    assert len(table) == visuals.MAX_ROWS and all(len(r) == visuals.MAX_COLS for r in table)


def test_ragged_rows_are_padded_and_long_cells_cut():
    table = visuals.parse({"table": [["a", "b", "c"], ["x"], ["y", "z" * 200]]})["table"]
    assert table[1] == ["x", "", ""]
    assert len(table[2][1]) == visuals.MAX_CELL and table[2][1].endswith("…")


def test_the_visual_survives_the_trip_through_the_warehouse():
    assert visuals.parse(json.dumps(CLASSES)) == CLASSES


def test_generation_reads_the_visual_off_each_card():
    [card] = generate.parse_cards("detailed", {"cards": [{
        "question": "Liveness vs readiness?", "summary": "Restart vs stop traffic.",
        "explanation": "e", "visual": CLASSES}]})
    assert card.visual == CLASSES


# ---------------------------------------------------------------- for the checker

def test_the_checker_reads_a_table_as_text():
    assert visuals.describe(CLASSES).startswith("table:  | Standard-IA | Glacier Deep Archive / ")


def test_the_checker_reads_a_diagram_as_labelled_edges():
    assert visuals.describe(PROBES) == \
        "diagram: Startup probe -> Running (passes); Running -> live (then)"


def test_quoted_names_chains_and_semicolons_in_labels():
    described = visuals.describe({"dot": 'digraph {\n "Worker" -> "Triggerer" -> "Worker" '
                                         '[label="defer; resume"]\n}'})
    assert described == ("diagram: Worker -> Triggerer (defer; resume); "
                         "Triggerer -> Worker (defer; resume)")


def test_the_checker_is_shown_the_visual_and_its_verdict_is_kept_apart():
    prompt = verify.build_prompt("Data Platform::AWS", "working", [
        {"front": "Q?", "back": "A.", "visual_json": json.dumps(CLASSES)},
        {"front": "Q2?", "back": "A2.", "visual_json": None}])
    assert "   Visual (table:" in prompt and prompt.count("   Visual (") == 1
    verdicts = verify.visual_verdicts(
        [{"index": 1, "visual_ok": False}, {"index": 2, "visual_ok": True}],
        [{"visual_json": "{}"}, {"visual_json": None}])
    assert verdicts == [False, None]          # no visual, no verdict to keep


# ---------------------------------------------------------------- drawing

def test_a_table_is_escaped_and_shows_code_as_code():
    html = visuals.table_html([["<b>x</b>", "`kubectl get pods`"], ["1", "2"]])
    assert "&lt;b&gt;" in html and "<code>kubectl get pods</code>" in html
    assert html.count("<th") == 2 and html.count("<td") == 2


@needs_dot
def test_a_diagram_follows_the_card_s_colours():
    svg = visuals.dot_svg(PROBES["dot"])
    assert svg.startswith("<svg") and 'fill="currentColor"' in svg
    assert visuals._INK not in svg and "<title>" not in svg and ' id="' not in svg


@needs_dot
def test_a_wide_diagram_is_turned_upright_for_a_phone():
    chain = "digraph { rankdir=LR; " + " -> ".join(f"step{i}" for i in range(6)) + " }"
    width, height = visuals._size(visuals._render(chain))
    assert width / height > visuals.MAX_ASPECT          # as the model asked for it
    upright = visuals.dot_svg(chain)
    w, h = visuals._size(upright)
    assert h > w


@needs_dot
def test_a_bare_list_of_edges_is_still_a_diagram():
    assert visuals.dot_svg('a -> b [label="x"]').startswith("<svg")


@needs_dot
def test_a_diagram_that_asks_for_files_is_not_drawn():
    with pytest.raises(visuals.NotDrawable):
        visuals.dot_svg('digraph { a [image="/etc/passwd"]; a -> b }')
    with pytest.raises(visuals.NotDrawable):
        visuals.dot_svg('digraph { a [URL="https://x"]; a -> b }')


@needs_dot
def test_too_many_boxes_is_not_a_flashcard_picture():
    with pytest.raises(visuals.NotDrawable, match="boxes"):
        visuals.dot_svg("digraph { " + "; ".join(f"n{i} -> n{i + 1}" for i in range(20)) + " }")


@needs_dot
def test_broken_dot_is_not_drawable_rather_than_a_crash():
    with pytest.raises(visuals.NotDrawable):
        visuals.dot_svg("digraph { a -> [label= }")


# ---------------------------------------------------------------- the stage

def _kept(wh, card_uid, visual, visual_ok=True, image_query="", card_type="detailed"):
    wh.replace_partition("requests", RUN_DATE,
                         ("run_date", "request_id", "deck", "topic", "card_type", "n", "reason",
                          "focus", "prompt"),
                         [(RUN_DATE, "r1", "Data Platform::AWS", "t", card_type, 1, "topic",
                           None, "p")])
    fields = {"Question": "Q?", "Summary": "S", "Explanation": "E", "Image": "", "Reference": ""}
    wh.replace_partition("generated_cards", RUN_DATE, generate.WRITTEN_COLUMNS, [
        (RUN_DATE, card_uid, "r1", "Data Platform::AWS", card_type, "Q?", "S",
         json.dumps(fields), image_query, "m", 0, 0, json.dumps(visual) if visual else None)])
    wh.replace_partition("verified_cards", RUN_DATE,
                         ("run_date", "card_uid", "passed", "score", "reason", "visual_ok"),
                         [(RUN_DATE, card_uid, True, 0.9, "", visual_ok)])
    wh.replace_partition("dedup_results", RUN_DATE,
                         ("run_date", "card_uid", "is_dup", "reason", "similarity"),
                         [(RUN_DATE, card_uid, False, None, None)])


def test_a_drawn_card_is_not_searched_for(wh, monkeypatch, cfg, profile):
    _kept(wh, "u1", CLASSES, image_query="s3 storage classes table")
    searched = []
    monkeypatch.setattr(pipeline.images, "fetch_many",
                        lambda jobs, media_dir, **k: (searched.extend(jobs), [])[1])
    result = pipeline.stage_images(pipeline.Context(cfg, profile, wh), RUN_DATE)
    assert result["drawn"] == 1 and searched == []
    [row] = wh.query("SELECT visual_kind, visual_html FROM card_outcomes WHERE card_uid = 'u1'")
    assert row["visual_kind"] == "table" and "ankigen-visual" in row["visual_html"]


def test_a_visual_the_checker_rejected_is_not_drawn(wh, monkeypatch, cfg, profile):
    _kept(wh, "u1", CLASSES, visual_ok=False)
    monkeypatch.setattr(pipeline.images, "fetch_many", lambda jobs, media_dir, **k: [])
    result = pipeline.stage_images(pipeline.Context(cfg, profile, wh), RUN_DATE)
    assert result["drawn"] == 0
    [row] = wh.query("SELECT visual_html FROM card_outcomes WHERE card_uid = 'u1'")
    assert row["visual_html"] is None


def test_an_undrawable_visual_falls_back_to_search(wh, monkeypatch, cfg, profile):
    _kept(wh, "u1", {"dot": "digraph { a [image=\"x\"]; a -> b }"}, image_query="a b diagram")
    searched = []
    monkeypatch.setattr(pipeline.images, "fetch_many",
                        lambda jobs, media_dir, **k: (searched.extend(jobs), [])[1])
    result = pipeline.stage_images(pipeline.Context(cfg, profile, wh), RUN_DATE)
    assert result["drawn"] == 0 and len(result["not_drawn"]) == 1
    assert [j[0] for j in searched] == ["u1"]


def test_a_drawn_visual_goes_in_the_picture_field(wh, tmp_path, monkeypatch, cfg, profile):
    _kept(wh, "u1", CLASSES)
    monkeypatch.setattr(pipeline.images, "fetch_many", lambda jobs, media_dir, **k: [])
    pipeline.stage_images(pipeline.Context(cfg, profile, wh), RUN_DATE)
    [card] = wh.query("SELECT * FROM card_outcomes WHERE card_uid = 'u1'")
    values = export.with_picture("detailed", json.loads(card["fields_json"]), card["visual_html"])
    assert values["Image"].startswith('<div class="ankigen-visual"')
    cloze = export.with_picture("cloze", {"Text": "t", "Extra": "hint"}, card["visual_html"])
    assert cloze["Extra"].startswith("hint<div")          # a block needs no <br>

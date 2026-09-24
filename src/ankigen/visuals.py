"""Draw a card's picture from the card itself: a table, or a diagram.

The model that writes a card knows exactly what it means, so when the answer
is a comparison or a flow it can describe the picture directly — rows and
columns, or boxes and arrows in Graphviz — in the same request that writes
the card. That costs nothing extra on a metered free tier, needs no search
engine, and cannot come back as somebody's holiday photo, which is what
searching the web for "S3 storage classes" once did.

Both kinds render to HTML that lives inside the note: a table as a table, a
diagram as inline SVG. No media file is involved, so nothing has to be synced
beyond the note, and both follow the card's own colours — text and lines are
`currentColor`, so the same picture reads on a dark card and a light one.
"""
from __future__ import annotations

import html
import json
import logging
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

MAX_ROWS = 6
MAX_COLS = 4
MAX_CELL = 60
MAX_NODES = 12
MAX_SVG_BYTES = 40_000
# Wider than this and a diagram shrinks to unreadable on a phone held upright,
# so it is laid out top to bottom instead.
MAX_ASPECT = 2.0
DOT_TIMEOUT = 15

# Stands in for "the card's text colour" while Graphviz draws, and becomes
# currentColor afterwards. Graphviz insists on a real colour.
_INK = "#010101"
_LINE = "#7f8fa6"          # a grey that reads on both dark and light cards
_STYLE = (
    f'graph [bgcolor="transparent", pad="0.15", nodesep="0.3", ranksep="0.45", '
    f'fontname="Helvetica"]; '
    f'node [shape=box, style="rounded", fontname="Helvetica", fontsize=13, '
    f'color="{_LINE}", fontcolor="{_INK}", penwidth=1.3, margin="0.15,0.06"]; '
    f'edge [fontname="Helvetica", fontsize=11, color="{_LINE}", fontcolor="{_INK}", '
    f'penwidth=1.2, arrowsize=0.8]; '
)
# Attributes that make Graphviz read files or emit links. The model has no
# reason to use them, and a diagram that does is not drawn.
_FORBIDDEN = re.compile(r"\b(image|imagepath|shapefile|fontpath|href|url|stylesheet)\s*=",
                        re.IGNORECASE)


class NotDrawable(ValueError):
    """The model's description could not be turned into a picture."""


def parse(raw) -> dict | None:
    """The card's `visual`, normalised to {"table": rows} or {"dot": source}.

    Anything else — null, an empty object, a shape the model invented — is
    no visual, which is the right answer for most cards anyway.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    rows = raw.get("table")
    if isinstance(rows, list) and rows:
        rows = [[_cell(c) for c in row][:MAX_COLS] for row in rows[:MAX_ROWS]
                if isinstance(row, list) and row]
        width = max((len(r) for r in rows), default=0)
        if len(rows) >= 2 and width >= 2:
            return {"table": [r + [""] * (width - len(r)) for r in rows]}
        return None
    dot = raw.get("dot")
    if isinstance(dot, str) and ("->" in dot or "--" in dot):
        return {"dot": dot.strip()}
    return None


def _cell(value) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= MAX_CELL else text[:MAX_CELL - 1] + "…"


def describe(visual: dict | None) -> str:
    """The visual in words, for the fact-checker, who cannot see pictures."""
    if not visual:
        return ""
    if "table" in visual:
        return "table: " + " / ".join(" | ".join(row) for row in visual["table"])
    labels, edges = {}, []
    for statement in _statements(visual["dot"]):
        label = re.search(r'label\s*=\s*"([^"]*)"', statement)
        head = statement.split("[", 1)[0]
        chain = [n.strip().strip('"') for n in re.split(r"-[->]", head)]
        if len(chain) > 1:
            # "a -> b -> c" is two edges, and the label belongs to each.
            edges.extend((a, b, label.group(1) if label else "")
                         for a, b in zip(chain, chain[1:]))
        elif label and chain[0] and chain[0] not in ("graph", "node", "edge"):
            labels[chain[0]] = label.group(1)
    if not edges:
        return "diagram: " + visual["dot"][:300]
    return "diagram: " + "; ".join(
        f"{labels.get(a, a)} -> {labels.get(b, b)}" + (f" ({text})" if text else "")
        for a, b, text in edges)


def _statements(dot: str) -> list[str]:
    """Split DOT into statements, minding separators inside quoted labels."""
    body = dot[dot.find("{") + 1:dot.rfind("}")] if "{" in dot else dot
    out, current, quoted = [], [], False
    for ch in body:
        if ch == '"':
            quoted = not quoted
        if ch in ";\n" and not quoted:
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
    out.append("".join(current))
    return [s.strip() for s in out if s.strip()]


# ----------------------------------------------------------------- tables

def table_html(rows: list[list[str]]) -> str:
    cell = "border:1px solid rgba(127,143,166,.6);padding:5px 9px;vertical-align:top"
    out = []
    for i, row in enumerate(rows):
        tag = "th" if i == 0 else "td"
        cells = "".join(f'<{tag} style="{cell}">{_inline(c)}</{tag}>' for c in row)
        out.append(f"<tr>{cells}</tr>")
    return ('<table style="border-collapse:collapse;margin:0 auto;font-size:15px;'
            f'line-height:1.35;text-align:left">{"".join(out)}</table>')


def _inline(text: str) -> str:
    """Escaped, with `backticks` shown as code, as they are elsewhere on cards."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text))


# ----------------------------------------------------------------- diagrams

def have_graphviz() -> bool:
    return shutil.which("dot") is not None


def dot_svg(source: str) -> str:
    """Inline SVG for a Graphviz description, styled to sit on a card."""
    if _FORBIDDEN.search(source):
        raise NotDrawable("the diagram asks Graphviz for files or links")
    source = source.strip()
    if not re.match(r"(strict\s+)?(di)?graph\b", source, re.IGNORECASE):
        source = "digraph { " + source + " }"
    svg = _render(source)
    width, height = _size(svg)
    if height and width / height > MAX_ASPECT:
        # Drop the model's direction rather than fight it: a later rankdir
        # statement would win over one we put first.
        upright = re.sub(r'\brankdir\s*=\s*"?\w+"?\s*;?', "", source)
        svg = _render(upright, extra='rankdir="TB"; ')
        width, height = _size(svg)
    if svg.count('class="node"') > MAX_NODES:
        raise NotDrawable(f"more than {MAX_NODES} boxes is not a flashcard picture")
    svg = _tidy(svg, width)
    if len(svg.encode()) > MAX_SVG_BYTES:
        raise NotDrawable("the drawing is too large to carry inside a note")
    return svg


def _render(source: str, extra: str = "") -> str:
    styled = source.replace("{", "{ " + _STYLE + extra, 1)
    try:
        done = subprocess.run(["dot", "-Tsvg"], input=styled.encode(), capture_output=True,
                              timeout=DOT_TIMEOUT)
    except FileNotFoundError as e:
        raise NotDrawable("Graphviz is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise NotDrawable("Graphviz took too long") from e
    if done.returncode != 0 or b"<svg" not in done.stdout:
        raise NotDrawable(done.stderr.decode(errors="replace").strip()[:200] or "Graphviz failed")
    return done.stdout.decode()


def _size(svg: str) -> tuple[float, float]:
    box = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', svg)
    return (float(box.group(1)), float(box.group(2))) if box else (0.0, 0.0)


def _tidy(svg: str, width_pt: float) -> str:
    """Graphviz's SVG, cut down to what a card needs and made to scale."""
    svg = svg[svg.index("<svg"):]
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.DOTALL)
    svg = re.sub(r"<title>.*?</title>", "", svg, flags=re.DOTALL)
    # Two diagrams on one screen would share ids like "node1".
    svg = re.sub(r'\s(id|class)="[^"]*"', "", svg)
    svg = svg.replace(f'fill="{_INK}"', 'fill="currentColor"')
    svg = svg.replace(f'stroke="{_INK}"', 'stroke="currentColor"')
    # Scale to the card, but never beyond its natural size (pt -> px).
    svg = re.sub(r'<svg width="[^"]*" height="[^"]*"',
                 f'<svg width="100%" style="max-width:{round(width_pt * 4 / 3)}px;height:auto"',
                 svg, count=1)
    return re.sub(r">\s+<", "><", svg).strip()


# ----------------------------------------------------------------- both

def to_html(visual: dict) -> str:
    """The note's picture, ready to go in a field. Raises NotDrawable."""
    if "table" in visual:
        inner = table_html(visual["table"])
        style = "margin:12px auto;overflow-x:auto"
    else:
        inner = dot_svg(visual["dot"])
        style = "margin:12px auto;text-align:center"
    return f'<div class="ankigen-visual" style="{style}">{inner}</div>'

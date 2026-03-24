from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def smart_parse(raw_text: str, fields: list[str]) -> list[dict]:
    """Parses the pipe-separated text from Agent 2 into a list of dicts."""
    parsed_cards = []
    clean_text = raw_text.replace("```markdown", "").replace("```text", "").replace("```", "").strip()
    lines = clean_text.split("\n")
    expected_count = len(fields)

    for line in lines:
        line = re.sub(r"^[\d\)\.\-\*]+\s*", "", line).strip()
        if not line or "|" not in line:
            continue

        parts = [p.strip() for p in line.split("|")]

        # Handle trailing empty part from trailing pipe
        if len(parts) == expected_count + 1 and parts[-1] == "":
            parts.pop()

        # Pad with empty strings if we're short (AI sometimes drops trailing empty fields)
        while len(parts) < expected_count:
            parts.append("")

        # Truncate if we have too many (AI sometimes adds extra)
        if len(parts) > expected_count:
            parts = parts[:expected_count]

        if len(parts) == expected_count:
            row = {fields[i]: parts[i] for i in range(expected_count)}
            parsed_cards.append(row)
        else:
            logger.warning("Skipping line with %d fields (expected %d): %s", len(parts), expected_count, line[:100])

    return parsed_cards

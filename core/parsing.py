import re


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

        if len(parts) == expected_count + 1 and parts[-1] == "":
            parts.pop()
        if len(parts) == expected_count - 1:
            parts.append("")

        if len(parts) == expected_count:
            row = {fields[i]: parts[i] for i in range(expected_count)}
            parsed_cards.append(row)

    return parsed_cards

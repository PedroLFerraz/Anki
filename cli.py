#!/usr/bin/env python3
"""
Anki flashcard generator — generates Q&A cards using a local LLM (Ollama).

Usage:
    python cli.py generate "Data Science" -n 5
    python cli.py generate "Machine Learning" -n 3 --type detailed
    python cli.py list
    python cli.py export --deck-name "Data Science"
    python cli.py clear
"""

import argparse
import logging
import sys

import storage.database  # triggers init_db()

from core import agents, apkg_import, embeddings, images
from export.genanki_export import export_cards
from storage import repository

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# In-memory session context — cards generated in this CLI run
_session_cards: list[dict] = []


def cmd_generate(args):
    card_type = args.type
    # Only imported context counts as "existing" — each session starts fresh
    ctx_cards, ctx_embeddings = repository.get_context_cards_with_embeddings()
    # Session cards are tracked in-memory (added to _session_cards below)
    all_existing = list(ctx_cards) + list(_session_cards)
    existing_text = "\n".join(
        f"Q: {c['Question']}" for c in all_existing if c.get("Question")
    )
    if not existing_text:
        existing_text = "(none)"

    ctx_label = f" ({len(ctx_cards)} from imported deck)" if ctx_cards else ""
    print(f"\nContext: {len(all_existing)} cards{ctx_label}")
    print(f"Generating {args.count} {card_type} cards about '{args.topic}'...\n")

    cards = agents.generate_cards(args.topic, args.count, existing_text, card_type=card_type)

    if not cards:
        print("Generation failed — no cards returned.")
        sys.exit(1)

    # For detailed/visual cards: download images
    if card_type in ("detailed", "visual"):
        import time
        print(f"Searching for images...")
        for i, card in enumerate(cards):
            query = card.get("image_query", "")
            if query:
                if i > 0:
                    time.sleep(3)  # avoid DuckDuckGo rate limits
                filename = images.search_and_download(query)
                card["image_filename"] = filename
                status = "found" if filename else "not found"
                print(f"  [{status}] {query}")

        # Visual cards without images are useless — filter them out
        if card_type == "visual":
            before = len(cards)
            cards = [c for c in cards if c.get("image_filename")]
            skipped = before - len(cards)
            if skipped:
                print(f"  Skipped {skipped} card(s) with no image found.")

    # Dedup against context + session cards
    dedup_cards = list(ctx_cards) + list(_session_cards)
    dedup_embeddings = list(ctx_embeddings) + [None] * len(_session_cards)
    use_embeddings = not args.no_embeddings
    saved = []
    for card in cards:
        emb = None
        if use_embeddings:
            emb = embeddings.get_embedding(f"{card['question']} {card['answer']}")

        is_dup, reason = embeddings.is_duplicate(
            card["question"], dedup_cards, dedup_embeddings, new_embedding=emb
        )

        status = "DUPLICATE" if is_dup else "GENERATED"

        # Build extra_fields for detailed/visual cards
        extra_fields = None
        if card_type == "detailed":
            extra_fields = {
                "summary": card.get("summary", ""),
                "explanation": card.get("explanation", ""),
                "image_query": card.get("image_query", ""),
                "image_filename": card.get("image_filename"),
            }
        elif card_type == "visual":
            extra_fields = {
                "title": card.get("title", ""),
                "explanation": card.get("explanation", ""),
                "image_query": card.get("image_query", ""),
                "image_filename": card.get("image_filename"),
            }

        card_id = repository.save_card(
            question=card["question"], answer=card["answer"],
            topic=args.topic, embedding=emb, status=status,
            card_type=card_type, extra_fields=extra_fields,
        )
        saved.append({"id": card_id, "is_dup": is_dup, "reason": reason, **card})

        if not is_dup:
            dedup_cards.append({"Question": card["question"], "Answer": card["answer"]})
            dedup_embeddings.append(emb)
            _session_cards.append({"Question": card["question"], "Answer": card["answer"]})

    # Display
    print(f"\n{'='*60}")
    print(f"Generated {len(saved)} cards:\n")

    for idx, card in enumerate(saved):
        dup_tag = " [DUPLICATE]" if card["is_dup"] else ""
        img_tag = ""
        if card_type in ("detailed", "visual") and card.get("image_filename"):
            img_tag = " [IMG]"
        print(f"--- Card {idx + 1}{dup_tag}{img_tag} ---")
        if card["is_dup"]:
            print(f"  Reason: {card['reason']}")
        if card_type == "visual":
            print(f"  Title: {card.get('title', '')}")
            print(f"  Explanation: {card.get('explanation', '')[:120]}...")
        elif card_type == "detailed":
            print(f"  Q: {card['question']}")
            print(f"  Summary: {card.get('summary', '')}")
            print(f"  Explanation: {card.get('explanation', '')[:120]}...")
        else:
            print(f"  Q: {card['question']}")
            print(f"  A: {card['answer']}")
        print()

    non_dups = [c for c in saved if not c["is_dup"]]
    if not non_dups:
        print("All cards are duplicates.")
        return

    print(f"{len(non_dups)} new cards.")
    answer = input("Accept all? [Y/n/pick] ").strip().lower()

    accepted_ids = []
    if answer in ("", "y", "yes"):
        accepted_ids = [c["id"] for c in non_dups]
    elif answer == "pick":
        for c in non_dups:
            choice = input(f"  Accept: {c['question'][:60]}...? [Y/n] ").strip().lower()
            if choice in ("", "y", "yes"):
                accepted_ids.append(c["id"])
    else:
        print("No cards accepted.")
        return

    for card_id in accepted_ids:
        repository.update_card_status(card_id, "ACCEPTED")

    print(f"\nAccepted {len(accepted_ids)} cards.")

    if accepted_ids:
        do_export = input("Export to .apkg now? [Y/n] ").strip().lower()
        if do_export in ("", "y", "yes"):
            _do_export(args.deck_name)


def _do_export(deck_name: str):
    cards = repository.get_cards(status="ACCEPTED")
    if not cards:
        print("No accepted cards to export.")
        return

    path = export_cards(cards, deck_name=deck_name)
    for c in cards:
        repository.update_card_status(c["id"], "EXPORTED")
    print(f"\nExported {len(cards)} cards to: {path.name}")
    print("Import this file into Anki: File > Import")


def cmd_list(args):
    cards = repository.get_cards(topic=args.topic, status=args.status)
    if not cards:
        print("No cards found.")
        return

    # Show context count separately
    ctx_count = sum(1 for c in cards if c.get("status") == "CONTEXT")
    non_ctx = [c for c in cards if c.get("status") != "CONTEXT"]

    if ctx_count and not args.status:
        print(f"\n({ctx_count} context cards loaded — use 'list --status CONTEXT' to see them)")

    display = cards if args.status else non_ctx
    if not display:
        print("No cards found.")
        return

    print(f"\n{len(display)} cards:\n")
    for card in display:
        ct = card.get("card_type", "basic")
        extra = card.get("extra_fields") or {}
        has_img = "[IMG] " if extra.get("image_filename") else ""
        print(f"  [{card['id']}] ({card['status']}) [{ct}] {has_img}{card['topic'] or '-'}")
        if ct == "visual":
            print(f"    Title: {extra.get('title', card['question'])[:80]}")
            print(f"    Explanation: {extra.get('explanation', card['answer'])[:80]}")
        elif ct == "detailed" and extra.get("summary"):
            print(f"    Q: {card['question']}")
            print(f"    S: {extra['summary'][:80]}")
        else:
            print(f"    Q: {card['question']}")
            print(f"    A: {card['answer'][:80]}")
        print()


def cmd_export(args):
    _do_export(args.deck_name)


def cmd_clear(args):
    statuses = args.status.split(",") if args.status else ["GENERATED", "REJECTED", "DUPLICATE"]
    total = 0
    for status in statuses:
        count = repository.delete_cards_by_status(status.strip(), topic=args.topic)
        if count:
            print(f"Deleted {count} {status} cards.")
            total += count
    if total == 0:
        print("No cards to clear.")
    else:
        print(f"Total: {total} cards cleared.")


def cmd_import_context(args):
    if args.clear_existing:
        count = repository.delete_context_cards()
        if count:
            print(f"Cleared {count} existing context cards.")

    ctx_count = repository.get_context_count()
    if ctx_count > 0 and not args.clear_existing:
        print(f"You already have {ctx_count} context cards loaded.")
        answer = input("Clear them before importing? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            repository.delete_context_cards()
            print("Cleared.")

    print(f"Importing {args.file}...")
    try:
        deck_name, cards = apkg_import.import_apkg(args.file)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not cards:
        print("No cards found in the deck.")
        return

    count = repository.save_context_cards(cards, source=deck_name)
    print(f"\nImported {count} cards as context from deck '{deck_name}'.")
    print("These cards will be used for dedup when generating new cards.")
    print("Use 'clear-context' to remove them.")


def cmd_clear_context(args):
    count = repository.delete_context_cards()
    if count:
        print(f"Cleared {count} context cards.")
    else:
        print("No context cards to clear.")


def main():
    parser = argparse.ArgumentParser(description="Anki Flashcard Generator")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # generate
    gen = subparsers.add_parser("generate", aliases=["gen"], help="Generate flashcards for a topic")
    gen.add_argument("topic", help="Topic to generate cards about")
    gen.add_argument("--count", "-n", type=int, default=5, help="Number of cards (default: 5)")
    gen.add_argument("--type", choices=["basic", "detailed", "visual"], default="basic",
                     help="Card type: basic (Q&A), detailed (summary + explanation + image), or visual (image front, explanation back)")
    gen.add_argument("--deck-name", "-d", default="Flashcards", help="Deck name in Anki")
    gen.add_argument("--no-embeddings", action="store_true", help="Skip embedding-based dedup")

    # list
    ls = subparsers.add_parser("list", aliases=["ls"], help="List cards")
    ls.add_argument("--topic", "-t", help="Filter by topic")
    ls.add_argument("--status", "-s", help="Filter by status")

    # export
    exp = subparsers.add_parser("export", help="Export accepted cards to .apkg")
    exp.add_argument("--deck-name", "-d", default="Flashcards", help="Deck name in Anki")

    # clear
    clr = subparsers.add_parser("clear", help="Clear generated/rejected/duplicate cards")
    clr.add_argument("--topic", "-t", help="Only clear cards for this topic")
    clr.add_argument("--status", "-s", default="GENERATED,REJECTED,DUPLICATE",
                     help="Statuses to clear (comma-separated)")

    # import-context
    imp = subparsers.add_parser("import-context", aliases=["import"],
                                help="Import .apkg deck as context for dedup")
    imp.add_argument("file", help="Path to .apkg file")
    imp.add_argument("--clear-existing", action="store_true",
                     help="Clear existing context cards before importing")

    # clear-context
    subparsers.add_parser("clear-context", help="Remove all imported context cards")

    args = parser.parse_args()

    if args.command in ("generate", "gen"):
        cmd_generate(args)
    elif args.command in ("list", "ls"):
        cmd_list(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "clear":
        cmd_clear(args)
    elif args.command in ("import-context", "import"):
        cmd_import_context(args)
    elif args.command == "clear-context":
        cmd_clear_context(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

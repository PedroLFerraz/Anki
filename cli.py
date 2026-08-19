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


def _edit_card(card: dict, card_type: str):
    """Inline edit a card's fields. Empty input keeps original value."""
    print(f"\n  Editing card {card['id']} (press Enter to keep current value):")

    new_q = input(f"  Question [{(card.get('question') or '')[:60]}]: ").strip()
    if new_q:
        card["question"] = new_q

    if card_type == "visual":
        new_title = input(f"  Title [{(card.get('title') or '')[:60]}]: ").strip()
        if new_title:
            card["title"] = new_title
            card["question"] = new_title  # title is stored as question
        new_exp = input(f"  Explanation [{(card.get('explanation') or '')[:60]}]: ").strip()
        if new_exp:
            card["explanation"] = new_exp
            card["answer"] = new_exp
    elif card_type == "cloze":
        cloze_text = card.get("text") or card.get("answer") or ""
        new_text = input(f"  Cloze text [{cloze_text[:60]}]: ").strip()
        if new_text:
            card["text"] = new_text
            card["answer"] = new_text
        new_extra = input(f"  Hint [{(card.get('extra') or '')[:60]}]: ").strip()
        if new_extra:
            card["extra"] = new_extra
    elif card_type == "detailed":
        new_sum = input(f"  Summary [{(card.get('summary') or '')[:60]}]: ").strip()
        if new_sum:
            card["summary"] = new_sum
            card["answer"] = new_sum
        new_exp = input(f"  Explanation [{(card.get('explanation') or '')[:60]}]: ").strip()
        if new_exp:
            card["explanation"] = new_exp
    else:
        new_a = input(f"  Answer [{(card.get('answer') or '')[:60]}]: ").strip()
        if new_a:
            card["answer"] = new_a

    # Persist to DB
    extra = card.get("extra_fields") or {}
    if card_type == "detailed":
        extra["summary"] = card.get("summary", "")
        extra["explanation"] = card.get("explanation", "")
    elif card_type == "visual":
        extra["title"] = card.get("title", "")
        extra["explanation"] = card.get("explanation", "")
    elif card_type == "cloze":
        extra["text"] = card.get("text", card.get("answer", ""))
        extra["extra"] = card.get("extra", "")
    repository.update_card_content(card["id"], card["question"], card["answer"], extra)
    print("  Updated.")


def _trunc(s: str, n: int = 80) -> str:
    """Truncate a string to n chars with an ellipsis indicator."""
    return s[:n] + "..." if len(s) > n else s


def cmd_generate(args):
    if not args.topic.strip():
        print("Error: Topic cannot be empty.")
        sys.exit(1)
    if args.count <= 0:
        print("Error: Count must be greater than 0.")
        sys.exit(1)

    # Check LLM connectivity before doing any work
    conn_err = agents.check_llm_connection()
    if conn_err:
        print(f"Error: {conn_err}")
        sys.exit(1)

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
        elif card_type == "cloze":
            extra_fields = {
                "text": card.get("text", card.get("answer", "")),
                "extra": card.get("extra", ""),
            }

        card_id = repository.save_card(
            question=card["question"], answer=card["answer"],
            topic=args.topic, embedding=emb, status=status,
            card_type=card_type, extra_fields=extra_fields,
        )
        saved.append({"id": card_id, "is_dup": is_dup, "reason": reason,
                      "extra_fields": extra_fields, **card})

        _session_cards.append({"Question": card["question"], "Answer": card["answer"]})
        if not is_dup:
            dedup_cards.append({"Question": card["question"], "Answer": card["answer"]})
            dedup_embeddings.append(emb)

    # Download images AFTER dedup — only for non-duplicate cards (concurrent)
    if card_type in ("detailed", "visual"):
        non_dup_saved = [c for c in saved if not c["is_dup"]]
        queries = [(c.get("image_query", ""), c["id"]) for c in non_dup_saved if c.get("image_query")]
        if queries:
            print(f"\nSearching for images ({len(queries)} cards)...")
            results = images.search_and_download_batch(queries)
            for card in non_dup_saved:
                filename = results.get(card["id"])
                card["image_filename"] = filename
                status_str = "found" if filename else "not found"
                query = card.get("image_query", "")
                if query:
                    print(f"  [{status_str}] {query}")
                if filename:
                    extra = card.get("extra_fields") or {}
                    extra["image_filename"] = filename
                    repository.update_card_extra_fields(card["id"], extra)

        # Visual cards without images are useless — mark them as REJECTED
        if card_type == "visual":
            for card in non_dup_saved:
                if not card.get("image_filename"):
                    repository.update_card_status(card["id"], "REJECTED")
                    card["no_image"] = True
            skipped = sum(1 for c in non_dup_saved if c.get("no_image"))
            if skipped:
                print(f"  Skipped {skipped} visual card(s) with no image found.")

    # Display
    print(f"\n{'='*60}")
    print(f"Generated {len(saved)} cards:\n")

    for idx, card in enumerate(saved):
        tag = ""
        if card["is_dup"]:
            tag = " [DUPLICATE]"
        elif card.get("no_image"):
            tag = " [NO IMAGE]"
        if card_type in ("detailed", "visual") and card.get("image_filename"):
            tag = " [IMG]"
        print(f"--- Card {idx + 1}{tag} ---")
        if card["is_dup"]:
            print(f"  Reason: {card['reason']}")
        if card_type == "visual":
            print(f"  Title: {card.get('title', '')}")
            print(f"  Explanation: {card.get('explanation', '')[:120]}...")
        elif card_type == "detailed":
            print(f"  Q: {card['question']}")
            print(f"  Summary: {card.get('summary', '')}")
            print(f"  Explanation: {card.get('explanation', '')[:120]}...")
        elif card_type == "cloze":
            print(f"  Cloze: {_trunc(card.get('text', card.get('answer', '')))}")
            if card.get("extra"):
                print(f"  Hint: {_trunc(card['extra'])}")
        else:
            print(f"  Q: {card['question']}")
            print(f"  A: {card['answer']}")
        print()

    non_dups = [c for c in saved if not c["is_dup"] and not c.get("no_image")]
    if not non_dups:
        if any(c.get("no_image") for c in saved):
            print("All cards failed to find images. Try again later (DuckDuckGo rate limit).")
        else:
            print("All cards are duplicates.")
        return

    print(f"{len(non_dups)} new cards.")
    answer = input("Accept all? [Y/n/pick] ").strip().lower()

    accepted_ids = []
    if answer in ("", "y", "yes"):
        accepted_ids = [c["id"] for c in non_dups]
    elif answer in ("pick", "p"):
        for c in non_dups:
            choice = input(f"  [{c['id']}] {c['question'][:55]}? [Y/n/e(dit)] ").strip().lower()
            if choice in ("", "y", "yes"):
                accepted_ids.append(c["id"])
            elif choice in ("e", "edit"):
                _edit_card(c, card_type)
                accepted_ids.append(c["id"])
    else:
        # User declined all — mark non-duplicates as REJECTED
        for c in non_dups:
            repository.update_card_status(c["id"], "REJECTED")
        print("No cards accepted.")
        return

    accepted_set = set(accepted_ids)
    for card_id in accepted_ids:
        repository.update_card_status(card_id, "ACCEPTED")
    # Mark non-accepted non-duplicates as REJECTED
    for c in non_dups:
        if c["id"] not in accepted_set:
            repository.update_card_status(c["id"], "REJECTED")

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
            print(f"    Title: {_trunc(extra.get('title', card['question']))}")
            print(f"    Explanation: {_trunc(extra.get('explanation', card['answer']))}")
        elif ct == "cloze":
            print(f"    Cloze: {_trunc(extra.get('text', card['answer']))}")
            if extra.get("extra"):
                print(f"    Hint: {_trunc(extra['extra'])}")
        elif ct == "detailed" and extra.get("summary"):
            print(f"    Q: {card['question']}")
            print(f"    S: {_trunc(extra['summary'])}")
        else:
            print(f"    Q: {card['question']}")
            print(f"    A: {_trunc(card['answer'])}")
        print()


def cmd_export(args):
    _do_export(args.deck_name)


def cmd_clear(args):
    if args.all:
        statuses = ["GENERATED", "REJECTED", "DUPLICATE", "ACCEPTED", "EXPORTED", "CONTEXT"]
    else:
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
    except Exception as e:
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


def cmd_providers(args):
    """Show available providers and check the configured one actually answers."""
    from core.config import NATIVE_PROVIDERS, PROVIDERS, settings

    print("\nAvailable presets (set LLM_PROVIDER in .env):\n")
    for name, preset in sorted(PROVIDERS.items()):
        key_note = "needs LLM_API_KEY" if preset["needs_key"] else "no key needed"
        emb = "embeddings" if preset["embedding_model"] else "no embeddings"
        print(f"  {name:<12} {preset['label']}")
        print(f"  {'':<12} {key_note}, {emb}")
        print(f"  {'':<12} {preset['notes']}")
    for name in sorted(NATIVE_PROVIDERS):
        print(f"  {name:<12} Google Gemini")
        print(f"  {'':<12} needs GOOGLE_API_KEY, embeddings")

    llm = settings.resolve_llm()
    emb = settings.resolve_embedding()

    def _mask(key: str) -> str:
        if not key or key == "ollama":
            return "(none)"
        return f"set, ...{key[-4:]}" if len(key) > 4 else "set"

    print("\nCurrent configuration:\n")
    print("  Generation")
    print(f"    provider   {llm['provider']}")
    print(f"    endpoint   {llm['base_url'] or 'google-genai SDK'}")
    print(f"    model      {llm['model']}")
    print(f"    api key    {_mask(llm['api_key'])}")

    print("  Embeddings")
    if emb["provider"]:
        print(f"    provider   {emb['provider']}")
        print(f"    endpoint   {emb['base_url'] or 'google-genai SDK'}")
        print(f"    model      {emb['model']}")
        print(f"    api key    {_mask(emb['api_key'])}")
    else:
        print("    unavailable - dedup will use fuzzy text matching only")

    print("\nChecking connection...")
    err = agents.check_llm_connection()
    if err:
        print(f"  FAILED: {err}")
        sys.exit(1)
    print("  OK - provider reachable.")


def main():
    parser = argparse.ArgumentParser(description="Anki Flashcard Generator")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # generate
    gen = subparsers.add_parser("generate", aliases=["gen"], help="Generate flashcards for a topic")
    gen.add_argument("topic", help="Topic to generate cards about")
    gen.add_argument("--count", "-n", type=int, default=5, help="Number of cards (default: 5)")
    gen.add_argument("--type", choices=["basic", "detailed", "visual", "cloze"], default="basic",
                     help="Card type: basic (Q&A), detailed (summary + explanation + image), visual (image front), or cloze (fill-in-the-blank)")
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
    clr.add_argument("--all", action="store_true",
                     help="Clear ALL cards including accepted, exported, and context")

    # import-context
    imp = subparsers.add_parser("import-context", aliases=["import"],
                                help="Import .apkg deck as context for dedup")
    imp.add_argument("file", help="Path to .apkg file")
    imp.add_argument("--clear-existing", action="store_true",
                     help="Clear existing context cards before importing")

    # clear-context
    subparsers.add_parser("clear-context", help="Remove all imported context cards")

    # providers
    subparsers.add_parser("providers", aliases=["provider"],
                          help="Show LLM providers and test the configured one")

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
    elif args.command in ("providers", "provider"):
        cmd_providers(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

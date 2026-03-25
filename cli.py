#!/usr/bin/env python3
"""
CLI tool for generating Anki artwork flashcards.

Usage:
    python cli.py generate "Impressionism" -n 10
    python cli.py artist "Claude Monet"
    python cli.py list
    python cli.py export
"""

import argparse
import json
import logging
import sys

import storage.database  # triggers init_db()

from core import agents, embeddings, media, parsing
from core.cards import Card, GenerationRun
from core.config import settings
from export.genanki_export import export_cards
from storage import repository

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _fetch_images_and_export(saved_cards, dt, deck_type_name, deck_name, source_topic):
    """Shared helper: fetch images for accepted cards, then optionally export.

    Images are fetched automatically (no prompt) since they're essential
    for determining if a card is viable.

    saved_cards: list of Card objects (status=ACCEPTED, with .id set)
    """
    if not saved_cards:
        return

    # Fetch images automatically
    image_tasks = []
    for card in saved_cards:
        title = card.fields_json.get("Title", "")
        artist = card.fields_json.get("Artist", "")
        if title or artist:
            image_tasks.append((card.id, title, artist))

    if image_tasks:
        def on_progress(card_id, filename, verified, done, total):
            if filename:
                tag = "" if verified else " (fair-use)"
                print(f"  [{done}/{total}] Card {card_id}: {filename}{tag}")
            else:
                print(f"  [{done}/{total}] Card {card_id}: no image found")

        print(f"\nFetching {len(image_tasks)} images...")
        results = media.fetch_images_batch(image_tasks, max_workers=1, on_progress=on_progress)

        found = 0
        not_found = 0
        for card_id, (filename, verified) in results.items():
            if filename:
                repository.update_card_media(card_id, image_filename=filename)
                for card in saved_cards:
                    if card.id == card_id:
                        card.image_filename = filename
                found += 1
            else:
                # No image found at all — add Google Images search link
                for card in saved_cards:
                    if card.id == card_id:
                        title = card.fields_json.get("Title", "")
                        artist = card.fields_json.get("Artist", "")
                        search_url = media._google_images_url(title, artist)
                        card.fields_json["Note"] = (
                            f'<a href="{search_url}">'
                            f'Search for "{title}" by {artist}</a>'
                        )
                        repository.save_card_fields(card.id, card.fields_json)
                not_found += 1

        print(f"  Images: {found} downloaded, {not_found} not found")

    # Export
    do_export = input("\nExport to .apkg now? [Y/n] ").strip().lower()
    if do_export in ("", "y", "yes"):
        accepted_cards = repository.get_cards(deck_type=deck_type_name, status="ACCEPTED")
        if accepted_cards:
            path = export_cards(accepted_cards, dt, deck_name=deck_name)
            for c in accepted_cards:
                repository.update_card_status(c.id, "EXPORTED")
            print(f"\nExported to: {path}")
            print("Import this file into Anki: File > Import")
        else:
            print("No accepted cards to export.")


def _display_and_accept_artworks(new_artworks, card_fields_list, dt, deck_type_name, source_topic):
    """Display artwork cards, let user accept/reject, save to DB. Returns list of accepted Card objects."""
    skip_fields = {f["name"] for f in dt.fields_schema if f["type"] == "(Skip)"}

    print(f"\n{'='*60}")
    print(f"{len(new_artworks)} new paintings:\n")

    for idx, (art, fields) in enumerate(zip(new_artworks, card_fields_list)):
        img_tag = "[IMG]" if art.get("image_url") else "[no img]"
        print(f"--- {idx + 1}. {art['title']} {img_tag} ---")
        for key, val in fields.items():
            if key in skip_fields or not val or key == "Artwork":
                continue
            print(f"  {key}: {val}")
        print()

    answer = input(f"Accept all {len(new_artworks)} cards? [Y/n/pick] ").strip().lower()

    accepted_indices = []
    if answer in ("", "y", "yes"):
        accepted_indices = list(range(len(new_artworks)))
    elif answer == "pick":
        for idx in range(len(new_artworks)):
            choice = input(f"  Accept '{new_artworks[idx]['title']}'? [Y/n] ").strip().lower()
            if choice in ("", "y", "yes"):
                accepted_indices.append(idx)
    else:
        print("No cards accepted.")
        return []

    if not accepted_indices:
        print("No cards accepted.")
        return []

    saved_cards = []
    for idx in accepted_indices:
        fields = card_fields_list[idx]
        card = Card(
            deck_type=deck_type_name, fields_json=fields,
            source_topic=source_topic, status="ACCEPTED",
        )
        card_id = repository.save_card(card)
        card.id = card_id
        saved_cards.append(card)

    print(f"\nAccepted {len(saved_cards)} cards.")
    return saved_cards


def cmd_generate(args):
    deck_type_name = args.deck_type
    dt = repository.get_deck_type(deck_type_name)
    if not dt:
        print(f"Error: Unknown deck type '{deck_type_name}'")
        sys.exit(1)

    # For artwork decks: use Wikidata (no LLM, no hallucinations)
    if deck_type_name == "artwork":
        from core.wikidata import query_artworks_by_topic, artworks_to_card_fields

        print(f"\nSearching Wikidata for '{args.topic}'...")
        artworks = query_artworks_by_topic(args.topic, limit=args.count)

        if not artworks:
            print(f"No artworks found on Wikidata for '{args.topic}'.")
            print("Try: movement (Impressionism), museum (Louvre), period (1800s)")
            return

        with_img = sum(1 for a in artworks if a.get("image_url"))
        print(f"Found {len(artworks)} artworks ({with_img} with free images).")

        # Dedup against existing deck
        existing_cards = repository.get_cards(deck_type=deck_type_name)
        existing_titles = {c.fields_json.get("Title", "").strip().lower() for c in existing_cards}

        new_artworks = [a for a in artworks if a["title"].strip().lower() not in existing_titles]
        skipped = len(artworks) - len(new_artworks)
        if skipped:
            print(f"Skipped {skipped} already in deck.")

        if not new_artworks:
            print("All artworks are already in the deck!")
            return

        card_fields_list = artworks_to_card_fields(new_artworks)
        saved_cards = _display_and_accept_artworks(
            new_artworks, card_fields_list, dt, deck_type_name, args.topic
        )
        _fetch_images_and_export(saved_cards, dt, deck_type_name, args.deck_name, args.topic)
        return

    # Non-artwork decks: use LLM pipeline
    if not settings.google_api_key:
        print("Error: GOOGLE_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    field_names = [f["name"] for f in dt.fields_schema]
    field_config = {f["name"]: f["type"] for f in dt.fields_schema}

    existing_cards, existing_embeddings = repository.get_existing_cards_with_embeddings(deck_type_name)
    existing_text = ", ".join(c.get("Title", "") for c in existing_cards if c.get("Title"))
    if not existing_text:
        existing_text = "No existing cards found."

    print(f"\nExisting cards in '{deck_type_name}': {len(existing_cards)}")

    file_text = None
    if args.file:
        from core.ingestion import extract_text
        with open(args.file, "rb") as f:
            file_text = extract_text(f.read(), args.file)
        print(f"Loaded file: {args.file} ({len(file_text)} chars)")

    print(f"\nAnalyzing knowledge gaps for '{args.topic}'...")
    missing_concepts, persona = agents.analyze_knowledge_gaps(
        args.topic, existing_text, source_text=file_text, num=args.count
    )
    print(f"Persona: {persona}")
    print(f"Gap Analysis:\n{missing_concepts}\n")

    print(f"Generating {args.count} cards as {persona}...")
    raw = agents.generate_cards(missing_concepts, args.count, field_config, persona=persona)
    parsed = parsing.smart_parse(raw, field_names)

    if not parsed:
        print("Generation failed. Raw output:")
        print(raw)
        sys.exit(1)

    run = GenerationRun(
        topic=args.topic, deck_name=dt.name, deck_type=deck_type_name,
        persona=persona, total_generated=len(parsed),
    )
    run_id = repository.create_run(run)

    use_embeddings = not getattr(args, 'no_embeddings', False)
    saved = []
    for i, card_fields in enumerate(parsed):
        emb = None
        if use_embeddings:
            card_text = embeddings.card_text_for_embedding(card_fields)
            emb = embeddings.get_embedding(card_text)

        is_dup, reason = embeddings.is_duplicate(
            card_fields, existing_cards, existing_embeddings, new_embedding=emb
        )

        status = "DUPLICATE" if is_dup else "GENERATED"
        card = Card(
            deck_type=deck_type_name, fields_json=card_fields,
            source_topic=args.topic, run_id=run_id, status=status,
        )
        card_id = repository.save_card(card, embedding=emb)
        card.id = card_id
        saved.append((card, is_dup, reason))

        if not is_dup:
            existing_cards.append(card_fields)
            existing_embeddings.append(emb)

    print(f"\n{'='*60}")
    print(f"Generated {len(saved)} cards:\n")

    skip_fields = {f["name"] for f in dt.fields_schema if f["type"] == "(Skip)"}
    for idx, (card, is_dup, reason) in enumerate(saved):
        dup_tag = " [DUPLICATE]" if is_dup else ""
        print(f"--- Card {idx + 1}{dup_tag} ---")
        if is_dup:
            print(f"  Reason: {reason}")
        for key, val in card.fields_json.items():
            if key in skip_fields or not val:
                continue
            print(f"  {key}: {val}")
        print()

    non_dups = [(i, s) for i, s in enumerate(saved) if not s[1]]
    if not non_dups:
        print("All cards are duplicates. Nothing to accept.")
        return

    print(f"{len(non_dups)} non-duplicate cards available.")
    answer = input("Accept all? [Y/n/pick] ").strip().lower()

    accepted_ids = []
    if answer in ("", "y", "yes"):
        accepted_ids = [saved[i][0].id for i, _ in non_dups]
    elif answer == "pick":
        for i, (card, _, _) in non_dups:
            choice = input(f"  Accept card {i+1}? [Y/n] ").strip().lower()
            if choice in ("", "y", "yes"):
                accepted_ids.append(card.id)
    else:
        print("No cards accepted.")
        return

    for card, is_dup, _ in saved:
        if card.id in accepted_ids:
            repository.update_card_status(card.id, "ACCEPTED")

    accepted_count = len(accepted_ids)
    repository.update_run_accepted(run_id, accepted_count)
    print(f"\nAccepted {accepted_count} cards.")

    if accepted_count == 0:
        return

    accepted_card_objs = [card for card, is_dup, _ in saved if card.id in accepted_ids]
    _fetch_images_and_export(accepted_card_objs, dt, deck_type_name, args.deck_name, args.topic)


def cmd_list(args):
    cards = repository.get_cards(deck_type=args.deck_type, status=args.status)
    if not cards:
        print("No cards found.")
        return

    print(f"\n{len(cards)} cards:\n")
    for card in cards:
        print(f"  [{card.id}] ({card.status}) {card.fields_json.get('Title', card.fields_json.get('Topic', '?'))}")
        print(f"       Artist: {card.fields_json.get('Artist', '-')}")
        if card.image_filename:
            print(f"       Image: {card.image_filename}")
        print()


def cmd_import(args):
    from core.apkg_import import import_apkg

    print(f"Importing cards from: {args.file}")
    stats = import_apkg(
        args.file,
        deck_type=args.deck_type,
        compute_embeddings=not args.no_embeddings,
    )
    if "error" in stats:
        print(f"Error: {stats['error']}")
        sys.exit(1)


def cmd_artist(args):
    """Look up an artist's real paintings on Wikidata and create cards."""
    from core.wikidata import query_artist_artworks, artworks_to_card_fields

    deck_type_name = args.deck_type
    dt = repository.get_deck_type(deck_type_name)
    if not dt:
        print(f"Error: Unknown deck type '{deck_type_name}'")
        sys.exit(1)

    print(f"\nSearching Wikidata for artworks by '{args.artist_name}'...")
    artworks = query_artist_artworks(args.artist_name)

    if not artworks:
        print("No artworks found on Wikidata for this artist.")
        print("Try the exact name as it appears on Wikipedia (e.g. 'Claude Monet', not 'Monet').")
        return

    with_img = sum(1 for a in artworks if a["image_url"])
    print(f"Found {len(artworks)} artworks ({with_img} with free images).")

    if args.limit and args.limit < len(artworks):
        artworks = artworks[:args.limit]
        print(f"Showing first {args.limit}.")

    # Dedup against existing deck
    existing_cards = repository.get_cards(deck_type=deck_type_name)
    existing_titles = {c.fields_json.get("Title", "").strip().lower() for c in existing_cards}

    new_artworks = [a for a in artworks if a["title"].strip().lower() not in existing_titles]
    skipped = len(artworks) - len(new_artworks)
    if skipped:
        print(f"Skipped {skipped} already in deck.")

    if not new_artworks:
        print("All paintings from this artist are already in the deck!")
        return

    card_fields_list = artworks_to_card_fields(new_artworks, args.artist_name)
    saved_cards = _display_and_accept_artworks(
        new_artworks, card_fields_list, dt, deck_type_name, args.artist_name
    )
    _fetch_images_and_export(saved_cards, dt, deck_type_name, args.deck_name, args.artist_name)


def cmd_clear(args):
    """Clear generated/rejected/duplicate cards from previous sessions."""
    statuses = args.status.split(",") if args.status else ["GENERATED", "REJECTED", "DUPLICATE"]
    total = 0
    for status in statuses:
        count = repository.delete_cards_by_status(status.strip(), deck_type=args.deck_type)
        if count:
            print(f"Deleted {count} {status} cards.")
            total += count
    if total == 0:
        print("No cards to clear.")
    else:
        print(f"Total: {total} cards cleared.")


def cmd_export(args):
    dt = repository.get_deck_type(args.deck_type)
    if not dt:
        print(f"Error: Unknown deck type '{args.deck_type}'")
        sys.exit(1)

    status = args.status or "ACCEPTED"
    cards = repository.get_cards(deck_type=args.deck_type, status=status)
    if not cards:
        print(f"No {status} cards to export.")
        return

    path = export_cards(cards, dt, deck_name=args.deck_name)
    for c in cards:
        repository.update_card_status(c.id, "EXPORTED")
    print(f"Exported {len(cards)} cards to: {path}")


def main():
    parser = argparse.ArgumentParser(description="Anki Card Generator CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # generate
    gen = subparsers.add_parser("generate", aliases=["gen"],
        help="Generate cards (artwork: Wikidata, other: LLM)")
    gen.add_argument("topic", help="Topic, movement, museum, or period (e.g. 'Impressionism', 'Louvre', '1800s')")
    gen.add_argument("--count", "-n", type=int, default=30, help="Max results (default: 30)")
    gen.add_argument("--file", "-f", help="Source file (PDF/TXT) for context (LLM only)")
    gen.add_argument("--deck-type", "-t", default="artwork", help="Deck type (default: artwork)")
    gen.add_argument("--deck-name", "-d", default="Great Works of Art", help="Deck name in Anki")
    gen.add_argument("--audio-lang", default="en", help="Audio language (default: en)")
    gen.add_argument("--no-embeddings", action="store_true", help="Skip embedding API calls (LLM only)")

    # list
    ls = subparsers.add_parser("list", aliases=["ls"], help="List generated cards")
    ls.add_argument("--deck-type", "-t", default="artwork")
    ls.add_argument("--status", "-s", help="Filter by status")

    # import
    imp = subparsers.add_parser("import", help="Import existing .apkg for dedup awareness")
    imp.add_argument("file", help="Path to .apkg file")
    imp.add_argument("--deck-type", "-t", default="artwork")
    imp.add_argument("--no-embeddings", action="store_true", help="Skip embedding computation")

    # artist (Wikidata lookup)
    art = subparsers.add_parser("artist", help="Look up real paintings by artist name (via Wikidata)")
    art.add_argument("artist_name", help="Artist name (e.g. 'Claude Monet')")
    art.add_argument("--limit", "-n", type=int, default=0, help="Max paintings to show (0 = all)")
    art.add_argument("--deck-type", "-t", default="artwork", help="Deck type (default: artwork)")
    art.add_argument("--deck-name", "-d", default="Great Works of Art", help="Deck name in Anki")

    # clear
    clr = subparsers.add_parser("clear", help="Clear generated/rejected/duplicate cards")
    clr.add_argument("--deck-type", "-t", default="artwork")
    clr.add_argument("--status", "-s", default="GENERATED,REJECTED,DUPLICATE",
                     help="Statuses to clear (comma-separated, default: GENERATED,REJECTED,DUPLICATE)")

    # export
    exp = subparsers.add_parser("export", help="Export cards to .apkg")
    exp.add_argument("--deck-type", "-t", default="artwork")
    exp.add_argument("--deck-name", "-d", default="Great Works of Art")
    exp.add_argument("--status", "-s", default="ACCEPTED", help="Status to export (default: ACCEPTED)")

    args = parser.parse_args()

    if args.command in ("generate", "gen"):
        cmd_generate(args)
    elif args.command in ("list", "ls"):
        cmd_list(args)
    elif args.command == "import":
        cmd_import(args)
    elif args.command == "artist":
        cmd_artist(args)
    elif args.command == "clear":
        cmd_clear(args)
    elif args.command == "export":
        cmd_export(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

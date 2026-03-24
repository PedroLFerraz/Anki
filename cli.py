#!/usr/bin/env python3
"""
CLI tool for generating Anki artwork flashcards.

Usage:
    python cli.py "Impressionism" --count 5
    python cli.py "Baroque painting" --count 3 --file notes.pdf
    python cli.py --list                          # show generated cards
    python cli.py --export                        # export accepted cards
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


def cmd_generate(args):
    deck_type_name = args.deck_type
    dt = repository.get_deck_type(deck_type_name)
    if not dt:
        print(f"Error: Unknown deck type '{deck_type_name}'")
        sys.exit(1)

    if not settings.google_api_key:
        print("Error: GOOGLE_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    field_names = [f["name"] for f in dt.fields_schema]
    field_config = {f["name"]: f["type"] for f in dt.fields_schema}

    # Get existing cards for dedup context
    existing_cards, existing_embeddings = repository.get_existing_cards_with_embeddings(deck_type_name)
    existing_text = ", ".join(c.get("Title", "") for c in existing_cards if c.get("Title"))
    if not existing_text:
        existing_text = "No existing cards found."

    print(f"\nExisting cards in '{deck_type_name}': {len(existing_cards)}")

    # Handle file source
    file_text = None
    if args.file:
        from core.ingestion import extract_text
        with open(args.file, "rb") as f:
            file_text = extract_text(f.read(), args.file)
        print(f"Loaded file: {args.file} ({len(file_text)} chars)")

    # Agent 1: Gap Analysis
    print(f"\nAnalyzing knowledge gaps for '{args.topic}'...")
    missing_concepts, persona = agents.analyze_knowledge_gaps(
        args.topic, existing_text, source_text=file_text, num=args.count
    )
    print(f"Persona: {persona}")
    print(f"Gap Analysis:\n{missing_concepts}\n")

    # Agent 2: Generate Cards
    print(f"Generating {args.count} cards as {persona}...")
    raw = agents.generate_cards(missing_concepts, args.count, field_config, persona=persona)
    parsed = parsing.smart_parse(raw, field_names)

    if not parsed:
        print("Generation failed. Raw output:")
        print(raw)
        sys.exit(1)

    # Create run record
    run = GenerationRun(
        topic=args.topic, deck_name=dt.name, deck_type=deck_type_name,
        persona=persona, total_generated=len(parsed),
    )
    run_id = repository.create_run(run)

    # Save cards with dedup
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

    # Display cards for review
    print(f"\n{'='*60}")
    print(f"Generated {len(saved)} cards:\n")

    # Get skip fields to hide from display
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

    # Interactive accept/reject
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

    # Update status
    for card, is_dup, _ in saved:
        if card.id in accepted_ids:
            repository.update_card_status(card.id, "ACCEPTED")

    accepted_count = len(accepted_ids)
    repository.update_run_accepted(run_id, accepted_count)
    print(f"\nAccepted {accepted_count} cards.")

    if accepted_count == 0:
        return

    # Fetch images for accepted cards (parallel)
    fetch = input("Fetch images? [Y/n] ").strip().lower()
    if fetch in ("", "y", "yes"):
        # Build search tasks using Title + Artist for precise artwork search
        image_tasks = []
        for card, is_dup, _ in saved:
            if card.id not in accepted_ids:
                continue
            fields = card.fields_json
            title = fields.get("Title", "")
            artist = fields.get("Artist", "")
            if title or artist:
                image_tasks.append((card.id, title, artist))

        if image_tasks:
            def on_progress(card_id, filename, verified, done, total):
                if filename:
                    print(f"  [{done}/{total}] Card {card_id}: {filename}")
                elif not verified:
                    print(f"  [{done}/{total}] Card {card_id}: copyrighted - search link added")
                else:
                    print(f"  [{done}/{total}] Card {card_id}: not found")

            print(f"\nFetching {len(image_tasks)} images...")
            results = media.fetch_images_batch(image_tasks, max_workers=1, on_progress=on_progress)

            found = 0
            copyrighted = 0
            for card_id, (filename, verified) in results.items():
                if filename:
                    repository.update_card_media(card_id, image_filename=filename)
                    for card, _, _ in saved:
                        if card.id == card_id:
                            card.image_filename = filename
                    found += 1
                elif not verified:
                    # No verified image found — painting is likely copyrighted.
                    # Put a Google Images search link in the Note field
                    # (not Artwork, which is Image-typed and won't render <a> tags).
                    for card, _, _ in saved:
                        if card.id == card_id:
                            title = card.fields_json.get("Title", "")
                            artist = card.fields_json.get("Artist", "")
                            search_url = media._google_images_url(title, artist)
                            card.fields_json["Note"] = (
                                f'<a href="{search_url}">'
                                f'[Copyrighted] Search for "{title}" by {artist}</a>'
                            )
                            repository.save_card_fields(card.id, card.fields_json)
                    copyrighted += 1

            print(f"  Images: {found} downloaded, {copyrighted} copyrighted (search links in Note)")

    # Export
    do_export = input("\nExport to .apkg now? [Y/n] ").strip().lower()
    if do_export in ("", "y", "yes"):
        accepted_cards = repository.get_cards(deck_type=deck_type_name, status="ACCEPTED")
        if accepted_cards:
            path = export_cards(accepted_cards, dt, deck_name=args.deck_name)
            for c in accepted_cards:
                repository.update_card_status(c.id, "EXPORTED")
            print(f"\nExported to: {path}")
            print("Import this file into Anki: File > Import")
        else:
            print("No accepted cards to export.")


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

    # Apply limit
    if args.limit and args.limit < len(artworks):
        artworks = artworks[:args.limit]
        print(f"Showing first {args.limit}.")

    # Filter out paintings already in the deck
    existing_cards = repository.get_cards(deck_type=deck_type_name)
    existing_titles = {c.fields_json.get("Title", "").strip().lower() for c in existing_cards}

    new_artworks = []
    skipped = 0
    for art in artworks:
        if art["title"].strip().lower() in existing_titles:
            skipped += 1
        else:
            new_artworks.append(art)

    if skipped:
        print(f"Skipped {skipped} already in deck.")

    if not new_artworks:
        print("All paintings from this artist are already in the deck!")
        return

    # Convert to card fields
    card_fields_list = artworks_to_card_fields(new_artworks, args.artist_name)

    # Display
    print(f"\n{'='*60}")
    print(f"{len(new_artworks)} new paintings:\n")

    skip_fields = {f["name"] for f in dt.fields_schema if f["type"] == "(Skip)"}
    for idx, (art, fields) in enumerate(zip(new_artworks, card_fields_list)):
        img_tag = "[IMG]" if art["image_url"] else "[no img]"
        print(f"--- {idx + 1}. {art['title']} {img_tag} ---")
        for key, val in fields.items():
            if key in skip_fields or not val or key == "Artwork":
                continue
            print(f"  {key}: {val}")
        print()

    # Interactive accept/reject
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
        return

    if not accepted_indices:
        print("No cards accepted.")
        return

    # Save accepted cards to DB
    saved_cards = []
    for idx in accepted_indices:
        fields = card_fields_list[idx]
        card = Card(
            deck_type=deck_type_name, fields_json=fields,
            source_topic=args.artist_name, status="ACCEPTED",
        )
        card_id = repository.save_card(card)
        card.id = card_id
        saved_cards.append((card, new_artworks[idx]))

    print(f"\nAccepted {len(saved_cards)} cards.")

    # Fetch images
    fetch = input("Fetch images? [Y/n] ").strip().lower()
    if fetch in ("", "y", "yes"):
        image_tasks = []
        for card, art in saved_cards:
            title = card.fields_json.get("Title", "")
            artist = card.fields_json.get("Artist", "")
            if title or artist:
                image_tasks.append((card.id, title, artist))

        if image_tasks:
            def on_progress(card_id, filename, verified, done, total):
                if filename:
                    print(f"  [{done}/{total}] Card {card_id}: {filename}")
                elif not verified:
                    print(f"  [{done}/{total}] Card {card_id}: copyrighted - search link added")
                else:
                    print(f"  [{done}/{total}] Card {card_id}: not found")

            print(f"\nFetching {len(image_tasks)} images...")
            results = media.fetch_images_batch(image_tasks, max_workers=1, on_progress=on_progress)

            found = 0
            copyrighted = 0
            for card_id, (filename, verified) in results.items():
                if filename:
                    repository.update_card_media(card_id, image_filename=filename)
                    for card, _ in saved_cards:
                        if card.id == card_id:
                            card.image_filename = filename
                    found += 1
                elif not verified:
                    for card, _ in saved_cards:
                        if card.id == card_id:
                            title = card.fields_json.get("Title", "")
                            artist = card.fields_json.get("Artist", "")
                            search_url = media._google_images_url(title, artist)
                            card.fields_json["Note"] = (
                                f'<a href="{search_url}">'
                                f'[Copyrighted] Search for "{title}" by {artist}</a>'
                            )
                            repository.save_card_fields(card.id, card.fields_json)
                    copyrighted += 1

            print(f"  Images: {found} downloaded, {copyrighted} copyrighted (search links in Note)")

    # Export
    do_export = input("\nExport to .apkg now? [Y/n] ").strip().lower()
    if do_export in ("", "y", "yes"):
        accepted_cards = repository.get_cards(deck_type=deck_type_name, status="ACCEPTED")
        if accepted_cards:
            path = export_cards(accepted_cards, dt, deck_name=args.deck_name)
            for c in accepted_cards:
                repository.update_card_status(c.id, "EXPORTED")
            print(f"\nExported to: {path}")
            print("Import this file into Anki: File > Import")
        else:
            print("No accepted cards to export.")


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
    gen = subparsers.add_parser("generate", aliases=["gen"], help="Generate new cards")
    gen.add_argument("topic", help="Topic to generate cards for")
    gen.add_argument("--count", "-n", type=int, default=3, help="Number of cards (default: 3)")
    gen.add_argument("--file", "-f", help="Source file (PDF/TXT) for context")
    gen.add_argument("--deck-type", "-t", default="artwork", help="Deck type (default: artwork)")
    gen.add_argument("--deck-name", "-d", default="Great Works of Art", help="Deck name in Anki")
    gen.add_argument("--audio-lang", default="en", help="Audio language (default: en)")
    gen.add_argument("--no-embeddings", action="store_true", help="Skip embedding API calls (uses fuzzy title matching only for dedup)")

    # list
    ls = subparsers.add_parser("list", aliases=["ls"], help="List generated cards")
    ls.add_argument("--deck-type", "-t", default="artwork")
    ls.add_argument("--status", "-s", help="Filter by status")

    # import
    imp = subparsers.add_parser("import", help="Import existing .apkg for dedup awareness")
    imp.add_argument("file", help="Path to .apkg file")
    imp.add_argument("--deck-type", "-t", default="artwork")
    imp.add_argument("--no-embeddings", action="store_true", help="Skip embedding computation (faster but no semantic dedup)")

    # artist (Wikidata lookup)
    art = subparsers.add_parser("artist", help="Look up real paintings by artist name (via Wikidata)")
    art.add_argument("artist_name", help="Artist name (e.g. 'Claude Monet')")
    art.add_argument("--limit", "-n", type=int, default=0, help="Max paintings to show (0 = all)")
    art.add_argument("--deck-type", "-t", default="artwork", help="Deck type (default: artwork)")
    art.add_argument("--deck-name", "-d", default="Great Works of Art", help="Deck name in Anki")

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
    elif args.command == "export":
        cmd_export(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

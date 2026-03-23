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
    saved = []
    for i, card_fields in enumerate(parsed):
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

    for idx, (card, is_dup, reason) in enumerate(saved):
        dup_tag = " [DUPLICATE]" if is_dup else ""
        print(f"--- Card {idx + 1}{dup_tag} ---")
        if is_dup:
            print(f"  Reason: {reason}")
        for key, val in card.fields_json.items():
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

    # Fetch media for accepted cards
    fetch = input("Fetch images & audio? [Y/n] ").strip().lower()
    if fetch in ("", "y", "yes"):
        print("\nFetching media...")
        for card, is_dup, _ in saved:
            if card.id not in accepted_ids:
                continue
            fields = card.fields_json

            # Image
            search_query = fields.get(field_names[0], "")
            artist = fields.get("Artist", "")
            if artist:
                search_query = f"{search_query} by {artist}"
            if search_query:
                print(f"  Searching image: {search_query}")
                urls = media.search_images(search_query)
                if urls:
                    result = media.download_image(urls)
                    if result:
                        repository.update_card_media(card.id, image_filename=result[0])
                        card.image_filename = result[0]

            # Audio
            audio_text = fields.get("Artist", "") or fields.get("Title", "")
            if audio_text:
                print(f"  Generating audio: {audio_text}")
                result = media.generate_audio(audio_text, lang=args.audio_lang)
                if result:
                    repository.update_card_media(card.id, audio_filename=result[0])
                    card.audio_filename = result[0]

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

    # list
    ls = subparsers.add_parser("list", aliases=["ls"], help="List generated cards")
    ls.add_argument("--deck-type", "-t", default="artwork")
    ls.add_argument("--status", "-s", help="Filter by status")

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
    elif args.command == "export":
        cmd_export(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Export approved Boynton Bot corrections as Qwen DPO preference pairs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "exports" / "qwen_dpo.jsonl"


def final_assistant_message(messages: Any) -> dict[str, str]:
    """Return the last non-empty assistant answer from a stored completion."""
    if not isinstance(messages, list):
        raise ValueError("completion is not a JSON array")

    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return {"role": "assistant", "content": content}

    raise ValueError("completion has no non-empty assistant answer")


def dpo_example(row: dict[str, Any]) -> dict[str, Any]:
    prompt = row["prompt"]
    if not isinstance(prompt, list) or not prompt:
        raise ValueError("prompt is not a non-empty JSON array")
    if not all(isinstance(message, dict) and isinstance(message.get("role"), str) for message in prompt):
        raise ValueError("prompt contains an invalid message")

    return {
        "prompt": prompt,
        "chosen": [final_assistant_message(row["correction"])],
        "rejected": [final_assistant_message(row["response"])],
        "metadata": {
            "source": "boynton-bot-feedback",
            "training_example_id": row["id"],
            "created_at": row["created_at"].isoformat(),
        },
    }


def load_examples(database_url: str) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    query = """
        SELECT id, created_at, prompt, response, correction
        FROM training_examples
        WHERE label = 'down' AND correction_status = 'approved'
        ORDER BY id ASC
    """
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

    examples: list[dict[str, Any]] = []
    skipped: list[tuple[int, str]] = []
    for row in rows:
        try:
            examples.append(dpo_example(row))
        except (KeyError, ValueError) as error:
            skipped.append((row["id"], str(error)))
    return examples, skipped


def write_jsonl(examples: list[dict[str, Any]], output: Path, force: bool) -> None:
    output = output.expanduser().resolve()
    if output.exists() and not force:
        raise FileExistsError(f"output already exists: {output} (pass --force to replace it)")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            for example in examples:
                temporary.write(json.dumps(example, ensure_ascii=False, separators=(",", ":")))
                temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(output)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export approved thumbs-down corrections as final-answer DPO pairs. "
            "Tool calls and tool results are intentionally omitted from chosen/rejected."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("BOYNTON_DATABASE_URL", "postgresql:///boynton_bot"),
        help="PostgreSQL URL (default: BOYNTON_DATABASE_URL or local boynton_bot database)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSONL destination (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace the output file if it already exists",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()
    try:
        examples, skipped = load_examples(args.database_url)
        if not examples:
            print("error: no valid approved corrections found; no file written", file=sys.stderr)
            return 1
        write_jsonl(examples, args.output, args.force)
    except (FileExistsError, OSError, psycopg.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for example_id, reason in skipped:
        print(f"skipped training example {example_id}: {reason}", file=sys.stderr)
    print(f"wrote {len(examples)} DPO pairs to {args.output.expanduser().resolve()}")
    if skipped:
        print(f"skipped {len(skipped)} invalid approved rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

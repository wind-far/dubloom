"""CLI runner: enqueue a YouTube URL and execute the pipeline synchronously."""

from __future__ import annotations

import argparse
import json
import sys

from backend.app import database
from backend.app.pipeline import run_task


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Dubloom localization pipeline once.")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--task-id", default=None, help="Reuse an existing task id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database.init_db()
    task_id = args.task_id or database.create_task(args.url.strip())
    print(f"task_id={task_id}", flush=True)
    run_task(task_id)
    final = database.get_task(task_id)
    print(json.dumps(final, indent=2, ensure_ascii=False), flush=True)
    return 0 if final and final.get("status") == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())

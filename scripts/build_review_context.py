from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.helpers import dump_json, load_json, read_optional_text


SIGNAL_LIMITS = {
    "project_metadata": 4000,
    "file_inventory": 5000,
    "todos": 4000,
    "tests": 4000,
    "lint": 4000,
    "git_summary": 3000,
    "ci_workflows": 4000,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build compact review context JSON.")
    parser.add_argument("--artifacts-dir", required=True, help="Collector output directory.")
    parser.add_argument("--repo-root", required=True, help="Absolute or relative repository root.")
    parser.add_argument("--paths", required=True, help="Configured review path scope.")
    parser.add_argument("--review-mode", required=True, help="Workflow review mode.")
    parser.add_argument("--max-issues", required=True, type=int, help="Cap for requested findings.")
    parser.add_argument("--prompt-preset", required=True, help="Prompt preset requested by workflow.")
    parser.add_argument("--output", required=True, help="Context JSON output path.")
    return parser.parse_args()


def build_context(args: argparse.Namespace) -> dict[str, object]:
    artifacts_dir = Path(args.artifacts_dir)
    repo_root = Path(args.repo_root).resolve()
    metadata = load_json(artifacts_dir / "metadata.json")
    signals = {
        name: read_optional_text(artifacts_dir / f"{name}.txt", max_chars=limit)
        for name, limit in SIGNAL_LIMITS.items()
    }
    return {
        "repo": {
            "name": metadata.get("repository_name", repo_root.name),
            "root": str(repo_root),
            "paths": args.paths,
            "default_branch": metadata.get("default_branch"),
            "file_counts": metadata.get("file_counts", {}),
            "collector_notes": metadata.get("collector_notes", []),
        },
        "review_mode": args.review_mode,
        "prompt_preset": args.prompt_preset,
        "max_issues": args.max_issues,
        "signals": signals,
    }


def main() -> None:
    args = parse_args()
    context = build_context(args)
    dump_json(Path(args.output), context)


if __name__ == "__main__":
    main()

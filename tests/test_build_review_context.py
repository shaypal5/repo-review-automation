from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from scripts.build_review_context import build_context
from scripts.helpers import dump_json


def test_build_context_truncates_and_includes_metadata(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "signals"
    artifacts_dir.mkdir()

    dump_json(
        artifacts_dir / "metadata.json",
        {
            "repository_name": "sample-repo",
            "default_branch": "main",
            "file_counts": {".py": 4},
            "collector_notes": ["note"],
        },
    )
    (artifacts_dir / "project_metadata.txt").write_text("metadata", encoding="utf-8")
    (artifacts_dir / "file_inventory.txt").write_text("x" * 6000, encoding="utf-8")
    (artifacts_dir / "todos.txt").write_text("todo line", encoding="utf-8")
    (artifacts_dir / "tests.txt").write_text("tests line", encoding="utf-8")
    (artifacts_dir / "lint.txt").write_text("lint line", encoding="utf-8")
    (artifacts_dir / "git_summary.txt").write_text("git line", encoding="utf-8")
    (artifacts_dir / "ci_workflows.txt").write_text("workflow line", encoding="utf-8")

    args = Namespace(
        artifacts_dir=str(artifacts_dir),
        repo_root=str(tmp_path),
        paths="src",
        review_mode="quick",
        max_issues=3,
        prompt_preset="default",
    )

    context = build_context(args)

    assert context["repo"]["name"] == "sample-repo"
    assert context["repo"]["default_branch"] == "main"
    assert context["review_mode"] == "quick"
    assert context["max_issues"] == 3
    assert context["signals"]["project_metadata"] == "metadata"
    assert context["signals"]["file_inventory"].endswith("...[truncated]")


def test_build_context_marks_missing_signal_files(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "signals"
    artifacts_dir.mkdir()
    dump_json(
        artifacts_dir / "metadata.json",
        {
            "repository_name": "sample-repo",
            "default_branch": None,
            "file_counts": {},
            "collector_notes": [],
        },
    )

    args = Namespace(
        artifacts_dir=str(artifacts_dir),
        repo_root=str(tmp_path),
        paths=".",
        review_mode="full",
        max_issues=5,
        prompt_preset="python",
    )

    context = build_context(args)

    assert context["signals"]["todos"] == "Not collected."
    assert context["signals"]["ci_workflows"] == "Not collected."

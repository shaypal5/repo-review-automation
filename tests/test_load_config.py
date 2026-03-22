from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from scripts.load_config import build_effective_config

FIXTURES = Path(__file__).parent / "fixtures"


def make_args(tmp_path: Path, **overrides: str) -> Namespace:
    return Namespace(
        repo_root=str(tmp_path),
        config_path=overrides.pop("config_path", ".github/repo-review.yml"),
        review_mode=overrides.pop("review_mode", ""),
        prompt_preset=overrides.pop("prompt_preset", ""),
        min_severity=overrides.pop("min_severity", ""),
        max_issues=overrides.pop("max_issues", ""),
        labels=overrides.pop("labels", ""),
        paths=overrides.pop("paths", ""),
        dedupe_mode=overrides.pop("dedupe_mode", ""),
        issue_prefix=overrides.pop("issue_prefix", ""),
        comment_mode=overrides.pop("comment_mode", ""),
        comment_issue_number=overrides.pop("comment_issue_number", ""),
        reopen_closed_issues=overrides.pop("reopen_closed_issues", ""),
        ignored_paths=overrides.pop("ignored_paths", ""),
        ignored_categories=overrides.pop("ignored_categories", ""),
        output=str(tmp_path / "out.json"),
    )


def test_absent_config_uses_defaults_and_inputs(tmp_path: Path) -> None:
    config = build_effective_config(
        make_args(tmp_path, prompt_preset="python", max_issues="7", labels="triage, ai-review")
    )

    assert config["config_found"] is False
    assert config["review_mode"] == "full"
    assert config["prompt_preset"] == "python"
    assert config["max_issues"] == 7
    assert config["labels"] == ["triage", "ai-review"]
    assert config["sources"]["review_mode"] == "default"
    assert config["sources"]["prompt_preset"] == "workflow_input"


def test_config_merge_precedence_prefers_inputs_over_repo_config(tmp_path: Path) -> None:
    config_dir = tmp_path / ".github"
    config_dir.mkdir()
    (config_dir / "repo-review.yml").write_text(
        (FIXTURES / "repo_review_config.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    config = build_effective_config(
        make_args(
            tmp_path,
            labels="ops,platform",
            max_issues="9",
            comment_issue_number="41",
            reopen_closed_issues="false",
        )
    )

    assert config["review_mode"] == "quick"
    assert config["labels"] == ["ops", "platform"]
    assert config["max_issues"] == 9
    assert config["comment_issue_number"] == 41
    assert config["reopen_closed_issues"] is False
    assert config["sources"]["review_mode"] == "repo_config"
    assert config["sources"]["labels"] == "workflow_input"


def test_labels_and_lists_normalize_from_strings(tmp_path: Path) -> None:
    config = build_effective_config(
        make_args(
            tmp_path,
            labels=" ai-review, maintenance ,triage ",
            paths="src tests,docs",
            ignored_paths="docs/generated, notebooks",
            ignored_categories="style, documentation",
        )
    )

    assert config["labels"] == ["ai-review", "maintenance", "triage"]
    assert config["paths"] == ["src", "tests", "docs"]
    assert config["ignored_paths"] == ["docs/generated", "notebooks"]
    assert config["ignored_categories"] == ["style", "documentation"]


def test_invalid_config_values_fail_clearly(tmp_path: Path) -> None:
    config_dir = tmp_path / ".github"
    config_dir.mkdir()
    (config_dir / "repo-review.yml").write_text("comment_mode: noisy\n", encoding="utf-8")

    with pytest.raises(ValueError, match="comment_mode"):
        build_effective_config(make_args(tmp_path))


def test_unknown_config_keys_fail(tmp_path: Path) -> None:
    config_dir = tmp_path / ".github"
    config_dir.mkdir()
    (config_dir / "repo-review.yml").write_text("unexpected: true\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported config keys"):
        build_effective_config(make_args(tmp_path))

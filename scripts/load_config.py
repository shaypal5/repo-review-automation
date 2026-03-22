from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.helpers import dump_json, normalize_dedupe_mode
from scripts.parse_findings import require_known_severity

DEFAULT_CONFIG = {
    "review_mode": "full",
    "prompt_preset": "default",
    "min_severity": "medium",
    "max_issues": 5,
    "labels": ["ai-review"],
    "paths": ["."],
    "dedupe_mode": "title_hash",
    "issue_prefix": "[Repo Review]",
    "comment_mode": "off",
    "comment_issue_number": None,
    "reopen_closed_issues": False,
    "ignored_paths": [],
    "ignored_categories": [],
}

ALLOWED_KEYS = set(DEFAULT_CONFIG)
ALLOWED_REVIEW_MODES = {"full", "quick", "report_only"}
ALLOWED_COMMENT_MODES = {"off", "summary"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load optional repo-local review config and merge it with workflow inputs."
    )
    parser.add_argument("--repo-root", required=True, help="Caller repository root.")
    parser.add_argument(
        "--config-path",
        default=".github/repo-review.yml",
        help="Repo-local config path.",
    )
    parser.add_argument("--review-mode", default="", help="Explicit workflow input override.")
    parser.add_argument("--prompt-preset", default="", help="Explicit workflow input override.")
    parser.add_argument("--min-severity", default="", help="Explicit workflow input override.")
    parser.add_argument("--max-issues", default="", help="Explicit workflow input override.")
    parser.add_argument("--labels", default="", help="Explicit workflow input override.")
    parser.add_argument("--paths", default="", help="Explicit workflow input override.")
    parser.add_argument("--dedupe-mode", default="", help="Explicit workflow input override.")
    parser.add_argument("--issue-prefix", default="", help="Explicit workflow input override.")
    parser.add_argument("--comment-mode", default="", help="Explicit workflow input override.")
    parser.add_argument(
        "--comment-issue-number",
        default="",
        help="Explicit workflow input override.",
    )
    parser.add_argument(
        "--reopen-closed-issues",
        default="",
        help="Explicit workflow input override. Accepts true or false.",
    )
    parser.add_argument(
        "--ignored-paths",
        default="",
        help="Explicit workflow input override.",
    )
    parser.add_argument(
        "--ignored-categories",
        default="",
        help="Explicit workflow input override.",
    )
    parser.add_argument("--output", required=True, help="Effective config JSON output path.")
    return parser.parse_args()


def parse_yaml_config(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse config file {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file {path} must contain a top-level mapping.")
    unknown = sorted(set(loaded) - ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"Unsupported config keys in {path}: {', '.join(unknown)}")
    return loaded


def normalize_review_mode(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in ALLOWED_REVIEW_MODES:
        allowed = ", ".join(sorted(ALLOWED_REVIEW_MODES))
        raise ValueError(f"review_mode must be one of: {allowed}. Got: {value!r}")
    return normalized


def normalize_comment_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_COMMENT_MODES:
        allowed = ", ".join(sorted(ALLOWED_COMMENT_MODES))
        raise ValueError(f"comment_mode must be one of: {allowed}. Got: {value!r}")
    return normalized


def normalize_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be a boolean value. Got: {value!r}")


def normalize_max_issues(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"max_issues must be an integer-compatible value, got: {value!r}")
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"max_issues must be numeric, got: {value!r}") from exc
    if not numeric_value.is_integer() or int(numeric_value) <= 0:
        raise ValueError(f"max_issues must be a positive integer, got: {value!r}")
    return int(numeric_value)


def normalize_string_list(
    value: Any,
    *,
    field_name: str,
    split_mode: str = "comma",
) -> list[str]:
    raw_items: list[Any]
    if isinstance(value, str):
        if split_mode == "whitespace_or_comma":
            raw_items = [part for part in value.replace(",", " ").split() if part]
        else:
            raw_items = [part for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise ValueError(f"{field_name} must be a string or list. Got: {value!r}")

    normalized: list[str] = []
    for item in raw_items:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def normalize_categories(value: Any) -> list[str]:
    categories = normalize_string_list(value, field_name="ignored_categories", split_mode="comma")
    return [item.lower().replace(" ", "_") for item in categories]


def normalize_comment_issue_number(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool):
        raise ValueError(f"comment_issue_number must be an integer, got: {value!r}")
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"comment_issue_number must be numeric, got: {value!r}") from exc
    if not numeric_value.is_integer() or int(numeric_value) <= 0:
        raise ValueError(f"comment_issue_number must be a positive integer, got: {value!r}")
    return int(numeric_value)


def normalize_field(field_name: str, value: Any) -> Any:
    if field_name == "review_mode":
        return normalize_review_mode(str(value))
    if field_name == "prompt_preset":
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("prompt_preset must be a non-empty string.")
        return normalized
    if field_name == "min_severity":
        return require_known_severity(str(value), field_name="min_severity")
    if field_name == "max_issues":
        return normalize_max_issues(value)
    if field_name == "labels":
        return normalize_string_list(value, field_name="labels", split_mode="comma")
    if field_name == "paths":
        return normalize_string_list(value, field_name="paths", split_mode="whitespace_or_comma")
    if field_name == "dedupe_mode":
        return normalize_dedupe_mode(str(value))
    if field_name == "issue_prefix":
        return str(value).strip()
    if field_name == "comment_mode":
        return normalize_comment_mode(str(value))
    if field_name == "comment_issue_number":
        return normalize_comment_issue_number(value)
    if field_name == "reopen_closed_issues":
        return normalize_bool(value, field_name="reopen_closed_issues")
    if field_name == "ignored_paths":
        return normalize_string_list(value, field_name="ignored_paths", split_mode="comma")
    if field_name == "ignored_categories":
        return normalize_categories(value)
    raise ValueError(f"Unsupported config field: {field_name}")


def normalize_mapping(raw_mapping: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field_name, value in raw_mapping.items():
        normalized[field_name] = normalize_field(field_name, value)
    return normalized


def collect_input_overrides(args: argparse.Namespace) -> dict[str, Any]:
    raw_inputs = {
        "review_mode": args.review_mode,
        "prompt_preset": args.prompt_preset,
        "min_severity": args.min_severity,
        "max_issues": args.max_issues,
        "labels": args.labels,
        "paths": args.paths,
        "dedupe_mode": args.dedupe_mode,
        "issue_prefix": args.issue_prefix,
        "comment_mode": args.comment_mode,
        "comment_issue_number": args.comment_issue_number,
        "reopen_closed_issues": args.reopen_closed_issues,
        "ignored_paths": args.ignored_paths,
        "ignored_categories": args.ignored_categories,
    }
    overrides: dict[str, Any] = {}
    for field_name, raw_value in raw_inputs.items():
        if isinstance(raw_value, str) and raw_value == "":
            continue
        overrides[field_name] = raw_value
    return normalize_mapping(overrides)


def build_effective_config(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config_path).resolve()
    config_found = config_path.is_file()

    config_values = normalize_mapping(parse_yaml_config(config_path)) if config_found else {}
    input_values = collect_input_overrides(args)

    effective = dict(DEFAULT_CONFIG)
    effective.update(config_values)
    effective.update(input_values)

    return {
        **effective,
        "labels_csv": ",".join(effective["labels"]),
        "paths_arg": ",".join(effective["paths"]),
        "ignored_paths_csv": ",".join(effective["ignored_paths"]),
        "ignored_categories_csv": ",".join(effective["ignored_categories"]),
        "config_path": args.config_path,
        "config_found": config_found,
        "repo_root": str(repo_root),
        "sources": {
            field_name: (
                "workflow_input"
                if field_name in input_values
                else "repo_config"
                if field_name in config_values
                else "default"
            )
            for field_name in DEFAULT_CONFIG
        },
    }


def main() -> None:
    args = parse_args()
    effective = build_effective_config(args)
    dump_json(Path(args.output), effective)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.helpers import (
    compute_finding_fingerprint,
    dump_json,
    extract_fingerprint_marker,
    github_token_from_env,
    list_closed_issues,
    load_json,
    reopen_issue,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match deduped findings against closed issues and optionally reopen them."
    )
    parser.add_argument("--repo", required=True, help="owner/name GitHub repository identifier.")
    parser.add_argument("--input", required=True, help="Deduped findings JSON path.")
    parser.add_argument(
        "--reopen-closed-issues",
        required=True,
        choices=["true", "false"],
        help="Whether to reopen matching closed issues instead of creating new ones.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Findings that still need issue creation after closed-issue processing.",
    )
    parser.add_argument(
        "--reopened-output",
        required=True,
        help="Reopened issues JSON output path.",
    )
    return parser.parse_args()


def build_closed_fingerprint_index(issues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for issue in issues:
        fingerprint = extract_fingerprint_marker(issue.get("body"))
        if not fingerprint:
            continue
        index.setdefault(
            fingerprint,
            {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "url": issue.get("html_url"),
            },
        )
    return index


def process_closed_issue_matches(
    findings_payload: dict[str, Any],
    *,
    repo: str,
    reopen_closed_issues: bool,
    existing_closed_issues: list[dict[str, Any]] | None = None,
    session: requests.Session | None = None,
    token: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    findings = findings_payload.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("Findings payload must contain a findings list.")

    closed_index = build_closed_fingerprint_index(existing_closed_issues or [])
    remaining: list[dict[str, Any]] = []
    reopened: list[dict[str, Any]] = []
    seen_issue_numbers: set[int] = set()
    auth_token = token or github_token_from_env()

    for finding in findings:
        fingerprint = compute_finding_fingerprint(finding)
        match = closed_index.get(fingerprint)
        if not match or not reopen_closed_issues:
            remaining.append(finding)
            continue

        issue_number = int(match["number"])
        if issue_number in seen_issue_numbers:
            continue
        seen_issue_numbers.add(issue_number)
        response = reopen_issue(repo, token=auth_token, issue_number=issue_number, session=session)
        reopened.append(
            {
                "finding_title": finding.get("title"),
                "fingerprint": fingerprint,
                "number": response.get("number"),
                "title": response.get("title"),
                "url": response.get("html_url"),
            }
        )

    reopened_payload = {
        "repo": repo,
        "reopen_closed_issues": reopen_closed_issues,
        "reopened_count": len(reopened),
        "issues": reopened,
    }
    return {"findings": remaining}, reopened_payload


def main() -> None:
    args = parse_args()
    findings_payload = load_json(Path(args.input))
    reopen_enabled = args.reopen_closed_issues == "true"
    with requests.Session() as session:
        closed_issues = list_closed_issues(
            args.repo,
            token=github_token_from_env(),
            session=session,
        )
        remaining_payload, reopened_payload = process_closed_issue_matches(
            findings_payload,
            repo=args.repo,
            reopen_closed_issues=reopen_enabled,
            existing_closed_issues=closed_issues,
            session=session,
        )
    dump_json(Path(args.output), remaining_payload)
    dump_json(Path(args.reopened_output), reopened_payload)


if __name__ == "__main__":
    main()

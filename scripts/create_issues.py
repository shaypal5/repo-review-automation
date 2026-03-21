from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.helpers import (
    build_issue_body,
    compute_finding_fingerprint,
    create_issue,
    dump_json,
    format_issue_title,
    github_token_from_env,
    load_json,
    parse_labels,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create GitHub issues from deduped findings.")
    parser.add_argument("--repo", required=True, help="owner/name GitHub repository identifier.")
    parser.add_argument("--input", required=True, help="Deduped findings JSON path.")
    parser.add_argument("--labels", required=False, default="", help="Comma-separated labels.")
    parser.add_argument("--issue-prefix", required=False, default="", help="Issue title prefix.")
    parser.add_argument("--output", required=True, help="Created issues JSON output path.")
    return parser.parse_args()


def create_issues_for_findings(
    findings_payload: dict[str, Any],
    *,
    repo: str,
    labels_raw: str,
    issue_prefix: str,
    session: requests.Session | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    findings = findings_payload.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("Findings payload must contain a findings list.")

    labels = parse_labels(labels_raw)
    auth_token = token or github_token_from_env()
    created: list[dict[str, Any]] = []

    for finding in findings:
        fingerprint = compute_finding_fingerprint(finding)
        title = format_issue_title(issue_prefix, str(finding.get("title", "")))
        body = build_issue_body(finding, fingerprint=fingerprint)
        response = create_issue(
            repo,
            token=auth_token,
            title=title,
            body=body,
            labels=labels,
            session=session,
        )
        created.append(
            {
                "finding_title": finding.get("title"),
                "fingerprint": fingerprint,
                "issue_number": response.get("number"),
                "issue_title": response.get("title"),
                "issue_url": response.get("html_url"),
                "labels": labels,
            }
        )

    return {
        "repo": repo,
        "requested_count": len(findings),
        "created_count": len(created),
        "labels": labels,
        "issues": created,
    }


def main() -> None:
    args = parse_args()
    findings_payload = load_json(Path(args.input))
    with requests.Session() as session:
        payload = create_issues_for_findings(
            findings_payload,
            repo=args.repo,
            labels_raw=args.labels,
            issue_prefix=args.issue_prefix,
            session=session,
        )
    dump_json(Path(args.output), payload)


if __name__ == "__main__":
    main()

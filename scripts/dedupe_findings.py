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
    list_open_issues,
    load_json,
    normalize_dedupe_mode,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dedupe normalized findings against open issues.")
    parser.add_argument("--repo", required=True, help="owner/name GitHub repository identifier.")
    parser.add_argument("--input", required=True, help="Normalized findings JSON path.")
    parser.add_argument("--mode", required=True, help="Dedupe mode.")
    parser.add_argument("--output", required=True, help="Filtered findings JSON output path.")
    parser.add_argument("--report", required=True, help="Detailed dedupe report output path.")
    return parser.parse_args()


def build_existing_fingerprint_index(
    issues: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for issue in issues:
        fingerprint = extract_fingerprint_marker(issue.get("body"))
        if not fingerprint:
            continue
        index.setdefault(
            fingerprint,
            {
                "issue_number": issue.get("number"),
                "issue_title": issue.get("title"),
                "issue_url": issue.get("html_url"),
            },
        )
    return index


def dedupe_findings(
    findings_payload: dict[str, Any],
    *,
    mode: str,
    existing_issues: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_mode = normalize_dedupe_mode(mode)
    findings = findings_payload.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("Findings payload must contain a findings list.")

    existing_index = (
        build_existing_fingerprint_index(existing_issues or [])
        if normalized_mode != "off"
        else {}
    )

    kept_findings: list[dict[str, Any]] = []
    report_items: list[dict[str, Any]] = []

    for finding in findings:
        fingerprint = compute_finding_fingerprint(finding)
        duplicate = existing_index.get(fingerprint)
        if normalized_mode == "off":
            kept_findings.append(finding)
            report_items.append(
                {
                    "title": finding.get("title"),
                    "fingerprint": fingerprint,
                    "status": "kept",
                    "reason": "dedupe_disabled",
                    "duplicate_issue_number": None,
                    "duplicate_issue_title": None,
                    "duplicate_issue_url": None,
                }
            )
            continue

        if duplicate:
            report_items.append(
                {
                    "title": finding.get("title"),
                    "fingerprint": fingerprint,
                    "status": "skipped",
                    "reason": "duplicate_open_issue",
                    "duplicate_issue_number": duplicate["issue_number"],
                    "duplicate_issue_title": duplicate["issue_title"],
                    "duplicate_issue_url": duplicate["issue_url"],
                }
            )
            continue

        kept_findings.append(finding)
        report_items.append(
            {
                "title": finding.get("title"),
                "fingerprint": fingerprint,
                "status": "kept",
                "reason": "kept",
                "duplicate_issue_number": None,
                "duplicate_issue_title": None,
                "duplicate_issue_url": None,
            }
        )

    report = {
        "mode": normalized_mode,
        "total_findings": len(findings),
        "kept_count": len(kept_findings),
        "skipped_count": len(findings) - len(kept_findings),
        "findings": report_items,
    }
    return {"findings": kept_findings}, report


def main() -> None:
    args = parse_args()
    findings_payload = load_json(Path(args.input))
    mode = normalize_dedupe_mode(args.mode)
    existing_issues: list[dict[str, Any]] = []
    if mode != "off":
        token = github_token_from_env()
        with requests.Session() as session:
            existing_issues = list_open_issues(args.repo, token=token, session=session)
    deduped_payload, report = dedupe_findings(
        findings_payload,
        mode=mode,
        existing_issues=existing_issues,
    )
    dump_json(Path(args.output), deduped_payload)
    dump_json(Path(args.report), report)


if __name__ == "__main__":
    main()

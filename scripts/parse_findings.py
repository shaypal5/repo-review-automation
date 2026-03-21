from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.helpers import dump_json, load_json, read_text, write_text

SEVERITY_ORDER = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

SEVERITY_ALIASES = {
    "info": "low",
    "warning": "medium",
    "moderate": "medium",
    "sev1": "critical",
    "sev2": "high",
    "sev3": "medium",
    "sev4": "low",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and normalize AI findings.")
    parser.add_argument("--input", required=True, help="Raw findings JSON path.")
    parser.add_argument("--schema", required=True, help="JSON schema path.")
    parser.add_argument("--min-severity", required=True, help="Minimum severity to keep.")
    parser.add_argument("--max-issues", required=True, type=int, help="Max findings to keep.")
    parser.add_argument("--output", required=True, help="Normalized findings JSON path.")
    parser.add_argument("--summary", required=True, help="Markdown summary output path.")
    parser.add_argument(
        "--context",
        required=False,
        help="Optional review_context.json path for repository metadata in markdown output.",
    )
    return parser.parse_args()


def extract_json_payload(raw_text: str) -> Any:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


def normalize_severity(value: str) -> str:
    normalized = value.strip().lower()
    return SEVERITY_ALIASES.get(normalized, normalized)


def normalize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(finding)
    normalized["severity"] = normalize_severity(str(finding["severity"]))
    normalized["category"] = str(finding["category"]).strip().lower().replace(" ", "_")
    normalized["title"] = str(finding["title"]).strip()
    normalized["summary"] = str(finding["summary"]).strip()
    normalized["recommended_fix"] = str(finding["recommended_fix"]).strip()
    normalized["evidence"] = [
        str(item).strip() for item in finding["evidence"] if str(item).strip()
    ]
    normalized["confidence"] = round(float(finding["confidence"]), 2)
    if "proposed_issue_body" in finding and finding["proposed_issue_body"] is not None:
        normalized["proposed_issue_body"] = str(finding["proposed_issue_body"]).strip()
    return normalized


def validate_findings(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    jsonschema.validate(instance=payload, schema=schema)


def filter_findings(
    findings: list[dict[str, Any]], *, min_severity: str, max_issues: int
) -> list[dict[str, Any]]:
    threshold = SEVERITY_ORDER[normalize_severity(min_severity)]
    filtered = [item for item in findings if SEVERITY_ORDER[item["severity"]] >= threshold]
    filtered.sort(
        key=lambda item: (
            SEVERITY_ORDER[item["severity"]],
            item["confidence"],
            item["title"].lower(),
        ),
        reverse=True,
    )
    return filtered[:max_issues]


def render_summary(
    findings_payload: dict[str, Any], *, context: dict[str, Any] | None = None
) -> str:
    repo_name = None
    review_mode = None
    if context:
        repo = context.get("repo", {})
        repo_name = repo.get("name")
        review_mode = context.get("review_mode")

    lines = ["# Repository Review Summary", ""]
    if repo_name:
        lines.append(f"- Repository: `{repo_name}`")
    if review_mode:
        lines.append(f"- Review mode: `{review_mode}`")
    lines.append(f"- Findings count: `{len(findings_payload['findings'])}`")
    lines.append("")

    if findings_payload["findings"]:
        for index, finding in enumerate(findings_payload["findings"], start=1):
            lines.extend(
                [
                    f"## {index}. {finding['title']}",
                    "",
                    f"- Category: `{finding['category']}`",
                    f"- Severity: `{finding['severity']}`",
                    f"- Confidence: `{finding['confidence']:.2f}`",
                    "",
                    finding["summary"],
                    "",
                    "### Evidence",
                ]
            )
            lines.extend(f"- {item}" for item in finding["evidence"])
            lines.extend(
                [
                    "",
                    "### Suggested Improvement",
                    finding["recommended_fix"],
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "No findings met the configured severity threshold.",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def process_findings(
    raw_payload: dict[str, Any], schema: dict[str, Any], *, min_severity: str, max_issues: int
) -> dict[str, Any]:
    normalized_findings = [normalize_finding(item) for item in raw_payload["findings"]]
    normalized_payload = {
        "findings": filter_findings(
            normalized_findings,
            min_severity=min_severity,
            max_issues=max_issues,
        )
    }
    validate_findings(normalized_payload, schema)
    return normalized_payload


def main() -> None:
    args = parse_args()
    raw_payload = extract_json_payload(read_text(Path(args.input)))
    schema = load_json(Path(args.schema))
    if not isinstance(raw_payload, dict) or "findings" not in raw_payload:
        raise ValueError("Raw findings payload must be a JSON object containing a findings array.")
    processed = process_findings(
        raw_payload,
        schema,
        min_severity=args.min_severity,
        max_issues=args.max_issues,
    )
    context = load_json(Path(args.context)) if args.context else None
    dump_json(Path(args.output), processed)
    write_text(Path(args.summary), render_summary(processed, context=context))


if __name__ == "__main__":
    main()

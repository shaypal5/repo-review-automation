from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

GITHUB_API_ROOT = "https://api.github.com"
FINGERPRINT_MARKER_PREFIX = "<!-- repo-review-fingerprint: "
FINGERPRINT_MARKER_SUFFIX = " -->"
FINGERPRINT_MARKER_RE = re.compile(
    r"<!--\s*repo-review-fingerprint:\s*([0-9a-f]+)\s*-->",
    re.IGNORECASE,
)
DEFAULT_TIMEOUT = (10, 30)
SUPPORTED_DEDUPE_MODES = {"off", "title_hash", "fingerprint"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(read_text(path))


def dump_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def truncate_text(text: str, *, max_chars: int) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 15].rstrip() + "\n...[truncated]"


def read_optional_text(path: Path, *, max_chars: int) -> str:
    if not path.exists():
        return "Not collected."
    return truncate_text(read_text(path), max_chars=max_chars)


def normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_fingerprint_text(value: str) -> str:
    return normalize_whitespace(value).lower()


def parse_labels(raw_labels: str) -> list[str]:
    return [label.strip() for label in raw_labels.split(",") if label.strip()]


def normalize_dedupe_mode(mode: str) -> str:
    normalized = normalize_fingerprint_text(mode).replace("-", "_")
    if normalized not in SUPPORTED_DEDUPE_MODES:
        allowed = ", ".join(sorted(SUPPORTED_DEDUPE_MODES))
        raise ValueError(f"dedupe_mode must be one of: {allowed}. Got: {mode!r}")
    return normalized


def finding_fingerprint_payload(finding: dict[str, Any]) -> dict[str, str]:
    evidence = finding.get("evidence") or []
    primary_evidence = str(evidence[0]).strip() if evidence else ""
    return {
        "title": normalize_fingerprint_text(str(finding.get("title", ""))),
        "category": normalize_fingerprint_text(str(finding.get("category", ""))),
        "primary_evidence": normalize_fingerprint_text(primary_evidence),
        "recommended_fix": normalize_fingerprint_text(str(finding.get("recommended_fix", ""))),
    }


def compute_finding_fingerprint(finding: dict[str, Any]) -> str:
    payload = json.dumps(
        finding_fingerprint_payload(finding),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_fingerprint_marker(fingerprint: str) -> str:
    return f"{FINGERPRINT_MARKER_PREFIX}{fingerprint}{FINGERPRINT_MARKER_SUFFIX}"


def extract_fingerprint_marker(body: str | None) -> str | None:
    if not body:
        return None
    match = FINGERPRINT_MARKER_RE.search(body)
    if not match:
        return None
    return match.group(1).lower()


def format_issue_title(issue_prefix: str, finding_title: str) -> str:
    prefix = issue_prefix.strip()
    title = finding_title.strip()
    if prefix and title:
        return f"{prefix} {title}"
    return prefix or title


def _why_this_matters(finding: dict[str, Any]) -> str:
    severity = str(finding.get("severity", "")).strip().lower()
    category = str(finding.get("category", "")).strip().replace("_", " ")
    impact = {
        "critical": (
            "This is likely to cause severe correctness, availability, or security problems "
            "if it remains unresolved."
        ),
        "high": (
            "This is likely to cause meaningful correctness, reliability, or "
            "maintainability problems if it remains unresolved."
        ),
        "medium": (
            "This is likely to create recurring engineering drag or user-visible risk "
            "if it remains unresolved."
        ),
        "low": (
            "This is worth addressing to reduce future engineering friction or prevent "
            "smaller regressions."
        ),
    }.get(severity, "This is worth addressing based on the automated review signal.")
    if category:
        return f"{impact} Category: {category}."
    return impact


def build_issue_body(finding: dict[str, Any], *, fingerprint: str) -> str:
    summary = str(finding.get("summary", "")).strip()
    evidence = [
        f"- {str(item).strip()}" for item in finding.get("evidence", []) if str(item).strip()
    ]
    suggested_improvement = str(
        finding.get("proposed_issue_body") or finding.get("recommended_fix") or ""
    ).strip()
    lines = [
        "## Summary",
        summary,
        "",
        "## Why this matters",
        _why_this_matters(finding),
        "",
        "## Evidence",
    ]
    lines.extend(evidence or ["- No evidence provided."])
    lines.extend(
        [
            "",
            "## Suggested improvement",
            suggested_improvement,
            "",
            "## Confidence",
            f"{float(finding.get('confidence', 0.0)):.2f}",
            "",
            "## Source",
            "Automated weekly repository review.",
            "",
            render_fingerprint_marker(fingerprint),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def github_token_from_env() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for GitHub issue deduplication and creation.")
    return token


def github_request(
    method: str,
    path: str,
    *,
    token: str,
    session: requests.Session | None = None,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
) -> Any:
    client = session or requests.Session()
    owns_session = session is None
    url = f"{GITHUB_API_ROOT}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_payload,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise RuntimeError(f"GitHub API request failed for {method} {path}: {exc}") from exc

            if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                time.sleep(1)
                continue

            if response.status_code >= 400:
                detail = response.text.strip()
                raise RuntimeError(
                    f"GitHub API request failed for {method} {path}: "
                    f"status={response.status_code} body={detail}"
                )

            if response.status_code == 204 or not response.content:
                return None
            return response.json()

        raise RuntimeError(f"GitHub API request failed for {method} {path}: {last_error}")
    finally:
        if owns_session:
            client.close()


def list_open_issues(
    repo: str,
    *,
    token: str,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = github_request(
            "GET",
            f"/repos/{repo}/issues",
            token=token,
            session=session,
            params={"state": "open", "per_page": 100, "page": page},
        )
        if not isinstance(payload, list):
            raise RuntimeError(
                f"Expected a list when listing issues for {repo}, got: {type(payload)!r}"
            )
        page_items = [item for item in payload if "pull_request" not in item]
        issues.extend(page_items)
        if len(payload) < 100:
            break
        page += 1
    return issues


def create_issue(
    repo: str,
    *,
    token: str,
    title: str,
    body: str,
    labels: list[str],
    session: requests.Session | None = None,
) -> dict[str, Any]:
    payload = github_request(
        "POST",
        f"/repos/{repo}/issues",
        token=token,
        session=session,
        json_payload={"title": title, "body": body, "labels": labels},
    )
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Expected issue creation response to be an object, got: {type(payload)!r}"
        )
    return payload

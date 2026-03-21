from __future__ import annotations

from pathlib import Path

from scripts.dedupe_findings import dedupe_findings
from scripts.helpers import (
    compute_finding_fingerprint,
    extract_fingerprint_marker,
    load_json,
    normalize_dedupe_mode,
    render_fingerprint_marker,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_fingerprint_generation_is_stable() -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    finding = dict(payload["findings"][0])
    baseline = compute_finding_fingerprint(finding)

    finding["title"] = "  github api calls do not retry transient failures  "
    finding["category"] = "Reliability"
    finding["evidence"] = [" scripts/run_ai_review.py "]
    finding["recommended_fix"] = (
        "Wrap external API calls with explicit timeout handling and a small retry budget "
        "for transient failures."
    )

    assert compute_finding_fingerprint(finding) == baseline


def test_marker_extraction_reads_hidden_fingerprint() -> None:
    marker = render_fingerprint_marker("abc123")
    body = f"## Summary\nExample\n\n{marker}\n"
    assert extract_fingerprint_marker(body) == "abc123"


def test_dedupe_skips_matching_open_issue() -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    existing_issues = load_json(FIXTURES / "existing_issues.json")
    fingerprint = compute_finding_fingerprint(payload["findings"][0])
    existing_issues[0]["body"] = existing_issues[0]["body"].replace("__FINGERPRINT__", fingerprint)

    deduped_payload, report = dedupe_findings(
        payload,
        mode="fingerprint",
        existing_issues=existing_issues,
    )

    assert [finding["title"] for finding in deduped_payload["findings"]] == [
        "Issue creation labels are not validated consistently"
    ]
    assert report["skipped_count"] == 1
    assert report["findings"][0]["reason"] == "duplicate_open_issue"
    assert report["findings"][0]["duplicate_issue_number"] == 17


def test_off_mode_keeps_all_findings() -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    deduped_payload, report = dedupe_findings(payload, mode="off", existing_issues=[])

    assert len(deduped_payload["findings"]) == len(payload["findings"])
    assert {item["reason"] for item in report["findings"]} == {"dedupe_disabled"}


def test_dedupe_report_marks_kept_findings() -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    deduped_payload, report = dedupe_findings(payload, mode="title_hash", existing_issues=[])

    assert len(deduped_payload["findings"]) == 2
    assert report["kept_count"] == 2
    assert all(item["status"] == "kept" for item in report["findings"])
    assert normalize_dedupe_mode(report["mode"]) == "title_hash"

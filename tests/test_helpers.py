from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from scripts.helpers import (
    SUMMARY_COMMENT_MARKER,
    build_issue_body,
    compute_finding_fingerprint,
    extract_fingerprint_marker,
    finding_fingerprint_payload,
    format_issue_title,
    github_request,
    github_token_from_env,
    list_issues,
    normalize_dedupe_mode,
    normalize_fingerprint_text,
    normalize_whitespace,
    parse_labels,
    read_optional_text,
    read_text,
    render_fingerprint_marker,
    truncate_text,
    write_text,
)


# ---------------------------------------------------------------------------
# read_text / write_text
# ---------------------------------------------------------------------------


def test_write_and_read_text_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "file.txt"
    write_text(target, "hello world")
    assert read_text(target) == "hello world"


def test_write_text_creates_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    write_text(target, "content")
    assert target.exists()


# ---------------------------------------------------------------------------
# truncate_text
# ---------------------------------------------------------------------------


def test_truncate_text_short_text_is_unchanged() -> None:
    assert truncate_text("hello", max_chars=100) == "hello"


def test_truncate_text_exact_limit_is_unchanged() -> None:
    text = "x" * 100
    assert truncate_text(text, max_chars=100) == text


def test_truncate_text_long_text_gets_truncated() -> None:
    text = "a" * 200
    result = truncate_text(text, max_chars=50)
    assert result.endswith("...[truncated]")
    assert len(result) == 50


def test_truncate_text_strips_whitespace_before_comparing() -> None:
    text = "  short  "
    assert truncate_text(text, max_chars=100) == "short"


# ---------------------------------------------------------------------------
# read_optional_text
# ---------------------------------------------------------------------------


def test_read_optional_text_missing_file_returns_sentinel(tmp_path: Path) -> None:
    result = read_optional_text(tmp_path / "missing.txt", max_chars=1000)
    assert result == "Not collected."


def test_read_optional_text_existing_file_returns_content(tmp_path: Path) -> None:
    f = tmp_path / "present.txt"
    f.write_text("some content", encoding="utf-8")
    assert read_optional_text(f, max_chars=1000) == "some content"


def test_read_optional_text_truncates_large_files(tmp_path: Path) -> None:
    f = tmp_path / "big.txt"
    f.write_text("z" * 500, encoding="utf-8")
    result = read_optional_text(f, max_chars=100)
    assert result.endswith("...[truncated]")


# ---------------------------------------------------------------------------
# normalize_whitespace / normalize_fingerprint_text
# ---------------------------------------------------------------------------


def test_normalize_whitespace_collapses_internal_spaces() -> None:
    assert normalize_whitespace("  hello   world  ") == "hello world"


def test_normalize_fingerprint_text_lowercases() -> None:
    assert normalize_fingerprint_text("Hello World") == "hello world"


# ---------------------------------------------------------------------------
# finding_fingerprint_payload
# ---------------------------------------------------------------------------


def test_finding_fingerprint_payload_uses_first_evidence_item() -> None:
    finding = {
        "title": "Test Title",
        "category": "reliability",
        "evidence": [" evidence-one ", "evidence-two"],
        "recommended_fix": "Fix it now.",
    }
    payload = finding_fingerprint_payload(finding)
    assert payload["primary_evidence"] == "evidence-one"


def test_finding_fingerprint_payload_empty_evidence_uses_empty_string() -> None:
    finding = {
        "title": "Title",
        "category": "testing",
        "evidence": [],
        "recommended_fix": "Add tests.",
    }
    payload = finding_fingerprint_payload(finding)
    assert payload["primary_evidence"] == ""


# ---------------------------------------------------------------------------
# compute_finding_fingerprint
# ---------------------------------------------------------------------------


def test_compute_finding_fingerprint_is_deterministic() -> None:
    finding = {
        "title": "Some Issue",
        "category": "reliability",
        "evidence": ["path/to/file.py"],
        "recommended_fix": "Fix the thing appropriately.",
    }
    fp1 = compute_finding_fingerprint(finding)
    fp2 = compute_finding_fingerprint(finding)
    assert fp1 == fp2


def test_compute_finding_fingerprint_changes_with_different_title() -> None:
    base = {
        "title": "Issue A",
        "category": "reliability",
        "evidence": ["src/foo.py"],
        "recommended_fix": "Resolve it.",
    }
    other = {**base, "title": "Issue B"}
    assert compute_finding_fingerprint(base) != compute_finding_fingerprint(other)


# ---------------------------------------------------------------------------
# render_fingerprint_marker / extract_fingerprint_marker
# ---------------------------------------------------------------------------


def test_render_and_extract_fingerprint_marker_round_trip() -> None:
    marker = render_fingerprint_marker("deadbeef")
    assert extract_fingerprint_marker(f"Some text\n{marker}") == "deadbeef"


def test_extract_fingerprint_marker_returns_none_when_absent() -> None:
    assert extract_fingerprint_marker("No marker here") is None


def test_extract_fingerprint_marker_returns_none_for_empty_body() -> None:
    assert extract_fingerprint_marker("") is None
    assert extract_fingerprint_marker(None) is None


# ---------------------------------------------------------------------------
# parse_labels
# ---------------------------------------------------------------------------


def test_parse_labels_splits_on_comma_and_strips() -> None:
    assert parse_labels(" ai-review , bug , triage ") == ["ai-review", "bug", "triage"]


def test_parse_labels_filters_empty_segments() -> None:
    assert parse_labels("a,,b,") == ["a", "b"]


# ---------------------------------------------------------------------------
# normalize_dedupe_mode
# ---------------------------------------------------------------------------


def test_normalize_dedupe_mode_accepts_valid_modes() -> None:
    assert normalize_dedupe_mode("off") == "off"
    assert normalize_dedupe_mode("title_hash") == "title_hash"
    assert normalize_dedupe_mode("fingerprint") == "fingerprint"


def test_normalize_dedupe_mode_normalizes_case_and_dashes() -> None:
    assert normalize_dedupe_mode("Title-Hash") == "title_hash"


def test_normalize_dedupe_mode_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="dedupe_mode must be one of"):
        normalize_dedupe_mode("unknown")


# ---------------------------------------------------------------------------
# format_issue_title
# ---------------------------------------------------------------------------


def test_format_issue_title_combines_prefix_and_title() -> None:
    assert format_issue_title("[Review]", "API is slow") == "[Review] API is slow"


def test_format_issue_title_empty_prefix_returns_title_only() -> None:
    assert format_issue_title("", "Title only") == "Title only"


def test_format_issue_title_empty_title_returns_prefix_only() -> None:
    assert format_issue_title("[Review]", "") == "[Review]"


# ---------------------------------------------------------------------------
# build_issue_body
# ---------------------------------------------------------------------------


def test_build_issue_body_contains_all_sections() -> None:
    finding = {
        "title": "Some Finding",
        "summary": "A short summary of the finding for verification.",
        "severity": "medium",
        "category": "reliability",
        "confidence": 0.85,
        "evidence": ["src/foo.py:42"],
        "recommended_fix": "Apply a fix to address this finding comprehensively.",
        "proposed_issue_body": "Apply a more detailed fix description here.",
    }
    body = build_issue_body(finding, fingerprint="abc123")

    assert "## Summary" in body
    assert "## Why this matters" in body
    assert "## Evidence" in body
    assert "## Suggested improvement" in body
    assert "## Confidence" in body
    assert "## Source" in body
    assert "<!-- repo-review-fingerprint: abc123 -->" in body


def test_build_issue_body_falls_back_to_recommended_fix_when_no_proposed_body() -> None:
    finding = {
        "summary": "A sufficiently long summary for this test case.",
        "severity": "low",
        "category": "style",
        "confidence": 0.5,
        "evidence": ["README.md"],
        "recommended_fix": "Update the readme with the correct information.",
    }
    body = build_issue_body(finding, fingerprint="xyz")
    assert "Update the readme with the correct information." in body


# ---------------------------------------------------------------------------
# github_token_from_env
# ---------------------------------------------------------------------------


def test_github_token_from_env_returns_token(monkeypatch: object) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "gh-test-token")
    assert github_token_from_env() == "gh-test-token"


def test_github_token_from_env_raises_when_missing(monkeypatch: object) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN is required"):
        github_token_from_env()


# ---------------------------------------------------------------------------
# github_request
# ---------------------------------------------------------------------------


def _make_mock_response(
    status_code: int,
    json_data: object | None = None,
    text: str = "",
    content: bytes = b"{}",
) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = text
    mock_resp.content = content
    mock_resp.json.return_value = json_data
    return mock_resp


def test_github_request_returns_json_on_success(monkeypatch: object) -> None:
    mock_session = MagicMock(spec=requests.Session)
    mock_session.request.return_value = _make_mock_response(
        200, json_data={"id": 1}, content=b'{"id":1}'
    )

    result = github_request(
        "GET",
        "/repos/owner/repo/issues",
        token="tok",
        session=mock_session,
    )

    assert result == {"id": 1}


def test_github_request_raises_on_client_error(monkeypatch: object) -> None:
    mock_session = MagicMock(spec=requests.Session)
    mock_session.request.return_value = _make_mock_response(
        404, text="Not Found", content=b"Not Found"
    )

    with pytest.raises(RuntimeError, match="GitHub API request failed"):
        github_request(
            "GET",
            "/repos/owner/repo/issues/99",
            token="tok",
            session=mock_session,
        )


def test_github_request_returns_none_on_204(monkeypatch: object) -> None:
    mock_session = MagicMock(spec=requests.Session)
    mock_session.request.return_value = _make_mock_response(204, content=b"")

    result = github_request(
        "DELETE",
        "/repos/owner/repo/issues/1/labels/x",
        token="tok",
        session=mock_session,
    )

    assert result is None


# ---------------------------------------------------------------------------
# list_issues
# ---------------------------------------------------------------------------


def test_list_issues_validates_invalid_state() -> None:
    with pytest.raises(ValueError, match="state must be one of"):
        list_issues("owner/repo", state="unknown", token="tok")


def test_list_issues_filters_pull_requests(monkeypatch: object) -> None:
    issue = {"number": 1, "title": "Issue"}
    pr = {"number": 2, "title": "PR", "pull_request": {}}

    mock_session = MagicMock(spec=requests.Session)
    mock_session.request.return_value = _make_mock_response(
        200,
        json_data=[issue, pr],
        content=b"[...]",
    )

    result = list_issues("owner/repo", state="open", token="tok", session=mock_session)

    assert result == [issue]


# ---------------------------------------------------------------------------
# SUMMARY_COMMENT_MARKER constant
# ---------------------------------------------------------------------------


def test_summary_comment_marker_is_html_comment() -> None:
    assert SUMMARY_COMMENT_MARKER.startswith("<!--")
    assert SUMMARY_COMMENT_MARKER.endswith("-->")

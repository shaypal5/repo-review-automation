from __future__ import annotations

from pathlib import Path

from scripts.helpers import SUMMARY_COMMENT_MARKER, load_json
from scripts.post_summary_comment import (
    build_skipped_result,
    post_or_update_comment,
    render_summary_comment,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_summary_markdown_contains_expected_sections() -> None:
    findings = load_json(FIXTURES / "valid_findings.json")
    dedupe_report = {
        "findings": [
            {"reason": "duplicate_open_issue"},
            {"reason": "kept"},
        ]
    }
    created_issues = {"created_count": 2}
    reopened_issues = {"reopened_count": 1}

    summary = render_summary_comment(
        repo="example/repo",
        review_mode="full",
        findings_payload=findings,
        dedupe_report=dedupe_report,
        created_issues=created_issues,
        reopened_issues=reopened_issues,
    )

    assert SUMMARY_COMMENT_MARKER in summary
    assert "- Findings count: `3`" in summary
    assert "- Skipped as duplicate open issues: `1`" in summary
    assert "- Reopened issues: `1`" in summary
    assert "- Newly created issues: `2`" in summary
    assert "**Compile failures can hide syntax regressions**" in summary


def test_post_summary_comment_updates_existing_marker_comment(monkeypatch: object) -> None:
    captured: list[dict[str, object]] = []

    def fake_list_issue_comments(
        repo: str,
        *,
        issue_number: int,
        token: str,
        session: object | None = None,
    ) -> list[dict[str, object]]:
        return [{"id": 7, "body": f"{SUMMARY_COMMENT_MARKER}\nOld"}]

    def fake_update_issue_comment(
        repo: str,
        *,
        comment_id: int,
        token: str,
        body: str,
        session: object | None = None,
    ) -> dict[str, object]:
        captured.append({"repo": repo, "comment_id": comment_id, "body": body})
        return {"id": comment_id, "html_url": "https://github.com/example/repo/issues/9#issuecomment-7"}

    monkeypatch.setattr(
        "scripts.post_summary_comment.list_issue_comments",
        fake_list_issue_comments,
    )
    monkeypatch.setattr(
        "scripts.post_summary_comment.update_issue_comment",
        fake_update_issue_comment,
    )

    result = post_or_update_comment(
        repo="example/repo",
        issue_number=9,
        body=f"{SUMMARY_COMMENT_MARKER}\nNew",
        token="test-token",
    )

    assert captured == [
        {
            "repo": "example/repo",
            "comment_id": 7,
            "body": f"{SUMMARY_COMMENT_MARKER}\nNew",
        }
    ]
    assert result["posted"] is True
    assert result["action"] == "updated"


def test_no_post_behavior_without_comment_target() -> None:
    result = build_skipped_result(issue_number=None, reason="comment_issue_number_not_configured")

    assert result == {
        "posted": False,
        "action": "skipped",
        "comment_id": None,
        "comment_url": None,
        "comment_issue_number": None,
        "reason": "comment_issue_number_not_configured",
    }

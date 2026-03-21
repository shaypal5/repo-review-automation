from __future__ import annotations

from pathlib import Path

from scripts.create_issues import create_issues_for_findings
from scripts.helpers import (
    build_issue_body,
    compute_finding_fingerprint,
    format_issue_title,
    load_json,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_labels_parsing_and_created_payload(monkeypatch: object) -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    captured_calls: list[dict[str, object]] = []

    def fake_create_issue(
        repo: str,
        *,
        token: str,
        title: str,
        body: str,
        labels: list[str],
        session: object | None = None,
    ) -> dict[str, object]:
        captured_calls.append(
            {
                "repo": repo,
                "token": token,
                "title": title,
                "body": body,
                "labels": labels,
            }
        )
        issue_number = len(captured_calls)
        return {
            "number": issue_number,
            "title": title,
            "html_url": f"https://github.com/example/repo/issues/{issue_number}",
        }

    monkeypatch.setattr("scripts.create_issues.create_issue", fake_create_issue)

    created = create_issues_for_findings(
        payload,
        repo="example/repo",
        labels_raw=" ai-review, bug , ,triage ",
        issue_prefix="[Repo Review]",
        token="test-token",
    )

    assert created["created_count"] == 2
    assert created["labels"] == ["ai-review", "bug", "triage"]
    assert captured_calls[0]["labels"] == ["ai-review", "bug", "triage"]
    assert created["issues"][0]["issue_number"] == 1


def test_issue_title_formatting_with_prefix() -> None:
    assert (
        format_issue_title("[Repo Review]", "GitHub API calls do not retry transient failures")
        == "[Repo Review] GitHub API calls do not retry transient failures"
    )
    assert format_issue_title(" ", "Plain title") == "Plain title"


def test_issue_body_contains_hidden_fingerprint_marker() -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    finding = payload["findings"][0]
    fingerprint = compute_finding_fingerprint(finding)
    body = build_issue_body(finding, fingerprint=fingerprint)

    assert "## Summary" in body
    assert "## Suggested improvement" in body
    assert f"<!-- repo-review-fingerprint: {fingerprint} -->" in body


def test_created_issues_payload_shape(monkeypatch: object) -> None:
    payload = {"findings": [load_json(FIXTURES / "findings_deduped_input.json")["findings"][0]]}

    def fake_create_issue(
        repo: str,
        *,
        token: str,
        title: str,
        body: str,
        labels: list[str],
        session: object | None = None,
    ) -> dict[str, object]:
        return {
            "number": 42,
            "title": title,
            "html_url": "https://github.com/example/repo/issues/42",
        }

    monkeypatch.setattr("scripts.create_issues.create_issue", fake_create_issue)

    created = create_issues_for_findings(
        payload,
        repo="example/repo",
        labels_raw="ai-review",
        issue_prefix="[Repo Review]",
        token="test-token",
    )

    assert created == {
        "repo": "example/repo",
        "requested_count": 1,
        "created_count": 1,
        "labels": ["ai-review"],
        "issues": [
            {
                "finding_title": "GitHub API calls do not retry transient failures",
                "fingerprint": compute_finding_fingerprint(payload["findings"][0]),
                "issue_number": 42,
                "issue_title": "[Repo Review] GitHub API calls do not retry transient failures",
                "issue_url": "https://github.com/example/repo/issues/42",
                "labels": ["ai-review"],
            }
        ],
    }

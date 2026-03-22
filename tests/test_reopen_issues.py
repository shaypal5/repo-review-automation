from __future__ import annotations

from pathlib import Path

from scripts.helpers import compute_finding_fingerprint, load_json
from scripts.reopen_issues import process_closed_issue_matches

FIXTURES = Path(__file__).parent / "fixtures"


def test_closed_issue_with_matching_fingerprint_is_detected_and_reopened(
    monkeypatch: object,
) -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    closed_issues = load_json(FIXTURES / "closed_issues.json")
    fingerprint = compute_finding_fingerprint(payload["findings"][0])
    closed_issues[0]["body"] = closed_issues[0]["body"].replace("__FINGERPRINT__", fingerprint)
    captured_issue_numbers: list[int] = []

    def fake_reopen_issue(
        repo: str,
        *,
        token: str,
        issue_number: int,
        session: object | None = None,
    ) -> dict[str, object]:
        captured_issue_numbers.append(issue_number)
        return {
            "number": issue_number,
            "title": closed_issues[0]["title"],
            "html_url": closed_issues[0]["html_url"],
        }

    monkeypatch.setattr("scripts.reopen_issues.reopen_issue", fake_reopen_issue)

    actionable, reopened = process_closed_issue_matches(
        payload,
        repo="example/repo",
        reopen_closed_issues=True,
        existing_closed_issues=closed_issues,
        token="test-token",
    )

    assert captured_issue_numbers == [12]
    assert [finding["title"] for finding in actionable["findings"]] == [
        "Issue creation labels are not validated consistently"
    ]
    assert reopened["reopened_count"] == 1
    assert reopened["issues"][0]["number"] == 12
    assert reopened["issues"][0]["fingerprint"] == fingerprint


def test_reopen_disabled_leaves_matching_finding_for_new_issue_creation() -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    closed_issues = load_json(FIXTURES / "closed_issues.json")
    fingerprint = compute_finding_fingerprint(payload["findings"][0])
    closed_issues[0]["body"] = closed_issues[0]["body"].replace("__FINGERPRINT__", fingerprint)

    actionable, reopened = process_closed_issue_matches(
        payload,
        repo="example/repo",
        reopen_closed_issues=False,
        existing_closed_issues=closed_issues,
        token="test-token",
    )

    assert len(actionable["findings"]) == 2
    assert reopened["reopened_count"] == 0
    assert reopened["issues"] == []


def test_open_issues_are_not_treated_as_reopen_candidates(monkeypatch: object) -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")
    open_like_issue = [
        {
            "number": 55,
            "title": "Looks open but is passed as a closed-issue list item",
            "html_url": "https://github.com/example/repo/issues/55",
            "body": "No fingerprint marker",
        }
    ]

    def fail_reopen_issue(**_: object) -> dict[str, object]:
        raise AssertionError("reopen_issue should not be called for unmatched closed issues")

    monkeypatch.setattr("scripts.reopen_issues.reopen_issue", fail_reopen_issue)

    actionable, reopened = process_closed_issue_matches(
        payload,
        repo="example/repo",
        reopen_closed_issues=True,
        existing_closed_issues=open_like_issue,
        token="test-token",
    )

    assert len(actionable["findings"]) == 2
    assert reopened == {
        "repo": "example/repo",
        "reopen_closed_issues": True,
        "reopened_count": 0,
        "issues": [],
    }


def test_reopen_disabled_does_not_require_token(monkeypatch: object) -> None:
    payload = load_json(FIXTURES / "findings_deduped_input.json")

    def fail_github_token_from_env() -> str:
        raise AssertionError("github_token_from_env should not be called when reopen is disabled")

    monkeypatch.setattr(
        "scripts.reopen_issues.github_token_from_env",
        fail_github_token_from_env,
    )

    actionable, reopened = process_closed_issue_matches(
        payload,
        repo="example/repo",
        reopen_closed_issues=False,
        existing_closed_issues=[],
        token=None,
    )

    assert len(actionable["findings"]) == len(payload["findings"])
    assert reopened["reopened_count"] == 0

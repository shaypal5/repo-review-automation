from __future__ import annotations

from pathlib import Path

import pytest

from scripts.helpers import load_json
from scripts.parse_findings import process_findings, render_summary

FIXTURES = Path(__file__).parent / "fixtures"


def test_valid_findings_pass() -> None:
    payload = load_json(FIXTURES / "valid_findings.json")
    schema = load_json(Path("schemas/findings.schema.json"))
    processed = process_findings(payload, schema, min_severity="low", max_issues=5)
    assert len(processed["findings"]) == 3
    assert processed["findings"][0]["severity"] == "high"


def test_invalid_findings_fail() -> None:
    payload = load_json(FIXTURES / "invalid_findings.json")
    schema = load_json(Path("schemas/findings.schema.json"))
    with pytest.raises(ValueError, match="finding severity"):
        process_findings(payload, schema, min_severity="low", max_issues=5)


def test_invalid_min_severity_fails() -> None:
    payload = load_json(FIXTURES / "valid_findings.json")
    schema = load_json(Path("schemas/findings.schema.json"))
    with pytest.raises(ValueError, match="min_severity"):
        process_findings(payload, schema, min_severity="urgent", max_issues=5)


def test_severity_filtering_works() -> None:
    payload = load_json(FIXTURES / "valid_findings.json")
    schema = load_json(Path("schemas/findings.schema.json"))
    processed = process_findings(payload, schema, min_severity="high", max_issues=5)
    assert [item["severity"] for item in processed["findings"]] == ["high"]


def test_max_findings_cap_works() -> None:
    payload = load_json(FIXTURES / "valid_findings.json")
    schema = load_json(Path("schemas/findings.schema.json"))
    processed = process_findings(payload, schema, min_severity="low", max_issues=2)
    assert len(processed["findings"]) == 2


def test_ignored_categories_are_filtered() -> None:
    payload = load_json(FIXTURES / "valid_findings.json")
    schema = load_json(Path("schemas/findings.schema.json"))
    processed = process_findings(
        payload,
        schema,
        min_severity="low",
        max_issues=5,
        ignored_categories={"maintainability"},
    )
    assert {item["category"] for item in processed["findings"]} == {
        "reliability",
        "developer_experience",
    }


def test_ignored_paths_filter_only_when_all_evidence_paths_match() -> None:
    payload = {
        "findings": [
            {
                "title": "Generated docs drift",
                "summary": "Generated docs keep drifting from source changes.",
                "severity": "medium",
                "category": "documentation",
                "confidence": 0.9,
                "evidence": ["docs/generated/api.md", "docs/generated/schema.md:14"],
                "recommended_fix": "Regenerate docs in CI.",
            },
            {
                "title": "Mixed evidence remains actionable",
                "summary": "One evidence path is ignored but another is not.",
                "severity": "medium",
                "category": "automation",
                "confidence": 0.8,
                "evidence": ["docs/generated/api.md", "src/service.py:44"],
                "recommended_fix": "Handle both sources explicitly.",
            },
        ]
    }
    schema = load_json(Path("schemas/findings.schema.json"))

    processed = process_findings(
        payload,
        schema,
        min_severity="low",
        max_issues=5,
        ignored_paths=["docs/generated"],
    )

    assert [item["title"] for item in processed["findings"]] == [
        "Mixed evidence remains actionable"
    ]


def test_ignored_paths_match_root_level_repo_relative_evidence() -> None:
    payload = {
        "findings": [
            {
                "title": "Root level file should be ignored",
                "summary": "A root-level file path should participate in ignored path filtering.",
                "severity": "medium",
                "category": "documentation",
                "confidence": 0.9,
                "evidence": ["README.md:12"],
                "recommended_fix": "Update the root-level README generation flow.",
            }
        ]
    }
    schema = load_json(Path("schemas/findings.schema.json"))

    processed = process_findings(
        payload,
        schema,
        min_severity="low",
        max_issues=5,
        ignored_paths=["README.md"],
    )

    assert processed["findings"] == []


def test_markdown_summary_has_expected_sections() -> None:
    payload = load_json(FIXTURES / "valid_findings.json")
    schema = load_json(Path("schemas/findings.schema.json"))
    context = load_json(FIXTURES / "review_context.json")
    processed = process_findings(payload, schema, min_severity="medium", max_issues=5)
    summary = render_summary(processed, context=context)
    assert "# Repository Review Summary" in summary
    assert "Repository: `example-repo`" in summary
    assert "## 1. Compile failures can hide syntax regressions" in summary
    assert "### Evidence" in summary
    assert "### Suggested Improvement" in summary

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
    with pytest.raises(Exception):
        process_findings(payload, schema, min_severity="low", max_issues=5)


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

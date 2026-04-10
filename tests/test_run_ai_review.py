from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from scripts.run_ai_review import (
    build_messages,
    build_schema,
    format_openai_error,
    load_json_payload,
    load_user_message,
)

# ---------------------------------------------------------------------------
# build_schema
# ---------------------------------------------------------------------------


def test_build_schema_has_findings_property() -> None:
    schema = build_schema()
    assert schema["name"] == "repo_review_findings"
    assert schema["strict"] is True
    assert "findings" in schema["schema"]["properties"]


def test_build_schema_findings_items_have_required_fields() -> None:
    schema = build_schema()
    items = schema["schema"]["properties"]["findings"]["items"]
    required_fields = {
        "title",
        "category",
        "severity",
        "confidence",
        "summary",
        "evidence",
        "recommended_fix",
        "proposed_issue_body",
    }
    assert set(items["required"]) == required_fields


def test_build_schema_severity_enum_contains_expected_values() -> None:
    schema = build_schema()
    severity_enum = schema["schema"]["properties"]["findings"]["items"]["properties"]["severity"][
        "enum"
    ]
    assert set(severity_enum) == {"low", "medium", "high", "critical"}


def test_build_schema_additional_properties_disallowed() -> None:
    schema = build_schema()
    assert schema["schema"]["additionalProperties"] is False
    items = schema["schema"]["properties"]["findings"]["items"]
    assert items["additionalProperties"] is False


# ---------------------------------------------------------------------------
# load_user_message
# ---------------------------------------------------------------------------


def test_load_user_message_includes_serialized_context() -> None:
    context = {"repo": "example/repo", "max_issues": 3}
    message = load_user_message(context)
    assert json.dumps(context, indent=2) in message


def test_load_user_message_is_a_string() -> None:
    assert isinstance(load_user_message({}), str)


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------


def test_build_messages_returns_two_messages() -> None:
    messages = build_messages("Review this repo.", {"max_issues": 5})
    assert len(messages) == 2


def test_build_messages_system_role_contains_prompt() -> None:
    messages = build_messages("My prompt text.", {"max_issues": 5})
    system_msg = next(m for m in messages if m["role"] == "system")
    assert "My prompt text." in system_msg["content"]


def test_build_messages_system_role_contains_max_issues() -> None:
    messages = build_messages("Prompt.", {"max_issues": 7})
    system_msg = next(m for m in messages if m["role"] == "system")
    assert "Return at most 7 findings" in system_msg["content"]


def test_build_messages_user_role_contains_context_json() -> None:
    context = {"repo": "test/repo", "max_issues": 2}
    messages = build_messages("Prompt.", context)
    user_msg = next(m for m in messages if m["role"] == "user")
    assert json.dumps(context, indent=2) in user_msg["content"]


def test_build_messages_has_system_and_user_roles() -> None:
    messages = build_messages("Prompt.", {"max_issues": 1})
    roles = {m["role"] for m in messages}
    assert roles == {"system", "user"}


# ---------------------------------------------------------------------------
# format_openai_error
# ---------------------------------------------------------------------------


def _make_response(status_code: int, body: str | bytes) -> MagicMock:
    mock = MagicMock(spec=requests.Response)
    mock.status_code = status_code
    if isinstance(body, bytes):
        text = body.decode("utf-8")
    else:
        text = body
    mock.text = text
    mock.json.return_value = json.loads(text) if text else {}
    return mock


def test_format_openai_error_parses_error_object() -> None:
    body = json.dumps({"error": {"message": "invalid key", "type": "auth_error", "code": "401"}})
    resp = _make_response(401, body)
    result = format_openai_error(resp)
    assert "message=invalid key" in result
    assert "type=auth_error" in result


def test_format_openai_error_falls_back_to_json_dump_when_no_error_key() -> None:
    body = json.dumps({"status": "bad"})
    resp = _make_response(500, body)
    result = format_openai_error(resp)
    assert "status" in result


def test_format_openai_error_falls_back_to_text_on_invalid_json() -> None:
    mock = MagicMock(spec=requests.Response)
    mock.text = "Internal Server Error"
    mock.json.side_effect = ValueError("no json")
    result = format_openai_error(mock)
    assert result == "Internal Server Error"


def test_format_openai_error_returns_sentinel_for_empty_body() -> None:
    mock = MagicMock(spec=requests.Response)
    mock.text = ""
    mock.json.side_effect = ValueError("no json")
    result = format_openai_error(mock)
    assert result == "<empty response body>"


# ---------------------------------------------------------------------------
# load_json_payload
# ---------------------------------------------------------------------------


def test_load_json_payload_parses_valid_json_string() -> None:
    content = json.dumps({"findings": []})
    result = load_json_payload(content)
    assert result == {"findings": []}


def test_load_json_payload_raises_on_invalid_json() -> None:
    with pytest.raises((json.JSONDecodeError, ValueError)):
        load_json_payload("not valid json {")

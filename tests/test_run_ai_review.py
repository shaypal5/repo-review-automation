from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.run_ai_review import (
    ANTHROPIC_URL,
    GEMINI_URL_TEMPLATE,
    OPENAI_URL,
    _format_anthropic_error,
    _format_gemini_error,
    build_messages,
    build_schema,
    call_anthropic,
    call_gemini,
    call_openai,
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


# ---------------------------------------------------------------------------
# call_openai with custom url (openai_compatible)
# ---------------------------------------------------------------------------


def _make_openai_success_response(findings: dict) -> MagicMock:
    mock = MagicMock(spec=requests.Response)
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "choices": [{"message": {"content": json.dumps(findings)}}]
    }
    return mock


def test_call_openai_uses_default_openai_url() -> None:
    findings = {"findings": []}
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_openai_success_response(findings)
        result = call_openai(api_key="test-key", model="gpt-4.1-mini", messages=messages)
    assert mock_post.call_args[0][0] == OPENAI_URL
    assert result == findings


def test_call_openai_uses_custom_url_for_compatible_endpoint() -> None:
    custom_url = "https://my-endpoint.example.com/v1/chat/completions"
    findings = {"findings": []}
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_openai_success_response(findings)
        result = call_openai(
            api_key="test-key", model="custom-model", messages=messages, url=custom_url
        )
    assert mock_post.call_args[0][0] == custom_url
    assert result == findings


def test_call_openai_raises_runtime_error_on_401() -> None:
    messages = [{"role": "user", "content": "hello"}]
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 401
    mock_resp.text = '{"error": {"message": "Unauthorized"}}'
    mock_resp.json.return_value = {"error": {"message": "Unauthorized"}}
    http_err = requests.HTTPError(response=mock_resp)
    mock_resp.raise_for_status.side_effect = http_err

    with patch("scripts.run_ai_review.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="401"):
            call_openai(api_key="bad-key", model="gpt-4", messages=messages)


def test_call_openai_raises_runtime_error_on_500() -> None:
    messages = [{"role": "user", "content": "hello"}]
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_resp.json.side_effect = ValueError("no json")
    http_err = requests.HTTPError(response=mock_resp)
    mock_resp.raise_for_status.side_effect = http_err

    with patch("scripts.run_ai_review.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="500"):
            call_openai(api_key="key", model="gpt-4", messages=messages)


# ---------------------------------------------------------------------------
# _format_anthropic_error
# ---------------------------------------------------------------------------


def test_format_anthropic_error_parses_error_object() -> None:
    body = json.dumps(
        {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}
    )
    mock = MagicMock(spec=requests.Response)
    mock.text = body
    mock.json.return_value = json.loads(body)
    result = _format_anthropic_error(mock)
    assert "message=bad key" in result
    assert "type=authentication_error" in result


def test_format_anthropic_error_falls_back_to_json_dump() -> None:
    body = json.dumps({"status": "error"})
    mock = MagicMock(spec=requests.Response)
    mock.text = body
    mock.json.return_value = json.loads(body)
    result = _format_anthropic_error(mock)
    assert "status" in result


def test_format_anthropic_error_falls_back_to_text_on_invalid_json() -> None:
    mock = MagicMock(spec=requests.Response)
    mock.text = "Service Unavailable"
    mock.json.side_effect = ValueError("no json")
    result = _format_anthropic_error(mock)
    assert result == "Service Unavailable"


def test_format_anthropic_error_returns_sentinel_for_empty_body() -> None:
    mock = MagicMock(spec=requests.Response)
    mock.text = ""
    mock.json.side_effect = ValueError("no json")
    result = _format_anthropic_error(mock)
    assert result == "<empty response body>"


# ---------------------------------------------------------------------------
# call_anthropic
# ---------------------------------------------------------------------------


def _make_anthropic_success_response(findings: dict) -> MagicMock:
    mock = MagicMock(spec=requests.Response)
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_findings",
                "input": findings,
            }
        ]
    }
    return mock


def test_call_anthropic_returns_findings_from_tool_use() -> None:
    findings = {"findings": []}
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_anthropic_success_response(findings)
        result = call_anthropic(
            api_key="test-key", model="claude-3-5-haiku-20241022", messages=messages
        )
    assert mock_post.call_args[0][0] == ANTHROPIC_URL
    assert result == findings


def test_call_anthropic_posts_to_correct_url() -> None:
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_anthropic_success_response({"findings": []})
        call_anthropic(api_key="key", model="claude-3-5-haiku-20241022", messages=messages)
    assert mock_post.call_args[0][0] == ANTHROPIC_URL


def test_call_anthropic_sends_x_api_key_header() -> None:
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_anthropic_success_response({"findings": []})
        call_anthropic(
            api_key="my-anthropic-key",
            model="claude-3-5-haiku-20241022",
            messages=messages,
        )
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["x-api-key"] == "my-anthropic-key"


def test_call_anthropic_separates_system_and_user_messages() -> None:
    messages = [
        {"role": "system", "content": "system instruction"},
        {"role": "user", "content": "user query"},
    ]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_anthropic_success_response({"findings": []})
        call_anthropic(api_key="key", model="claude-3-5-haiku-20241022", messages=messages)
    body = mock_post.call_args.kwargs["json"]
    assert body["system"] == "system instruction"
    user_msgs = body["messages"]
    assert all(m["role"] != "system" for m in user_msgs)


def test_call_anthropic_raises_runtime_error_on_401() -> None:
    messages = [{"role": "user", "content": "hello"}]
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 401
    body = (
        '{"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}'
    )
    mock_resp.text = body
    mock_resp.json.return_value = json.loads(body)
    http_err = requests.HTTPError(response=mock_resp)
    mock_resp.raise_for_status.side_effect = http_err

    with patch("scripts.run_ai_review.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="401"):
            call_anthropic(api_key="bad-key", model="claude-3-5-haiku", messages=messages)


def test_call_anthropic_raises_runtime_error_when_tool_use_block_missing() -> None:
    messages = [{"role": "user", "content": "hello"}]
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"content": [{"type": "text", "text": "no tool block"}]}

    with patch("scripts.run_ai_review.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="record_findings"):
            call_anthropic(api_key="key", model="claude-3-5-haiku", messages=messages)


# ---------------------------------------------------------------------------
# _format_gemini_error
# ---------------------------------------------------------------------------


def test_format_gemini_error_parses_error_object() -> None:
    body = json.dumps(
        {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}}
    )
    mock = MagicMock(spec=requests.Response)
    mock.text = body
    mock.json.return_value = json.loads(body)
    result = _format_gemini_error(mock)
    assert "message=API key not valid" in result
    assert "status=INVALID_ARGUMENT" in result


def test_format_gemini_error_falls_back_to_text_on_invalid_json() -> None:
    mock = MagicMock(spec=requests.Response)
    mock.text = "Bad Request"
    mock.json.side_effect = ValueError("no json")
    result = _format_gemini_error(mock)
    assert result == "Bad Request"


def test_format_gemini_error_returns_sentinel_for_empty_body() -> None:
    mock = MagicMock(spec=requests.Response)
    mock.text = ""
    mock.json.side_effect = ValueError("no json")
    result = _format_gemini_error(mock)
    assert result == "<empty response body>"


# ---------------------------------------------------------------------------
# call_gemini
# ---------------------------------------------------------------------------


def _make_gemini_success_response(findings: dict) -> MagicMock:
    mock = MagicMock(spec=requests.Response)
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(findings)}]}}
        ]
    }
    return mock


def test_call_gemini_returns_parsed_findings() -> None:
    findings = {"findings": []}
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_gemini_success_response(findings)
        result = call_gemini(api_key="test-key", model="gemini-2.0-flash", messages=messages)
    assert result == findings


def test_call_gemini_posts_to_correct_url() -> None:
    model = "gemini-2.0-flash"
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_gemini_success_response({"findings": []})
        call_gemini(api_key="key", model=model, messages=messages)
    expected_url = GEMINI_URL_TEMPLATE.format(model=model)
    assert mock_post.call_args[0][0] == expected_url


def test_call_gemini_passes_api_key_as_query_param() -> None:
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_gemini_success_response({"findings": []})
        call_gemini(api_key="my-gemini-key", model="gemini-2.0-flash", messages=messages)
    params = mock_post.call_args.kwargs["params"]
    assert params["key"] == "my-gemini-key"


def test_call_gemini_sends_system_instruction() -> None:
    messages = [
        {"role": "system", "content": "system instruction"},
        {"role": "user", "content": "user query"},
    ]
    with patch("scripts.run_ai_review.requests.post") as mock_post:
        mock_post.return_value = _make_gemini_success_response({"findings": []})
        call_gemini(api_key="key", model="gemini-2.0-flash", messages=messages)
    body = mock_post.call_args.kwargs["json"]
    assert body["systemInstruction"]["parts"][0]["text"] == "system instruction"


def test_call_gemini_raises_runtime_error_on_403() -> None:
    messages = [{"role": "user", "content": "hello"}]
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 403
    body = '{"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}}'
    mock_resp.text = body
    mock_resp.json.return_value = json.loads(body)
    http_err = requests.HTTPError(response=mock_resp)
    mock_resp.raise_for_status.side_effect = http_err

    with patch("scripts.run_ai_review.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="403"):
            call_gemini(api_key="bad-key", model="gemini-2.0-flash", messages=messages)


def test_call_gemini_raises_runtime_error_on_500() -> None:
    messages = [{"role": "user", "content": "hello"}]
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_resp.json.side_effect = ValueError("no json")
    http_err = requests.HTTPError(response=mock_resp)
    mock_resp.raise_for_status.side_effect = http_err

    with patch("scripts.run_ai_review.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="500"):
            call_gemini(api_key="key", model="gemini-2.0-flash", messages=messages)

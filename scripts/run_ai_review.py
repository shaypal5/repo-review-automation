from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.helpers import dump_json, load_json, read_text

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

PROVIDERS = ("openai", "anthropic", "gemini", "openai_compatible")

DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-3-5-haiku-20241022",
    "gemini": "gemini-2.0-flash",
    "openai_compatible": "gpt-4.1-mini",
}

PROVIDER_DEFAULT_KEY_ENVS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai_compatible": "OPENAI_API_KEY",
}

# Keep for backward compatibility
DEFAULT_MODEL = DEFAULT_MODELS["openai"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the AI review step against structured context."
    )
    parser.add_argument("--prompt-file", required=True, help="Prompt markdown file.")
    parser.add_argument("--context-file", required=True, help="review_context.json path.")
    parser.add_argument("--output", required=True, help="Raw findings JSON output path.")
    parser.add_argument(
        "--provider",
        default="openai",
        choices=list(PROVIDERS),
        help="LLM provider to use. Defaults to openai.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model name. Defaults to LLM_MODEL env var, OPENAI_MODEL env var, "
            "or the provider default."
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help=(
            "Environment variable that contains the API key. "
            "Defaults to OPENAI_API_KEY for openai/openai_compatible, "
            "ANTHROPIC_API_KEY for anthropic, GEMINI_API_KEY for gemini."
        ),
    )
    parser.add_argument(
        "--api-base-url",
        default=None,
        help=(
            "Full Chat Completions endpoint URL for OpenAI-compatible providers "
            "(for example, https://host/v1/chat/completions; may include query "
            "parameters if required). Required when --provider=openai_compatible."
        ),
    )
    args = parser.parse_args()
    if args.api_key_env is None:
        args.api_key_env = PROVIDER_DEFAULT_KEY_ENVS[args.provider]
    if args.model is None:
        args.model = (
            os.environ.get("LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or DEFAULT_MODELS[args.provider]
        )
    return args


def build_schema() -> dict[str, Any]:
    return {
        "name": "repo_review_findings",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["findings"],
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "title",
                            "category",
                            "severity",
                            "confidence",
                            "summary",
                            "evidence",
                            "recommended_fix",
                            "proposed_issue_body",
                        ],
                        "properties": {
                            "title": {"type": "string", "minLength": 5},
                            "category": {"type": "string", "minLength": 3},
                            "severity": {
                                "type": "string",
                                "enum": ["low", "medium", "high", "critical"],
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "summary": {"type": "string", "minLength": 20},
                            "evidence": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 3},
                            },
                            "recommended_fix": {"type": "string", "minLength": 20},
                            "proposed_issue_body": {"type": "string", "minLength": 20},
                        },
                    },
                }
            },
        },
    }


def build_messages(prompt_text: str, context: dict[str, Any]) -> list[dict[str, str]]:
    max_issues = context.get("max_issues", 5)
    instruction = (
        f"{prompt_text.strip()}\n\n"
        f"Return at most {max_issues} findings. "
        "Output valid JSON only and ensure every finding is grounded in the provided evidence."
    )
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": load_user_message(context)},
    ]


def load_user_message(context: dict[str, Any]) -> str:
    return (
        "Review the following structured repository context and produce findings that match the "
        "required schema.\n\n"
        f"{json.dumps(context, indent=2)}"
    )


def format_openai_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "<empty response body>"

    if isinstance(payload, dict):
        # OpenAI / OpenAI-compatible error format: {"error": {"message": ..., "type": ..., ...}}
        error = payload.get("error")
        if isinstance(error, dict):
            parts = []
            for key in ("message", "type", "code", "param"):
                value = error.get(key)
                if value is not None:
                    parts.append(f"{key}={value}")
            if parts:
                return ", ".join(parts)

    return json.dumps(payload, sort_keys=True)


def call_openai(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    url: str = OPENAI_URL,
) -> dict[str, Any]:
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.2,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": build_schema(),
            },
        },
        timeout=120,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        error_response = exc.response if exc.response is not None else response
        status_code = error_response.status_code
        error_details = format_openai_error(error_response)
        if status_code == 401:
            raise RuntimeError(
                f"Request to {url} returned 401 Unauthorized. "
                "Verify the API key is valid and has the necessary permissions. "
                f"Details: {error_details}"
            ) from exc
        raise RuntimeError(
            f"Request failed with status {status_code} at {url}. Details: {error_details}"
        ) from exc
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return load_json_payload(content)


def _format_anthropic_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "<empty response body>"

    if isinstance(payload, dict):
        # Anthropic error format: {"type": "error", "error": {"type": ..., "message": ...}}
        error = payload.get("error")
        if isinstance(error, dict):
            parts = []
            for key in ("message", "type"):
                value = error.get(key)
                if value is not None:
                    parts.append(f"{key}={value}")
            if parts:
                return ", ".join(parts)

    return json.dumps(payload, sort_keys=True)


def call_anthropic(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    system_content = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_messages = [m for m in messages if m["role"] != "system"]

    schema_def = build_schema()
    tool: dict[str, Any] = {
        "name": "record_findings",
        "description": "Record repository review findings in structured format.",
        "input_schema": {
            "type": schema_def["schema"]["type"],
            "properties": schema_def["schema"]["properties"],
            "required": schema_def["schema"]["required"],
            "additionalProperties": schema_def["schema"]["additionalProperties"],
        },
    }
    response = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 8192,
            "system": system_content,
            "messages": user_messages,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "record_findings"},
        },
        timeout=120,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        error_response = exc.response if exc.response is not None else response
        status_code = error_response.status_code
        error_details = _format_anthropic_error(error_response)
        if status_code == 401:
            raise RuntimeError(
                f"Anthropic request returned 401 Unauthorized. "
                "Verify the ANTHROPIC_API_KEY is valid. "
                f"Details: {error_details}"
            ) from exc
        raise RuntimeError(
            f"Anthropic request failed with status {status_code} at {ANTHROPIC_URL}. "
            f"Details: {error_details}"
        ) from exc
    payload = response.json()
    for block in payload.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "record_findings":
            return block["input"]
    raise RuntimeError(
        f"Anthropic response did not contain a 'record_findings' tool_use block. "
        f"Full response: {json.dumps(payload, sort_keys=True)}"
    )


def _format_gemini_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "<empty response body>"

    if isinstance(payload, dict):
        # Gemini error format: {"error": {"code": ..., "message": ..., "status": ...}}
        error = payload.get("error")
        if isinstance(error, dict):
            parts = []
            for key in ("message", "status", "code"):
                value = error.get(key)
                if value is not None:
                    parts.append(f"{key}={value}")
            if parts:
                return ", ".join(parts)

    return json.dumps(payload, sort_keys=True)


def call_gemini(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    url = GEMINI_URL_TEMPLATE.format(model=model)
    system_content = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_content = next((m["content"] for m in messages if m["role"] == "user"), "")

    schema_def = build_schema()
    response = requests.post(
        url,
        params={"key": api_key},
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_content}]},
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseSchema": schema_def["schema"],
            },
        },
        timeout=120,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        error_response = exc.response if exc.response is not None else response
        status_code = error_response.status_code
        error_details = _format_gemini_error(error_response)
        if status_code in (400, 403):
            raise RuntimeError(
                f"Gemini request returned {status_code}. "
                "Verify the GEMINI_API_KEY is valid and the model name is correct. "
                f"Details: {error_details}"
            ) from exc
        raise RuntimeError(
            f"Gemini request failed with status {status_code} at {url}. Details: {error_details}"
        ) from exc
    payload = response.json()
    content = payload["candidates"][0]["content"]["parts"][0]["text"]
    return load_json_payload(content)


def load_json_payload(content: str) -> dict[str, Any]:
    return json.loads(content)


def main() -> None:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise OSError(f"Missing required API key in environment variable {args.api_key_env}.")

    prompt_text = read_text(Path(args.prompt_file))
    context = load_json(Path(args.context_file))
    messages = build_messages(prompt_text, context)

    if args.provider == "anthropic":
        findings = call_anthropic(api_key=api_key, model=args.model, messages=messages)
    elif args.provider == "gemini":
        findings = call_gemini(api_key=api_key, model=args.model, messages=messages)
    elif args.provider == "openai_compatible":
        if not args.api_base_url:
            raise ValueError("--api-base-url is required when --provider=openai_compatible")
        findings = call_openai(
            api_key=api_key, model=args.model, messages=messages, url=args.api_base_url
        )
    else:
        findings = call_openai(api_key=api_key, model=args.model, messages=messages)

    dump_json(Path(args.output), findings)


if __name__ == "__main__":
    main()

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
DEFAULT_MODEL = "gpt-4.1-mini"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the AI review step against structured context."
    )
    parser.add_argument("--prompt-file", required=True, help="Prompt markdown file.")
    parser.add_argument("--context-file", required=True, help="review_context.json path.")
    parser.add_argument("--output", required=True, help="Raw findings JSON output path.")
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        help="OpenAI model name. Defaults to OPENAI_MODEL or gpt-4.1-mini.",
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable that contains the API key.",
    )
    return parser.parse_args()


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


def call_openai(*, api_key: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    response = requests.post(
        OPENAI_URL,
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
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return load_json_payload(content)


def load_json_payload(content: str) -> dict[str, Any]:
    return json.loads(content)


def main() -> None:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise OSError(
            f"Missing required API key in environment variable {args.api_key_env}."
        )

    prompt_text = read_text(Path(args.prompt_file))
    context = load_json(Path(args.context_file))
    messages = build_messages(prompt_text, context)
    findings = call_openai(api_key=api_key, model=args.model, messages=messages)
    dump_json(Path(args.output), findings)


if __name__ == "__main__":
    main()

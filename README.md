# repo-review-automation

`repo-review-automation` is a central GitHub Actions repository that exposes a reusable weekly repository review workflow. Milestone 1 is intentionally report-only: the workflow checks out a caller repository, collects deterministic signals, asks an AI model for structured findings, validates and normalizes those findings, and uploads both JSON and Markdown artifacts.

## Milestone 1 scope

Implemented in this milestone:

- reusable workflow at [`.github/workflows/repo-review.yml`](/Users/shaypalachy/clones/repo-review-automation/.github/workflows/repo-review.yml)
- deterministic signal collection under [`scripts/collect_signals.sh`](/Users/shaypalachy/clones/repo-review-automation/scripts/collect_signals.sh)
- compact review-context builder in [`scripts/build_review_context.py`](/Users/shaypalachy/clones/repo-review-automation/scripts/build_review_context.py)
- OpenAI-backed AI review runner in [`scripts/run_ai_review.py`](/Users/shaypalachy/clones/repo-review-automation/scripts/run_ai_review.py)
- schema validation and Markdown report generation in [`scripts/parse_findings.py`](/Users/shaypalachy/clones/repo-review-automation/scripts/parse_findings.py)
- strict findings schema at [`schemas/findings.schema.json`](/Users/shaypalachy/clones/repo-review-automation/schemas/findings.schema.json)
- prompt presets under [`prompts/`](/Users/shaypalachy/clones/repo-review-automation/prompts/default_review_prompt.md)
- parsing and summary tests under [`tests/test_parse_findings.py`](/Users/shaypalachy/clones/repo-review-automation/tests/test_parse_findings.py)

Not implemented in milestone 1:

- GitHub issue creation
- deduplication against existing issues
- Copilot follow-up automation
- repo-local config merging
- monorepo routing
- comment-on-PR or comment-on-issue modes

## Architecture summary

The reusable workflow keeps two checkouts in the same job:

- `automation/`: the `repo-review-automation` repository, containing the workflow, scripts, schema, and prompt files
- `caller/`: the downstream repository that invoked the reusable workflow

That split is the key milestone 1 design choice. It lets the job inspect the caller repository while still executing stable automation code from the central repository.

The workflow sequence is:

1. resolve the automation repository and ref from `github.workflow_ref`
2. check out `automation/` and `caller/`
3. set up Python and install the helper dependencies
4. collect deterministic signals into `out/signals/`
5. build `out/review_context.json`
6. call the AI model to produce `out/raw_findings.json`
7. validate, normalize, filter, and cap findings into `out/findings.json`
8. render `out/findings.md`
9. upload artifacts and expose outputs

## Reusable workflow inputs

Supported inputs:

- `create_issues` (`boolean`, default `false`): accepted for forward compatibility, but milestone 1 explicitly rejects `true`
- `review_mode` (`string`, default `full`)
- `prompt_preset` (`string`, default `default`)
- `min_severity` (`string`, default `medium`)
- `max_issues` (`number`, default `5`)
- `labels` (`string`, default `ai-review`): accepted for forward compatibility and ignored in milestone 1
- `paths` (`string`, default `.`)
- `python_version` (`string`, default `"3.11"`)
- `upload_artifacts` (`boolean`, default `true`)
- `dedupe_mode` (`string`, default `title_hash`): accepted for forward compatibility and ignored in milestone 1
- `issue_prefix` (`string`, default `[Repo Review]`): accepted for forward compatibility and ignored in milestone 1

Workflow outputs:

- `findings_count`
- `summary_markdown_path`
- `findings_json_path`

## Required secret and AI configuration

Milestone 1 uses the OpenAI Chat Completions API with structured JSON output.

Required:

- repository or organization secret: `OPENAI_API_KEY`

Optional:

- repository or organization variable: `OPENAI_MODEL`

If `OPENAI_MODEL` is not set, the workflow defaults to `gpt-4.1-mini`.

## Minimal consumer workflow

Copyable example:

```yaml
name: Weekly Repo Review

on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: read
  security-events: read

jobs:
  weekly-review:
    uses: your-org/repo-review-automation/.github/workflows/repo-review.yml@main
    with:
      create_issues: false
      review_mode: full
      prompt_preset: python
      min_severity: medium
      max_issues: 5
      labels: ai-review
      paths: .
      python_version: "3.11"
      upload_artifacts: true
      dedupe_mode: title_hash
      issue_prefix: "[Repo Review]"
    secrets: inherit
```

There is also a ready-to-copy example at [`examples/weekly-repo-review.yml`](/Users/shaypalachy/clones/repo-review-automation/examples/weekly-repo-review.yml).

## Artifacts and outputs

The workflow uploads a `repo-review-report` artifact containing:

- `out/review_context.json`
- `out/raw_findings.json`
- `out/findings.json`
- `out/findings.md`
- `out/signals/`

Useful deterministic signal files include:

- `project_metadata.txt`
- `file_inventory.txt`
- `todos.txt`
- `tests.txt`
- `lint.txt`
- `git_summary.txt`
- `ci_workflows.txt`

## Local development

Create an environment and install the local dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Run tests:

```bash
pytest -q
```

Run Ruff:

```bash
ruff check .
```

Run the parser manually against fixtures:

```bash
python scripts/parse_findings.py \
  --input tests/fixtures/valid_findings.json \
  --schema schemas/findings.schema.json \
  --min-severity medium \
  --max-issues 5 \
  --context tests/fixtures/review_context.json \
  --output /tmp/findings.json \
  --summary /tmp/findings.md
```

Run the signal collector manually against a local repository:

```bash
bash scripts/collect_signals.sh \
  --repo-root . \
  --paths . \
  --output-dir /tmp/repo-review-signals
```

## Limitations in milestone 1

- `create_issues=true` is rejected because issue creation is deliberately out of scope
- the AI provider is fixed to OpenAI for this milestone
- deterministic collectors are intentionally lightweight and Python-oriented
- command failures inside signal collection are captured into artifacts instead of failing the workflow immediately
- `paths` is passed into the context and collector, but the MVP collector does not implement deep multi-path routing logic

## Roadmap

Future milestones can add:

- issue creation and deduplication
- hidden fingerprint logic
- richer language-specific analyzers
- repo-local configuration files
- monorepo-aware routing
- comment or PR review output modes

## Notes on the AI output contract

The model is required to return JSON matching [`schemas/findings.schema.json`](/Users/shaypalachy/clones/repo-review-automation/schemas/findings.schema.json). Each finding must include:

- `title`
- `category`
- `severity`
- `confidence`
- `summary`
- `evidence`
- `recommended_fix`

The parser normalizes severities, filters by the configured minimum, caps the final list to `max_issues`, and renders a human-readable Markdown report.

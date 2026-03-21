# repo-review-automation

`repo-review-automation` is a central GitHub Actions repository that exposes a reusable weekly repository review workflow. Milestone 2 preserves the Milestone 1 report pipeline and extends it with controlled GitHub issue creation plus deterministic deduplication against existing open issues.

## Milestone 2 scope

Implemented in this milestone:

- reusable workflow at [`.github/workflows/repo-review.yml`](.github/workflows/repo-review.yml)
- deterministic signal collection under [`scripts/collect_signals.sh`](scripts/collect_signals.sh)
- compact review-context builder in [`scripts/build_review_context.py`](scripts/build_review_context.py)
- OpenAI-backed AI review runner in [`scripts/run_ai_review.py`](scripts/run_ai_review.py)
- schema validation and Markdown report generation in [`scripts/parse_findings.py`](scripts/parse_findings.py)
- dedupe pass under [`scripts/dedupe_findings.py`](scripts/dedupe_findings.py)
- issue creation pass under [`scripts/create_issues.py`](scripts/create_issues.py)
- shared fingerprint, label, issue-body, and GitHub API helpers in [`scripts/helpers.py`](scripts/helpers.py)
- strict findings schema at [`schemas/findings.schema.json`](schemas/findings.schema.json)
- prompt presets under [`prompts/`](prompts/)
- parsing and summary tests under [`tests/test_parse_findings.py`](tests/test_parse_findings.py)
- fingerprint, dedupe, and issue creation tests under [`tests/test_dedupe_findings.py`](tests/test_dedupe_findings.py) and [`tests/test_create_issues.py`](tests/test_create_issues.py)

Still intentionally out of scope in milestone 2:

- Copilot follow-up automation
- closed-issue reopening
- semantic similarity dedupe
- repo-local config merging
- monorepo routing
- comment-on-PR or comment-on-issue modes
- assignees, milestones, projects, or project routing

## Architecture summary

The reusable workflow keeps two checkouts in the same job:

- `automation/`: the `repo-review-automation` repository, containing the workflow, scripts, schema, and prompt files
- `caller/`: the downstream repository that invoked the reusable workflow

That split is the key milestone 1 design choice. It lets the job inspect the caller repository while still executing stable automation code from the central repository.

The workflow sequence is:

01. resolve the automation repository and ref from `github.workflow_ref`
02. check out `automation/` and `caller/`
03. set up Python and install the helper dependencies
04. collect deterministic signals into `out/signals/`
05. build `out/review_context.json`
06. call the AI model to produce `out/raw_findings.json`
07. validate, normalize, filter, and cap findings into `out/findings.json`
08. render `out/findings.md`
09. dedupe `out/findings.json` into `out/findings_deduped.json`
10. create GitHub issues from deduped findings when `create_issues=true`
11. upload artifacts and expose outputs

## PR agent context integration

This repository self-consumes [`shaypal5/pr-agent-context`](https://github.com/shaypal5/pr-agent-context)
on pull requests.

- [`.github/workflows/ci.yml`](.github/workflows/ci.yml) uploads a combined `coverage.xml` artifact and
  invokes `pr-agent-context` in `coverage_xml_artifact` mode.
- [`.github/workflows/pr-agent-context-refresh.yml`](.github/workflows/pr-agent-context-refresh.yml)
  handles follow-up refreshes after reviews and external check completion.
- The refresh flow reuses coverage from the `CI` workflow with scoped comment updates and suppresses
  no-op all-clear refresh comments.

## Report-only vs issue creation

- `create_issues: false` keeps the Milestone 1 behavior: findings are reported, artifacts are uploaded, and no issues are created.
- `create_issues: true` enables deterministic dedupe against open issues, then creates issues only for the remaining findings.

The canonical normalized report payload stays at `out/findings.json`. Issue creation uses the post-dedupe payload at `out/findings_deduped.json`.

## Reusable workflow inputs

Supported inputs:

- `create_issues` (`boolean`, default `false`): toggles report-only mode vs issue creation mode
- `review_mode` (`string`, default `full`)
- `prompt_preset` (`string`, default `default`)
- `min_severity` (`string`, default `medium`)
- `max_issues` (`number`, default `5`)
- `labels` (`string`, default `ai-review`): comma-separated labels for created issues; whitespace is trimmed and empty entries are ignored
- `paths` (`string`, default `.`)
- `python_version` (`string`, default `"3.11"`)
- `upload_artifacts` (`boolean`, default `true`)
- `dedupe_mode` (`string`, default `title_hash`): one of `off`, `title_hash`, or `fingerprint`
- `issue_prefix` (`string`, default `[Repo Review]`): prefix applied to created issue titles

Workflow outputs:

- `findings_count`
- `summary_markdown_path`
- `findings_json_path`
- `created_issue_count`
- `created_issue_numbers`
- `deduped_findings_json_path`
- `created_issues_json_path`

### `dedupe_mode` behavior

- `off`: do not compare findings against open issues; create issues for every accepted finding that survived Milestone 1 normalization.
- `title_hash`: compute a stable fingerprint from normalized `title`, `category`, the first `evidence` entry, and `recommended_fix`, then skip findings whose fingerprint already appears in an open issue.
- `fingerprint`: uses the same hidden fingerprint marker strategy as `title_hash` in milestone 2. Both modes are equivalent today and exist separately to preserve room for future semantics without breaking callers.

## Required permissions

The reusable workflow requests:

```yaml
permissions:
  contents: read
  issues: write
  pull-requests: read
  security-events: read
```

Caller workflows should grant `issues: write` when `create_issues=true`. Report-only callers can stay read-only.

## Required secret and AI configuration

Milestone 1 uses the OpenAI Chat Completions API with structured JSON output.

Required:

- repository or organization secret: `OPENAI_API_KEY`

Optional:

- repository or organization variable: `OPENAI_MODEL`

If `OPENAI_MODEL` is not set, the workflow defaults to `gpt-4.1-mini`.

Data disclosure: the workflow collects deterministic signals from the caller repository, including selected file inventories, workflow contents, TODO/FIXME matches, git history summaries, and related metadata. The resulting review context, including excerpts of that collected repository content and metadata, is sent to the OpenAI API and processed on OpenAI infrastructure outside GitHub. Consumers should verify that sending this data to OpenAI is acceptable under their organization’s security, privacy, and compliance requirements before enabling the workflow.

## Consumer workflow examples

### Report-only

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

Ready-to-copy file: [`examples/weekly-repo-review.yml`](examples/weekly-repo-review.yml).

### Create issues

```yaml
name: Weekly Repo Review With Issue Creation

on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

permissions:
  contents: read
  issues: write
  pull-requests: read
  security-events: read

jobs:
  weekly-review:
    uses: your-org/repo-review-automation/.github/workflows/repo-review.yml@main
    with:
      create_issues: true
      review_mode: full
      prompt_preset: python
      min_severity: medium
      max_issues: 5
      labels: ai-review,triage
      paths: .
      python_version: "3.11"
      upload_artifacts: true
      dedupe_mode: fingerprint
      issue_prefix: "[Repo Review]"
    secrets: inherit
```

Ready-to-copy file: [`examples/weekly-repo-review-create-issues.yml`](examples/weekly-repo-review-create-issues.yml).

## Artifacts and outputs

The workflow uploads a `repo-review-report` artifact containing:

- `out/review_context.json`
- `out/raw_findings.json`
- `out/findings.json`
- `out/findings_deduped.json`
- `out/findings.md`
- `out/dedupe_report.json`
- `out/created_issues.json`
- `out/signals/`

`out/dedupe_report.json` records a keep-or-skip decision for every finding, including the generated fingerprint and any duplicate open issue metadata. `out/created_issues.json` records the issue number, URL, title, labels, and source finding title for every created issue.

## Hidden fingerprint markers

Each created issue body ends with a hidden marker:

```html
<!-- repo-review-fingerprint: <fingerprint> -->
```

The fingerprint is deterministic and derived from normalized finding fields. Milestone 2 only dedupes against open issues that already contain this marker. This keeps dedupe behavior stable, inspectable, and auditable without adding another AI step.

Issue bodies follow a consistent structure:

- `Summary`
- `Why this matters`
- `Evidence`
- `Suggested improvement`
- `Confidence`
- `Source`
- hidden fingerprint marker

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
pytest --cov=repo_review_automation --cov-branch --cov-report=xml --cov-report=term -q
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

Run the dedupe pass manually:

```bash
GITHUB_TOKEN=... python scripts/dedupe_findings.py \
  --repo owner/repo \
  --input /tmp/findings.json \
  --mode fingerprint \
  --output /tmp/findings_deduped.json \
  --report /tmp/dedupe_report.json
```

Run issue creation manually:

```bash
GITHUB_TOKEN=... python scripts/create_issues.py \
  --repo owner/repo \
  --input /tmp/findings_deduped.json \
  --labels ai-review,triage \
  --issue-prefix "[Repo Review]" \
  --output /tmp/created_issues.json
```

Run the signal collector manually against a local repository:

```bash
bash scripts/collect_signals.sh \
  --repo-root . \
  --paths . \
  --output-dir /tmp/repo-review-signals
```

## Limitations in milestone 2

- the AI provider is fixed to OpenAI for this milestone
- deterministic collectors are intentionally lightweight and Python-oriented
- command failures inside signal collection are captured into artifacts instead of failing the workflow immediately
- `paths` supports basic file-or-directory scoping, but the MVP collector does not implement advanced monorepo routing or config merging
- label creation is not automatic; if a requested label does not exist and the GitHub API rejects it, the workflow fails with the API error
- dedupe only checks open issues that already contain the hidden fingerprint marker
- closed issues are not reopened
- `title_hash` and `fingerprint` are equivalent in milestone 2
- semantic similarity matching is intentionally deferred

## Notes on the AI output contract

The model is required to return JSON matching [`schemas/findings.schema.json`](schemas/findings.schema.json). Each finding must include:

- `title`
- `category`
- `severity`
- `confidence`
- `summary`
- `evidence`
- `recommended_fix`

The parser normalizes severities, filters by the configured minimum, caps the final list to `max_issues`, and renders a human-readable Markdown report. Milestone 2 then reuses that normalized payload for deterministic dedupe and optional issue creation without adding another model call.

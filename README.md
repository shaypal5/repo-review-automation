# repo-review-automation

`repo-review-automation` is a central GitHub Actions repository that exposes a reusable repository review workflow. Milestone 3 keeps the Milestone 1 and 2 pipeline intact and adds three rollout-focused capabilities:

- optional repo-local configuration from the caller repository
- closed-issue awareness with optional reopen behavior
- summary comment mode for low-noise manual and scheduled runs

The design remains intentionally small: deterministic signal collection, one AI review call, strict normalization, deterministic dedupe, optional issue lifecycle actions, and optional summary comments.

## What Milestone 3 preserves

Milestone 3 preserves all existing Milestone 2 behavior:

- report-only mode
- issue-creation mode
- current core artifacts and outputs
- hidden fingerprint marker behavior
- `dedupe_mode` support for `off`, `title_hash`, and `fingerprint`
- dual checkout architecture:
  - `automation/` for the central automation repository
  - `caller/` for the downstream repository invoking the workflow

## Workflow sequence

The reusable workflow now runs this sequence:

1. resolve the automation repository and ref from `github.workflow_ref`
2. check out `automation/` and `caller/`
3. set up Python and install helper dependencies
4. load and merge repo-local configuration into `out/effective_config.json`
5. collect deterministic signals into `out/signals/`
6. build `out/review_context.json`
7. call the AI model to produce `out/raw_findings.json`
8. validate, normalize, severity-filter, and ignore-filter findings into `out/findings.json`
9. render `out/findings.md`
10. emit `out/findings_deduped.json` in report-only mode and initialize empty issue/comment artifacts
11. when `create_issues=true`, dedupe against open issues, inspect closed issues, optionally reopen matches, and create new issues for the remaining findings
12. render or post a single summary comment when configured
13. upload artifacts and expose outputs

## Repo-local configuration

Caller repositories can define an optional config file at `.github/repo-review.yml` by default. A different path can be supplied through the workflow input `config_path`.

Example:

```yaml
review_mode: full
prompt_preset: python
min_severity: medium
max_issues: 3
labels:
  - ai-review
  - maintenance
dedupe_mode: fingerprint
issue_prefix: "[Repo Review]"
comment_mode: summary
comment_issue_number: 42
reopen_closed_issues: true
ignored_paths:
  - docs/generated/
  - notebooks/
ignored_categories:
  - style
```

Supported config keys:

- `review_mode`
- `prompt_preset`
- `min_severity`
- `max_issues`
- `labels`
- `paths`
- `dedupe_mode`
- `issue_prefix`
- `comment_mode`
- `comment_issue_number`
- `reopen_closed_issues`
- `ignored_paths`
- `ignored_categories`

`labels` may be either a comma-separated string or a YAML list. `paths`, `ignored_paths`, and `ignored_categories` may also be provided as strings or lists.

### Config precedence

The effective runtime config is merged deterministically using:

1. explicit workflow inputs
2. repo-local config
3. workflow defaults

The merged result is written to `out/effective_config.json` and used by later workflow steps.

### Config validation

The loader:

- parses YAML with `yaml.safe_load`
- rejects unknown top-level keys
- normalizes labels, paths, ignored categories, and ignored paths
- validates enums and integer fields
- keeps config-file absence non-fatal, including for custom `config_path` values

## Reusable workflow inputs

Milestone 2 inputs remain available. Milestone 3 adds:

- `comment_mode` (`string`, default empty): explicit override for `off` or `summary`
- `comment_issue_number` (`string`, default empty): issue number that should host the summary comment
- `reopen_closed_issues` (`string`, default empty): explicit override for `true` or `false`
- `config_path` (`string`, default `.github/repo-review.yml`)
- `ignored_paths` (`string`, default empty): explicit comma-separated override
- `ignored_categories` (`string`, default empty): explicit comma-separated override

Existing configurable fields now default to empty workflow inputs and get their actual defaults from the config loader so precedence stays correct:

- `review_mode`
- `prompt_preset`
- `min_severity`
- `max_issues`
- `labels`
- `paths`
- `dedupe_mode`
- `issue_prefix`

Non-config inputs remain:

- `create_issues` (`boolean`, default `false`)
- `python_version` (`string`, default `"3.11"`)
- `upload_artifacts` (`boolean`, default `true`)

## Outputs

Existing outputs are preserved:

- `findings_count`
- `summary_markdown_path`
- `findings_json_path`
- `created_issue_count`
- `created_issue_numbers`
- `deduped_findings_json_path`
- `created_issues_json_path`

Milestone 3 adds:

- `reopened_issue_count`
- `reopened_issue_numbers`
- `comment_posted`
- `comment_url`

## Dedupe and reopen behavior

Open-issue dedupe still works exactly as in Milestone 2, using the hidden fingerprint marker:

```html
<!-- repo-review-fingerprint: <fingerprint> -->
```

Behavior after parsing and ignore filtering:

1. if a matching open issue exists, the finding is skipped and reported as `duplicate_open_issue`
2. if no open match exists but a matching closed issue exists:
   - `reopen_closed_issues=true`: reopen that issue and do not create a new one
   - `reopen_closed_issues=false`: leave the finding actionable so a new issue is created
3. if there is no matching issue, create a new issue when `create_issues=true`

Milestone 3 still uses exact fingerprint matching only. There is no fuzzy or semantic dedupe.

## Comment mode

`comment_mode` supports:

- `off`
- `summary`

When `comment_mode=summary`:

- the workflow always renders `out/summary_comment.md`
- if `comment_issue_number` is configured, the workflow creates or updates a single comment on that issue
- if `comment_issue_number` is not configured, the workflow skips API posting and records that in `out/comment_result.json`

Comments are updated in place using this hidden marker:

```html
<!-- repo-review-summary-comment -->
```

This keeps comment mode deterministic and avoids comment spam.

### Summary comment content

The rendered summary includes:

- review mode
- findings count
- duplicate-open count
- reopened issue count
- created issue count
- top findings list with title, severity, and confidence
- a note that the summary came from the automated repository review

## Ignored categories and paths

`ignored_categories` is applied after normalization. Categories are normalized to lowercase with spaces converted to underscores before matching.

`ignored_paths` is a conservative MVP filter:

- the parser extracts repo-relative file-like paths from finding evidence
- a finding is dropped only when at least one evidence path is recognized and all recognized evidence paths fall under ignored prefixes
- findings with mixed evidence stay actionable

This keeps filtering predictable without deep path inference.

## Artifacts

The workflow artifact `repo-review-report` includes:

- `out/effective_config.json`
- `out/review_context.json`
- `out/raw_findings.json`
- `out/findings.json`
- `out/findings_deduped.json`
- `out/findings.md`
- `out/dedupe_report.json`
- `out/created_issues.json`
- `out/reopened_issues.json`
- `out/summary_comment.md`
- `out/comment_result.json`
- `out/signals/`

When `create_issues=true`, the updated artifact also includes:

- `out/findings_actionable.json`

`out/created_issues.json` records created issues. `out/reopened_issues.json` records reopened issues. `out/comment_result.json` records whether a comment was posted or skipped and captures the comment URL when available.

## Permissions

Base reusable workflow permissions remain read-oriented:

```yaml
permissions:
  contents: read
  pull-requests: read
  security-events: read
```

Caller workflows need `issues: write` when they enable either:

- `create_issues: true`
- `comment_mode: summary` with a configured `comment_issue_number`

## Required secret and AI configuration

Required:

- repository or organization secret: `OPENAI_API_KEY`

Optional:

- repository or organization variable: `OPENAI_MODEL`

If `OPENAI_MODEL` is not set, the workflow defaults to `gpt-4.1-mini`.

Data disclosure note: deterministic repository signals and the resulting review context are sent to the OpenAI API. Consumers should confirm that this is acceptable for their security and compliance requirements before enabling the workflow.

## Example consumer workflows

### A. Minimal report-only

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
    secrets: inherit
```

Ready-to-copy file: [`examples/weekly-repo-review.yml`](examples/weekly-repo-review.yml).

### B. Issue creation

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
      prompt_preset: python
      dedupe_mode: fingerprint
      labels: ai-review,triage
    secrets: inherit
```

Ready-to-copy file: [`examples/weekly-repo-review-create-issues.yml`](examples/weekly-repo-review-create-issues.yml).

### C. Issue creation plus reopen of matching closed issues

```yaml
name: Weekly Repo Review With Reopen

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
      prompt_preset: python
      dedupe_mode: fingerprint
      reopen_closed_issues: "true"
    secrets: inherit
```

Ready-to-copy file: [`examples/weekly-repo-review-reopen.yml`](examples/weekly-repo-review-reopen.yml).

### D. Summary comment mode

```yaml
name: Weekly Repo Review Summary Comment

on:
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
      create_issues: false
      comment_mode: summary
      comment_issue_number: "42"
    secrets: inherit
```

Ready-to-copy file: [`examples/weekly-repo-review-comment-summary.yml`](examples/weekly-repo-review-comment-summary.yml).

### Example repo-local config

Ready-to-copy file: [`examples/repo-review-config.yml`](examples/repo-review-config.yml).

## Local development

Run the local checks with:

```bash
pytest -q
ruff check .
```

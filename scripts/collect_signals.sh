#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="."
PATHS="."
OUTPUT_DIR="artifacts"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --paths)
      PATHS="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$OUTPUT_DIR"

REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"

metadata_file="$OUTPUT_DIR/metadata.json"
project_metadata_file="$OUTPUT_DIR/project_metadata.txt"
file_inventory_file="$OUTPUT_DIR/file_inventory.txt"
todos_file="$OUTPUT_DIR/todos.txt"
tests_file="$OUTPUT_DIR/tests.txt"
lint_file="$OUTPUT_DIR/lint.txt"
git_summary_file="$OUTPUT_DIR/git_summary.txt"
ci_workflows_file="$OUTPUT_DIR/ci_workflows.txt"

repo_name="$(basename "$REPO_ROOT")"

run_capture() {
  local label="$1"
  local output_file="$2"
  shift 2
  {
    echo "# ${label}"
    echo
    echo '$' "$@"
    echo
    if "$@"; then
      echo
      echo "[status] success"
    else
      status=$?
      echo
      echo "[status] failure (${status})"
      return 0
    fi
  } >"$output_file" 2>&1
}

{
  echo "Repository: ${repo_name}"
  echo "Root: ${REPO_ROOT}"
  echo "Paths: ${PATHS}"
  echo
  echo "Common project files:"
  for candidate in pyproject.toml requirements.txt package.json Dockerfile; do
    if [[ -f "${REPO_ROOT}/${candidate}" ]]; then
      echo "- ${candidate}: present"
    else
      echo "- ${candidate}: missing"
    fi
  done
  workflow_count=0
  if [[ -d "${REPO_ROOT}/.github/workflows" ]]; then
    workflow_count=$(find "${REPO_ROOT}/.github/workflows" -maxdepth 1 -type f | wc -l | tr -d ' ')
  fi
  echo "- .github/workflows files: ${workflow_count}"
} >"$project_metadata_file"

python3 - "$REPO_ROOT" "$PATHS" "$metadata_file" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
paths_value = sys.argv[2]
output_path = Path(sys.argv[3])

extensions = Counter()
collector_notes = []
ignored_parts = {".git", ".pytest_cache", ".ruff_cache", "__pycache__", ".venv"}

def parse_scope_tokens(raw: str) -> list[str]:
    if not raw.strip():
        return ["."]
    return [token for token in raw.replace(",", " ").split() if token]


def resolve_search_roots(repo_root: Path, raw_paths: str) -> tuple[list[Path], list[str], list[str]]:
    notes: list[str] = []
    search_roots: list[Path] = []
    effective_scope: list[str] = []

    for token in parse_scope_tokens(raw_paths):
        candidate = (repo_root / token).resolve()
        if not candidate.exists():
            notes.append(f"Path scope entry not found and ignored: {token!r}")
            continue
        search_roots.append(candidate)
        effective_scope.append(token)

    if not search_roots:
        search_roots = [repo_root]
        effective_scope = ["."]
        if raw_paths.strip():
            notes.append("No valid paths in --paths; scanned entire repository instead.")

    return search_roots, effective_scope, notes


def iter_scoped_files(repo_root: Path, raw_paths: str):
    search_roots, _, notes = resolve_search_roots(repo_root, raw_paths)
    seen_files: set[Path] = set()
    for note in notes:
        collector_notes.append(note)

    for root in search_roots:
        candidates = [root] if root.is_file() else root.rglob("*")
        for file_path in candidates:
            if not file_path.is_file():
                continue
            if any(part in ignored_parts for part in file_path.parts):
                continue
            resolved = file_path.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            yield file_path


_, effective_scope, _ = resolve_search_roots(repo_root, paths_value)

for file_path in iter_scoped_files(repo_root, paths_value):
    suffix = file_path.suffix.lower() or "[no_extension]"
    extensions[suffix] += 1

payload = {
    "repository_name": repo_root.name,
    "default_branch": None,
    "paths": paths_value,
    "paths_scope": effective_scope,
    "file_counts": dict(extensions.most_common(20)),
    "collector_notes": collector_notes,
}

git_head = repo_root / ".git"
if not git_head.exists():
    collector_notes.append("Git metadata unavailable in checkout.")
else:
    head_file = git_head / "HEAD" if git_head.is_dir() else git_head
    try:
        head_value = head_file.read_text(encoding="utf-8").strip()
        if head_value.startswith("ref: refs/heads/"):
            payload["default_branch"] = head_value.removeprefix("ref: refs/heads/")
    except OSError:
        collector_notes.append("Unable to infer branch metadata from .git/HEAD.")

output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

run_capture \
  "File inventory" \
  "$file_inventory_file" \
  python3 - "$REPO_ROOT" "$PATHS" <<'PY'
from collections import Counter
from pathlib import Path
import sys

repo_root = Path(sys.argv[1]).resolve()
paths_value = sys.argv[2]
extensions = Counter()
directories = Counter()
ignored_parts = {".git", ".pytest_cache", ".ruff_cache", "__pycache__", ".venv"}

def parse_scope_tokens(raw: str) -> list[str]:
    if not raw.strip():
        return ["."]
    return [token for token in raw.replace(",", " ").split() if token]


search_roots = []
seen_files = set()

for token in parse_scope_tokens(paths_value):
    candidate = (repo_root / token).resolve()
    if candidate.exists():
        search_roots.append(candidate)

if not search_roots:
    search_roots = [repo_root]

for root in search_roots:
    candidates = [root] if root.is_file() else root.rglob("*")
    for file_path in candidates:
        if not file_path.is_file():
            continue
        if any(part in ignored_parts for part in file_path.parts):
            continue
        resolved = file_path.resolve()
        if resolved in seen_files:
            continue
        seen_files.add(resolved)
        suffix = file_path.suffix.lower() or "[no_extension]"
        extensions[suffix] += 1
        try:
            first_part = file_path.relative_to(repo_root).parts[0]
        except IndexError:
            first_part = "."
        directories[first_part] += 1

print("Top file extensions:")
for extension, count in extensions.most_common(20):
    print(f"- {extension}: {count}")

print("\nTop directories:")
for directory, count in directories.most_common(20):
    print(f"- {directory}: {count}")
PY

run_capture \
  "TODO/FIXME/HACK scan" \
  "$todos_file" \
  sh -c "cd \"$REPO_ROOT\" && grep -rEn --exclude-dir='.git' 'TODO|FIXME|HACK' ${PATHS@Q}"

if [[ -f "${REPO_ROOT}/pyproject.toml" || -f "${REPO_ROOT}/requirements.txt" ]]; then
  if find "$REPO_ROOT" -type f \( -path "*/tests/*" -o -name "test_*.py" \) | head -n 1 >/dev/null; then
    run_capture \
      "Pytest collection" \
      "$tests_file" \
      sh -c "cd \"$REPO_ROOT\" && python3 -m pytest --collect-only -q ${PATHS@Q}"
  else
    echo "No Python tests detected." >"$tests_file"
  fi
  run_capture \
    "Python compileall" \
    "$lint_file" \
    sh -c "cd \"$REPO_ROOT\" && python3 -m compileall -q ${PATHS@Q}"
else
  echo "No Python project metadata detected; skipped Python checks." >"$tests_file"
  echo "No Python project metadata detected; skipped lint-style checks." >"$lint_file"
fi

if [[ -d "${REPO_ROOT}/.github/workflows" ]]; then
  run_capture \
    "Workflow scan" \
    "$ci_workflows_file" \
    sh -c "cd \"$REPO_ROOT\" && grep -rn '' .github/workflows"
else
  echo "No .github/workflows directory detected." >"$ci_workflows_file"
fi

if git -C "$REPO_ROOT" rev-parse HEAD >/dev/null 2>&1; then
  run_capture \
    "Recent git summary" \
    "$git_summary_file" \
    git -C "$REPO_ROOT" log --oneline -n 10
else
  echo "Git history unavailable in checkout." >"$git_summary_file"
fi

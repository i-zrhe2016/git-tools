#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  commit_git.sh [options]

Options:
  --message TEXT        Commit message. If omitted, prompt interactively.
  --author-name NAME    Override author/committer name for this commit only.
  --author-email EMAIL  Override author/committer email for this commit only.
  --allow-empty         Create a commit even when there are no changes.
  -h, --help            Show this help message.

Examples:
  ./commit_git.sh --message "Update docs"
  ./commit_git.sh --message "Release" --author-name "git-tools api" --author-email "bot@example.com"
EOF
}

COMMIT_MESSAGE=""
AUTHOR_NAME="${GIT_COMMIT_AUTHOR_NAME:-}"
AUTHOR_EMAIL="${GIT_COMMIT_AUTHOR_EMAIL:-}"
ALLOW_EMPTY=0

prompt_nonempty() {
  local label="$1"
  local value=""

  if [[ ! -t 0 ]]; then
    echo "${label} is required when stdin is not interactive." >&2
    exit 1
  fi

  while [[ -z "${value}" ]]; do
    read -r -p "${label}: " value
  done

  printf '%s\n' "${value}"
}

prompt_commit_message() {
  prompt_nonempty "Commit message"
}

resolve_author_name() {
  local configured_name=""
  if [[ -n "${AUTHOR_NAME}" ]]; then
    printf '%s\n' "${AUTHOR_NAME}"
    return
  fi

  configured_name="$(git config --get user.name 2>/dev/null || true)"
  if [[ -n "${configured_name}" ]]; then
    printf '%s\n' "${configured_name}"
    return
  fi

  prompt_nonempty "Author name"
}

resolve_author_email() {
  local configured_email=""
  if [[ -n "${AUTHOR_EMAIL}" ]]; then
    printf '%s\n' "${AUTHOR_EMAIL}"
    return
  fi

  configured_email="$(git config --get user.email 2>/dev/null || true)"
  if [[ -n "${configured_email}" ]]; then
    printf '%s\n' "${configured_email}"
    return
  fi

  prompt_nonempty "Author email"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --message)
      COMMIT_MESSAGE="${2:-}"
      shift 2
      ;;
    --author-name)
      AUTHOR_NAME="${2:-}"
      shift 2
      ;;
    --author-email)
      AUTHOR_EMAIL="${2:-}"
      shift 2
      ;;
    --allow-empty)
      ALLOW_EMPTY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "This script must be run inside a git repository." >&2
  exit 1
fi

if [[ -z "${COMMIT_MESSAGE}" ]]; then
  COMMIT_MESSAGE="$(prompt_commit_message)"
fi

AUTHOR_NAME="$(resolve_author_name)"
AUTHOR_EMAIL="$(resolve_author_email)"

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo ".env is tracked by git. Refusing to commit it." >&2
  exit 1
fi

git add -A

if [[ "${ALLOW_EMPTY}" -ne 1 ]] && git diff --cached --quiet --exit-code; then
  echo "No changes to commit."
  exit 0
fi

COMMIT_COMMAND=(git commit -m "${COMMIT_MESSAGE}")
COMMIT_ENV=()

if [[ "${ALLOW_EMPTY}" -eq 1 ]]; then
  COMMIT_COMMAND+=(--allow-empty)
fi

if [[ -n "${AUTHOR_NAME}" ]]; then
  COMMIT_ENV+=("GIT_AUTHOR_NAME=${AUTHOR_NAME}" "GIT_COMMITTER_NAME=${AUTHOR_NAME}")
fi

if [[ -n "${AUTHOR_EMAIL}" ]]; then
  COMMIT_ENV+=("GIT_AUTHOR_EMAIL=${AUTHOR_EMAIL}" "GIT_COMMITTER_EMAIL=${AUTHOR_EMAIL}")
fi

if [[ "${#COMMIT_ENV[@]}" -gt 0 ]]; then
  env "${COMMIT_ENV[@]}" "${COMMIT_COMMAND[@]}"
else
  "${COMMIT_COMMAND[@]}"
fi

echo "Created commit $(git rev-parse HEAD)"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMIT_ARGS=()
PUSH_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  submit_git.sh [options]

Commit local changes and push them with the project scripts.

Commit options:
  --message TEXT        Commit message. If omitted, prompt interactively.
  --author-name NAME    Override author/committer name for this commit only.
  --author-email EMAIL  Override author/committer email for this commit only.
  --allow-empty         Create a commit even when there are no changes.

Push options:
  --remote NAME         Git remote name. Default: origin
  --branch NAME         Git branch name. Default: current branch
  --repo PATH           Remote repo path, such as owner/repo
  --remote-url URL      Explicit remote URL to use
  --host HOST           Git server hostname. Default: derived from remote, otherwise github.com
  --user USER           SSH username. Default: $GIT_SSH_USER or git
  --key-path PATH       SSH private key path. Default: ./key in the current directory
  --allow-dirty         Pass through to push_git.sh
  -h, --help            Show this help message.

Examples:
  ./submit_git.sh --message "Update README"
  ./submit_git.sh --message "Release" --repo owner/repo --branch main
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --message|--author-name|--author-email)
      COMMIT_ARGS+=("$1" "${2:-}")
      shift 2
      ;;
    --allow-empty)
      COMMIT_ARGS+=("$1")
      shift
      ;;
    --remote|--branch|--repo|--remote-url|--host|--user|--key-path)
      PUSH_ARGS+=("$1" "${2:-}")
      shift 2
      ;;
    --allow-dirty)
      PUSH_ARGS+=("$1")
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

"${SCRIPT_DIR}/commit_git.sh" "${COMMIT_ARGS[@]}"
"${SCRIPT_DIR}/push_git.sh" "${PUSH_ARGS[@]}"

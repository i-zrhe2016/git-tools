#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  push_git.sh [options]

Options:
  --remote NAME         Git remote name. Default: origin
  --branch NAME         Git branch name. Default: current branch
  --repo PATH           Remote repo path, such as owner/repo
  --remote-url URL      Explicit remote URL to use
  --host HOST           Git server hostname. Default: derived from remote, otherwise github.com
  --user USER           SSH username. Default: $GIT_SSH_USER or git
  --key-path PATH       SSH private key path. Default: ./key in the current directory
  --allow-dirty         Push even if the working tree is dirty
  -h, --help            Show this help message.

Examples:
  ./push_git.sh
  ./push_git.sh --host gitlab.com --repo group/project
  ./push_git.sh --remote-url git@example.com:team/repo.git --key-path ./key
EOF
}

REMOTE="origin"
BRANCH=""
REPO_PATH=""
REMOTE_URL_OVERRIDE=""
HOST_NAME=""
SSH_USER="${GIT_SSH_USER:-git}"
KEY_PATH=""
ALLOW_DIRTY=0

resolve_default_key_path() {
  printf '%s\n' "$(pwd)/key"
}

build_ssh_command() {
  local command="ssh -i ${KEY_PATH} -o IdentitiesOnly=yes"
  if [[ -n "${GIT_SSH_KNOWN_HOSTS_PATH:-}" ]]; then
    command="${command} -o UserKnownHostsFile=${GIT_SSH_KNOWN_HOSTS_PATH}"
  fi
  printf '%s\n' "${command}"
}

parse_remote_url() {
  local url="${1:-}"
  if [[ -z "${url}" ]]; then
    return 1
  fi

  if [[ "${url}" =~ ^https?://([^/]+)/(.+)$ ]]; then
    printf '%s\n%s\n%s\n' "${BASH_REMATCH[1]}" "git" "${BASH_REMATCH[2]%.git}"
    return 0
  fi

  if [[ "${url}" =~ ^ssh://([^@]+)@([^/]+)/(.+)$ ]]; then
    printf '%s\n%s\n%s\n' "${BASH_REMATCH[2]}" "${BASH_REMATCH[1]}" "${BASH_REMATCH[3]%.git}"
    return 0
  fi

  if [[ "${url}" =~ ^([^@]+)@([^:]+):(.+)$ ]]; then
    printf '%s\n%s\n%s\n' "${BASH_REMATCH[2]}" "${BASH_REMATCH[1]}" "${BASH_REMATCH[3]%.git}"
    return 0
  fi

  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE="${2:-}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --repo)
      REPO_PATH="${2:-}"
      shift 2
      ;;
    --remote-url)
      REMOTE_URL_OVERRIDE="${2:-}"
      shift 2
      ;;
    --host)
      HOST_NAME="${2:-}"
      shift 2
      ;;
    --user)
      SSH_USER="${2:-}"
      shift 2
      ;;
    --key-path)
      KEY_PATH="${2:-}"
      shift 2
      ;;
    --allow-dirty)
      ALLOW_DIRTY=1
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

if [[ -z "${BRANCH}" ]]; then
  BRANCH="$(git branch --show-current)"
fi

if [[ -z "${BRANCH}" ]]; then
  echo "Could not determine the current branch." >&2
  exit 1
fi

REMOTE_URL="$(git remote get-url "${REMOTE}" 2>/dev/null || true)"
PARSED_HOST=""
PARSED_USER=""
PARSED_REPO=""
TMP_REMOTE_PARTS="$(mktemp)"

if parse_remote_url "${REMOTE_URL}" >"${TMP_REMOTE_PARTS}"; then
  mapfile -t REMOTE_PARTS <"${TMP_REMOTE_PARTS}"
  PARSED_HOST="${REMOTE_PARTS[0]:-}"
  PARSED_USER="${REMOTE_PARTS[1]:-}"
  PARSED_REPO="${REMOTE_PARTS[2]:-}"
fi
rm -f "${TMP_REMOTE_PARTS}"

if [[ -z "${HOST_NAME}" ]]; then
  HOST_NAME="${PARSED_HOST:-${GIT_SSH_HOST:-github.com}}"
fi

if [[ -z "${REPO_PATH}" ]]; then
  REPO_PATH="${PARSED_REPO}"
fi

if [[ -z "${KEY_PATH}" ]]; then
  KEY_PATH="$(resolve_default_key_path || true)"
fi

if [[ ! -f "${KEY_PATH}" ]]; then
  echo "SSH private key not found: ${KEY_PATH}" >&2
  echo "Run setup_git_ssh.sh first, or pass --key-path." >&2
  exit 1
fi

if [[ -z "${REMOTE_URL_OVERRIDE}" && -z "${REMOTE_URL}" && -z "${REPO_PATH}" ]]; then
  echo "Remote '${REMOTE}' is missing. Pass --repo PATH or --remote-url." >&2
  exit 1
fi

if [[ -n "${REMOTE_URL_OVERRIDE}" ]]; then
  FINAL_REMOTE_URL="${REMOTE_URL_OVERRIDE}"
else
  if [[ -z "${REPO_PATH}" ]]; then
    echo "Could not resolve remote repo path. Pass --repo PATH or --remote-url." >&2
    exit 1
  fi
  REPO_PATH="${REPO_PATH#https://}"
  REPO_PATH="${REPO_PATH#http://}"
  REPO_PATH="${REPO_PATH#${HOST_NAME}/}"
  REPO_PATH="${REPO_PATH#git@${HOST_NAME}:}"
  REPO_PATH="${REPO_PATH%.git}"
  FINAL_REMOTE_URL="${SSH_USER}@${HOST_NAME}:${REPO_PATH}.git"
fi

if [[ -n "${REMOTE_URL}" ]]; then
  git remote set-url "${REMOTE}" "${FINAL_REMOTE_URL}"
else
  git remote add "${REMOTE}" "${FINAL_REMOTE_URL}"
fi

if [[ "${ALLOW_DIRTY}" -ne 1 ]] && [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree has uncommitted changes. Run ./submit_git.sh or ./commit_git.sh first, or rerun with --allow-dirty." >&2
  exit 1
fi

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo ".env is tracked by git. Refusing to push until it is removed from version control." >&2
  exit 1
fi

git config core.sshCommand "$(build_ssh_command)"

echo "Pushing ${BRANCH} to ${FINAL_REMOTE_URL}"
git push "${REMOTE}" "${BRANCH}"

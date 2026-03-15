from __future__ import annotations

import base64
import binascii
import os
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("GIT_API_DATA_DIR", ROOT_DIR / "data")).resolve()
KEYS_DIR = DATA_DIR / "keys"
SSH_HOME = Path(os.getenv("GIT_API_HOME", DATA_DIR / "home")).resolve()
WORKSPACE_ROOT = Path(
    os.getenv("GIT_API_WORKSPACE_ROOT", ROOT_DIR / "workspace")
).resolve()
STAGING_ROOT = WORKSPACE_ROOT / "_api"
DEFAULT_KEY_NAME = os.getenv("GIT_API_DEFAULT_KEY_NAME", "default")
DEFAULT_AUTHOR_NAME = os.getenv("GIT_API_COMMIT_AUTHOR_NAME", "git-tools api")
DEFAULT_AUTHOR_EMAIL = os.getenv(
    "GIT_API_COMMIT_AUTHOR_EMAIL", "git-tools-api@example.invalid"
)
AUTH_REQUIRED_ENV = "GIT_API_AUTH_REQUIRED"
AUTH_TOKEN_ENV = "GIT_API_AUTH_TOKEN"
KEY_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
REMOTE_HTTPS_RE = re.compile(r"^https?://([^/]+)/(.+)$")
REMOTE_SSH_URL_RE = re.compile(r"^ssh://([^@]+)@([^/]+)/(.+)$")
REMOTE_SCP_RE = re.compile(r"^([^@]+)@([^:]+):(.+)$")
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
PUBLIC_PATHS = frozenset({"/health"})

SETUP_SCRIPT = ROOT_DIR / "setup_git_ssh.sh"
PUSH_SCRIPT = ROOT_DIR / "push_git.sh"


class SaveKeyRequest(BaseModel):
    email: str | None = None
    key_name: str = Field(default=DEFAULT_KEY_NAME)
    host: str = Field(default="github.com")
    host_alias: str | None = None
    user: str = Field(default="git")
    private_key: str = Field(min_length=1)


class RepoFile(BaseModel):
    path: str = Field(min_length=1)
    content: str | None = None
    content_b64: str | None = None
    executable: bool = False


class PushRequest(BaseModel):
    repo_dir: str | None = None
    files: list[RepoFile] | None = None
    key_name: str = Field(default=DEFAULT_KEY_NAME)
    remote: str = Field(default="origin")
    branch: str | None = None
    repo: str | None = None
    remote_url: str | None = None
    host: str | None = None
    user: str = Field(default="git")
    allow_dirty: bool = False
    private_key: str | None = None
    commit_message: str = Field(default="Update via git-tools API", min_length=1)
    author_name: str | None = None
    author_email: str | None = None
    delete_missing: bool = True
    force_push: bool = False


class CommandError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stdout: str, stderr: str):
        self.args_list = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(stderr or stdout or "command failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_auth_configuration()
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    SSH_HOME.mkdir(parents=True, exist_ok=True)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    bootstrap_key_from_env()
    yield


app = FastAPI(title="git-tools API", version="1.0.0", lifespan=lifespan)


def getenv_nonempty(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def parse_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise RuntimeError(
        f"{name} must be one of: {', '.join(sorted(TRUE_VALUES | FALSE_VALUES))}"
    )


def auth_required() -> bool:
    return parse_bool_env(AUTH_REQUIRED_ENV, default=True)


def configured_auth_token() -> str | None:
    return getenv_nonempty(AUTH_TOKEN_ENV)


def validate_auth_configuration() -> None:
    if auth_required() and not configured_auth_token():
        raise RuntimeError(f"{AUTH_TOKEN_ENV} must be set when {AUTH_REQUIRED_ENV}=true")


def command_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(SSH_HOME)
    if extra_env:
        env.update(extra_env)
    return env


def run_command(
    args: list[str],
    cwd: Path | None = None,
    check: bool = True,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=command_env(extra_env),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if check and completed.returncode != 0:
        raise CommandError(args, completed.returncode, completed.stdout, completed.stderr)
    return completed


def sanitize_key_name(key_name: str) -> str:
    if not KEY_NAME_RE.fullmatch(key_name):
        raise HTTPException(
            status_code=400,
            detail="key_name only allows letters, numbers, dot, underscore and hyphen",
        )
    return key_name


def key_path_for_name(key_name: str) -> Path:
    safe_name = sanitize_key_name(key_name)
    return KEYS_DIR / f"{safe_name}.key"


def read_public_key(key_path: Path) -> str:
    public_key_path = key_path.with_suffix(f"{key_path.suffix}.pub")
    if not public_key_path.exists():
        raise HTTPException(status_code=500, detail="public key file was not generated")
    return public_key_path.read_text(encoding="utf-8").strip()


def resolve_repo_dir(repo_dir: str) -> Path:
    requested = Path(repo_dir)
    resolved = requested.resolve() if requested.is_absolute() else (WORKSPACE_ROOT / requested).resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"repo_dir must stay inside workspace root: {WORKSPACE_ROOT}",
        ) from exc
    if not resolved.exists():
        raise HTTPException(status_code=400, detail=f"repo_dir does not exist: {resolved}")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"repo_dir is not a directory: {resolved}")
    return resolved


def build_setup_command(request: SaveKeyRequest, key_path: Path, require_existing_key: bool = True) -> list[str]:
    command = [
        str(SETUP_SCRIPT),
        "--key-path",
        str(key_path),
        "--host",
        request.host,
        "--user",
        request.user,
        "--no-repo-config",
    ]
    if require_existing_key:
        command.append("--require-existing-key")
    if request.email:
        command.extend(["--email", request.email])
    if request.host_alias:
        command.extend(["--host-alias", request.host_alias])
    return command


def build_ssh_command(key_path: Path) -> str:
    command = f"ssh -i {shlex.quote(str(key_path))} -o IdentitiesOnly=yes"
    known_hosts = os.getenv("GIT_SSH_KNOWN_HOSTS_PATH")
    if known_hosts:
        command += f" -o UserKnownHostsFile={shlex.quote(known_hosts)}"
    return command


def write_private_key(key_path: Path, private_key: str) -> None:
    normalized = private_key.replace("\r\n", "\n").strip()
    key_path.write_text(f"{normalized}\n", encoding="utf-8")
    os.chmod(key_path, 0o600)
    public_key_path = key_path.with_suffix(f"{key_path.suffix}.pub")
    public_key = run_command(["ssh-keygen", "-y", "-f", str(key_path)]).stdout
    public_key_path.write_text(public_key, encoding="utf-8")
    os.chmod(public_key_path, 0o644)


def normalize_private_key_env(private_key: str) -> str:
    return private_key.replace("\\r\\n", "\n").replace("\\n", "\n")


def resolve_private_key_from_env() -> tuple[str | None, str | None]:
    plain = getenv_nonempty("GIT_API_INIT_PRIVATE_KEY")
    encoded = getenv_nonempty("GIT_API_INIT_PRIVATE_KEY_B64")
    if plain and encoded:
        raise RuntimeError(
            "set only one of GIT_API_INIT_PRIVATE_KEY or GIT_API_INIT_PRIVATE_KEY_B64"
        )
    if plain:
        return normalize_private_key_env(plain), "GIT_API_INIT_PRIVATE_KEY"
    if not encoded:
        return None, None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise RuntimeError("GIT_API_INIT_PRIVATE_KEY_B64 is not valid base64 UTF-8 data") from exc
    return decoded, "GIT_API_INIT_PRIVATE_KEY_B64"


def bootstrap_key_from_env() -> None:
    private_key, source = resolve_private_key_from_env()
    if private_key is None or source is None:
        return

    key_name = getenv_nonempty("GIT_API_INIT_KEY_NAME") or DEFAULT_KEY_NAME
    host = getenv_nonempty("GIT_API_INIT_HOST") or "github.com"
    user = getenv_nonempty("GIT_API_INIT_USER") or "git"

    try:
        request = SaveKeyRequest(
            email=getenv_nonempty("GIT_API_INIT_EMAIL"),
            key_name=key_name,
            host=host,
            host_alias=getenv_nonempty("GIT_API_INIT_HOST_ALIAS"),
            user=user,
            private_key=private_key,
        )
        key_path = key_path_for_name(request.key_name)
        write_private_key(key_path, request.private_key)
        run_command(build_setup_command(request, key_path, require_existing_key=True), cwd=ROOT_DIR)
    except HTTPException as exc:
        raise RuntimeError(f"failed to bootstrap private key from {source}: {exc.detail}") from exc
    except CommandError as exc:
        error = exc.stderr.strip() or exc.stdout.strip() or "command failed"
        raise RuntimeError(f"failed to bootstrap private key from {source}: {error}") from exc


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    stripped = token.strip()
    return stripped or None


def request_api_token(request: Request) -> str | None:
    bearer = extract_bearer_token(request.headers.get("Authorization"))
    if bearer:
        return bearer
    api_key = request.headers.get("X-API-Key")
    if api_key is None:
        return None
    stripped = api_key.strip()
    return stripped or None


@app.middleware("http")
async def require_api_auth(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS or not auth_required():
        return await call_next(request)

    expected_token = configured_auth_token()
    if not expected_token:
        return JSONResponse(
            status_code=503,
            content={"detail": f"{AUTH_TOKEN_ENV} is not configured"},
        )

    provided_token = request_api_token(request)
    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        return JSONResponse(
            status_code=401,
            content={"detail": "missing or invalid api token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


def command_failure(exc: CommandError) -> HTTPException:
    detail = {
        "command": exc.args_list,
        "returncode": exc.returncode,
        "stdout": exc.stdout.strip(),
        "stderr": exc.stderr.strip(),
    }
    return HTTPException(status_code=400, detail=detail)


def parse_remote_url(remote_url: str) -> tuple[str, str, str] | None:
    https_match = REMOTE_HTTPS_RE.fullmatch(remote_url)
    if https_match:
        return https_match.group(1), "git", https_match.group(2).removesuffix(".git")

    ssh_url_match = REMOTE_SSH_URL_RE.fullmatch(remote_url)
    if ssh_url_match:
        return ssh_url_match.group(2), ssh_url_match.group(1), ssh_url_match.group(3).removesuffix(
            ".git"
        )

    scp_match = REMOTE_SCP_RE.fullmatch(remote_url)
    if scp_match:
        return scp_match.group(2), scp_match.group(1), scp_match.group(3).removesuffix(".git")

    return None


def resolve_push_mode(request: PushRequest) -> str:
    has_repo_dir = bool(request.repo_dir)
    has_files = request.files is not None
    if has_repo_dir == has_files:
        raise HTTPException(status_code=400, detail="provide exactly one of repo_dir or files")
    if has_files and not request.files:
        raise HTTPException(status_code=400, detail="files must not be empty")
    return "repo_dir" if has_repo_dir else "files"


def resolve_host(request: PushRequest) -> str:
    if request.host:
        return request.host
    if request.remote_url:
        parsed = parse_remote_url(request.remote_url)
        if parsed:
            return parsed[0]
    return "github.com"


def resolve_branch(request: PushRequest) -> str:
    return request.branch or "main"


def resolve_author_name(request: PushRequest) -> str:
    return (request.author_name or "").strip() or DEFAULT_AUTHOR_NAME


def resolve_author_email(request: PushRequest) -> str:
    return (request.author_email or "").strip() or DEFAULT_AUTHOR_EMAIL


def build_remote_url(request: PushRequest) -> str:
    if request.remote_url:
        return request.remote_url
    if not request.repo:
        raise HTTPException(status_code=400, detail="repo or remote_url is required")

    host = resolve_host(request)
    repo_path = request.repo.strip()
    for prefix in (
        f"https://{host}/",
        f"http://{host}/",
        f"git@{host}:",
        f"{host}/",
    ):
        if repo_path.startswith(prefix):
            repo_path = repo_path[len(prefix) :]
    repo_path = repo_path.removesuffix(".git")
    return f"{request.user}@{host}:{repo_path}.git"


def ensure_key_ready(request: PushRequest) -> Path:
    key_path = key_path_for_name(request.key_name)
    if not request.private_key:
        return key_path

    host = resolve_host(request)
    save_request = SaveKeyRequest(
        email=None,
        key_name=request.key_name,
        host=host,
        host_alias=None,
        user=request.user,
        private_key=request.private_key,
    )
    write_private_key(key_path, request.private_key)
    run_command(build_setup_command(save_request, key_path, require_existing_key=True), cwd=ROOT_DIR)
    return key_path


def resolve_repo_file_path(repo_dir: Path, relative_path: str) -> Path:
    if "\\" in relative_path:
        raise HTTPException(status_code=400, detail="file paths must use forward slashes")

    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or not relative.parts:
        raise HTTPException(status_code=400, detail=f"invalid file path: {relative_path}")
    if any(part in ("", ".", "..", ".git") for part in relative.parts):
        raise HTTPException(status_code=400, detail=f"invalid file path: {relative_path}")

    target = (repo_dir / Path(*relative.parts)).resolve()
    try:
        target.relative_to(repo_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid file path: {relative_path}") from exc
    return target


def decode_repo_file_content(file_request: RepoFile) -> bytes:
    if (file_request.content is None) == (file_request.content_b64 is None):
        raise HTTPException(
            status_code=400,
            detail=f"file {file_request.path} must set exactly one of content or content_b64",
        )
    if file_request.content is not None:
        return file_request.content.encode("utf-8")
    try:
        return base64.b64decode(file_request.content_b64 or "", validate=True)
    except binascii.Error as exc:
        raise HTTPException(
            status_code=400,
            detail=f"file {file_request.path} has invalid base64 content",
        ) from exc


def clear_repo_contents(repo_dir: Path) -> None:
    for child in repo_dir.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def write_repo_files(repo_dir: Path, files: list[RepoFile]) -> int:
    prepared_files: list[tuple[Path, bytes, bool]] = []
    seen_paths: set[str] = set()

    for file_request in files:
        target_path = resolve_repo_file_path(repo_dir, file_request.path)
        target_key = target_path.relative_to(repo_dir).as_posix()
        if target_key in seen_paths:
            raise HTTPException(status_code=400, detail=f"duplicate file path: {file_request.path}")
        seen_paths.add(target_key)
        prepared_files.append(
            (target_path, decode_repo_file_content(file_request), file_request.executable)
        )

    for target_path, content, executable in prepared_files:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        os.chmod(target_path, 0o755 if executable else 0o644)

    return len(prepared_files)


def configure_remote(repo_dir: Path, remote_name: str, remote_url: str) -> None:
    existing = run_command(["git", "remote", "get-url", remote_name], cwd=repo_dir, check=False)
    if existing.returncode == 0:
        run_command(["git", "remote", "set-url", remote_name, remote_url], cwd=repo_dir)
        return
    run_command(["git", "remote", "add", remote_name, remote_url], cwd=repo_dir)


def remote_branch_exists(repo_dir: Path, remote_url: str, branch: str) -> bool:
    completed = run_command(
        ["git", "ls-remote", "--heads", remote_url, branch], cwd=repo_dir, check=False
    )
    if completed.returncode != 0:
        raise CommandError(
            ["git", "ls-remote", "--heads", remote_url, branch],
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )
    return bool(completed.stdout.strip())


def prepare_uploaded_repo(
    repo_dir: Path,
    remote_name: str,
    remote_url: str,
    branch: str,
    key_path: Path,
    author_name: str,
    author_email: str,
) -> None:
    run_command(["git", "init"], cwd=repo_dir)
    run_command(["git", "config", "user.name", author_name], cwd=repo_dir)
    run_command(["git", "config", "user.email", author_email], cwd=repo_dir)
    run_command(["git", "config", "core.sshCommand", build_ssh_command(key_path)], cwd=repo_dir)
    configure_remote(repo_dir, remote_name, remote_url)

    if remote_branch_exists(repo_dir, remote_url, branch):
        run_command(["git", "fetch", remote_name, branch], cwd=repo_dir)
        run_command(["git", "checkout", "-B", branch, "FETCH_HEAD"], cwd=repo_dir)
        return

    run_command(["git", "symbolic-ref", "HEAD", f"refs/heads/{branch}"], cwd=repo_dir)


def current_commit(repo_dir: Path) -> str | None:
    completed = run_command(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def push_existing_repo(request: PushRequest, key_path: Path) -> dict[str, str]:
    if request.repo_dir is None:
        raise HTTPException(status_code=400, detail="repo_dir is required for repository push mode")

    repo_dir = resolve_repo_dir(request.repo_dir)
    command = [
        str(PUSH_SCRIPT),
        "--remote",
        request.remote,
        "--user",
        request.user,
        "--key-path",
        str(key_path),
    ]

    if request.branch:
        command.extend(["--branch", request.branch])
    if request.repo:
        command.extend(["--repo", request.repo])
    if request.remote_url:
        command.extend(["--remote-url", request.remote_url])
    if request.host:
        command.extend(["--host", request.host])
    if request.allow_dirty:
        command.append("--allow-dirty")

    completed = run_command(command, cwd=repo_dir)
    return {
        "mode": "repo_dir",
        "repo_dir": str(repo_dir),
        "key_name": request.key_name,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def push_uploaded_files(request: PushRequest, key_path: Path) -> dict[str, object]:
    if request.files is None:
        raise HTTPException(status_code=400, detail="files are required for content push mode")

    remote_url = build_remote_url(request)
    branch = resolve_branch(request)
    author_name = resolve_author_name(request)
    author_email = resolve_author_email(request)

    with tempfile.TemporaryDirectory(dir=STAGING_ROOT) as temp_dir:
        repo_dir = Path(temp_dir)
        prepare_uploaded_repo(
            repo_dir=repo_dir,
            remote_name=request.remote,
            remote_url=remote_url,
            branch=branch,
            key_path=key_path,
            author_name=author_name,
            author_email=author_email,
        )

        if request.delete_missing:
            clear_repo_contents(repo_dir)
        files_written = write_repo_files(repo_dir, request.files)
        run_command(["git", "add", "-A"], cwd=repo_dir)

        status = run_command(["git", "status", "--short"], cwd=repo_dir)
        commit_created = bool(status.stdout.strip())
        if commit_created:
            run_command(["git", "commit", "-m", request.commit_message], cwd=repo_dir)

        command = ["git", "push"]
        if request.force_push:
            command.append("--force-with-lease")
        command.extend([request.remote, branch])
        completed = run_command(command, cwd=repo_dir)
        commit = current_commit(repo_dir)

    return {
        "mode": "files",
        "remote": request.remote,
        "remote_url": remote_url,
        "branch": branch,
        "key_name": request.key_name,
        "files_written": files_written,
        "delete_missing": request.delete_missing,
        "commit_created": commit_created,
        "commit": commit,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/keys/import")
def import_key(request: SaveKeyRequest) -> dict[str, str]:
    key_path = key_path_for_name(request.key_name)
    try:
        write_private_key(key_path, request.private_key)
        run_command(build_setup_command(request, key_path, require_existing_key=True), cwd=ROOT_DIR)
    except CommandError as exc:
        raise command_failure(exc) from exc

    return {
        "key_name": request.key_name,
        "private_key_path": str(key_path),
        "public_key": read_public_key(key_path),
        "host": request.host,
        "host_alias": request.host_alias or request.host,
        "user": request.user,
    }


@app.post("/git/push")
def push_git(request: PushRequest) -> dict[str, object]:
    try:
        key_path = ensure_key_ready(request)
        mode = resolve_push_mode(request)
        if mode == "repo_dir":
            return push_existing_repo(request, key_path)
        return push_uploaded_files(request, key_path)
    except CommandError as exc:
        raise command_failure(exc) from exc

from __future__ import annotations

import base64
import binascii
import os
import re
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("GIT_API_DATA_DIR", ROOT_DIR / "data")).resolve()
KEYS_DIR = DATA_DIR / "keys"
SSH_HOME = Path(os.getenv("GIT_API_HOME", DATA_DIR / "home")).resolve()
WORKSPACE_ROOT = Path(
    os.getenv("GIT_API_WORKSPACE_ROOT", ROOT_DIR / "workspace")
).resolve()
DEFAULT_KEY_NAME = os.getenv("GIT_API_DEFAULT_KEY_NAME", "default")
KEY_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

SETUP_SCRIPT = ROOT_DIR / "setup_git_ssh.sh"
PUSH_SCRIPT = ROOT_DIR / "push_git.sh"


class SaveKeyRequest(BaseModel):
    email: str | None = None
    key_name: str = Field(default=DEFAULT_KEY_NAME)
    host: str = Field(default="github.com")
    host_alias: str | None = None
    user: str = Field(default="git")
    private_key: str = Field(min_length=1)


class PushRequest(BaseModel):
    repo_dir: str
    key_name: str = Field(default=DEFAULT_KEY_NAME)
    remote: str = Field(default="origin")
    branch: str | None = None
    repo: str | None = None
    remote_url: str | None = None
    host: str | None = None
    user: str = Field(default="git")
    allow_dirty: bool = False
    private_key: str | None = None


class CommandError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stdout: str, stderr: str):
        self.args_list = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(stderr or stdout or "command failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    SSH_HOME.mkdir(parents=True, exist_ok=True)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    bootstrap_key_from_env()
    yield


app = FastAPI(title="git-tools API", version="1.0.0", lifespan=lifespan)


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(SSH_HOME)
    return env


def run_command(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=command_env(),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
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


def build_setup_command(
    request: SaveKeyRequest | PushRequest, key_path: Path, require_existing_key: bool = True
) -> list[str]:
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


def write_private_key(key_path: Path, private_key: str) -> None:
    normalized = private_key.replace("\r\n", "\n").strip()
    key_path.write_text(f"{normalized}\n", encoding="utf-8")
    os.chmod(key_path, 0o600)
    public_key_path = key_path.with_suffix(f"{key_path.suffix}.pub")
    public_key = run_command(["ssh-keygen", "-y", "-f", str(key_path)]).stdout
    public_key_path.write_text(public_key, encoding="utf-8")
    os.chmod(public_key_path, 0o644)


def getenv_nonempty(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


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


def command_failure(exc: CommandError) -> HTTPException:
    detail = {
        "command": exc.args_list,
        "returncode": exc.returncode,
        "stdout": exc.stdout.strip(),
        "stderr": exc.stderr.strip(),
    }
    return HTTPException(status_code=400, detail=detail)


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
def push_git(request: PushRequest) -> dict[str, str]:
    key_path = key_path_for_name(request.key_name)
    repo_dir = resolve_repo_dir(request.repo_dir)
    if request.private_key:
        if not request.host:
            raise HTTPException(
                status_code=400,
                detail="host is required when private_key is provided in the push request",
            )
        try:
            write_private_key(key_path, request.private_key)
            save_request = SaveKeyRequest(
                email=None,
                key_name=request.key_name,
                host=request.host,
                host_alias=None,
                user=request.user,
                private_key=request.private_key,
            )
            run_command(
                build_setup_command(save_request, key_path, require_existing_key=True),
                cwd=ROOT_DIR,
            )
        except CommandError as exc:
            raise command_failure(exc) from exc

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

    try:
        completed = run_command(command, cwd=repo_dir)
    except CommandError as exc:
        raise command_failure(exc) from exc

    return {
        "repo_dir": str(repo_dir),
        "key_name": request.key_name,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }

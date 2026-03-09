# API Examples

## 启动服务并在启动时注入私钥

如果用户已经有可用私钥，优先用环境变量在容器启动时导入：

约定本地私钥路径为 `git-tools-api/key`，只用于本地导入，不要提交到仓库。

```bash
export GIT_API_INIT_PRIVATE_KEY_B64="$(base64 < git-tools-api/key | tr -d '\n')"
export GIT_API_INIT_HOST=github.com
export GIT_API_INIT_USER=git
docker compose up --build -d
```

如果宿主机 `8000` 已被占用：

```bash
GIT_API_PORT=18000 docker compose up --build -d
```

## 健康检查

```bash
curl http://127.0.0.1:8000/health
```

## 导入私钥

```bash
PRIVATE_KEY_JSON="$(python3 - <<'PY'
import json
from pathlib import Path

print(json.dumps(Path("git-tools-api/key").read_text(encoding="utf-8")))
PY
)"

curl -X POST http://127.0.0.1:8000/keys/import \
  -H 'Content-Type: application/json' \
  -d "{
    \"key_name\": \"default\",
    \"host\": \"github.com\",
    \"user\": \"git\",
    \"private_key\": ${PRIVATE_KEY_JSON}
  }"
```

## 直接推送文本文件

优先使用 `files` 模式，把目标分支的内容作为请求体传进去：

```bash
curl -X POST http://127.0.0.1:8000/git/push \
  -H 'Content-Type: application/json' \
  -d '{
    "key_name": "default",
    "host": "github.com",
    "repo": "owner/repo",
    "branch": "main",
    "commit_message": "Update via API",
    "files": [
      {
        "path": "README.md",
        "content": "# hello\n"
      },
      {
        "path": "scripts/deploy.sh",
        "content": "#!/usr/bin/env bash\necho ok\n",
        "executable": true
      }
    ]
  }'
```

## 推送二进制文件

使用 `content_b64`：

```bash
FILE_B64="$(base64 < ./logo.png | tr -d '\n')"

curl -X POST http://127.0.0.1:8000/git/push \
  -H 'Content-Type: application/json' \
  -d "{
    \"key_name\": \"default\",
    \"host\": \"github.com\",
    \"repo\": \"owner/repo\",
    \"branch\": \"main\",
    \"commit_message\": \"Add logo\",
    \"files\": [
      {
        \"path\": \"assets/logo.png\",
        \"content_b64\": \"${FILE_B64}\"
      }
    ]
  }"
```

## 一次请求同时导入私钥并推送

只有当用户明确希望一次调用完成时才使用这种形式：

```bash
curl -X POST http://127.0.0.1:8000/git/push \
  -H 'Content-Type: application/json' \
  -d '{
    "key_name": "default",
    "host": "github.com",
    "repo": "owner/repo",
    "branch": "main",
    "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----",
    "commit_message": "Update via API",
    "files": [
      {
        "path": "README.md",
        "content": "# hello\n"
      }
    ]
  }'
```

## 常见排查命令

```bash
docker compose ps
docker compose logs git-tools-api --tail=100
curl -s http://127.0.0.1:8000/health
```

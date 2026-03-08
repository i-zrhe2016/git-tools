# git-tools

一个通过 API 执行 Git SSH 推送的服务。

推荐用法是把私钥和仓库内容都传给 API，由容器内部完成暂存、提交和推送；不需要把待推送仓库挂载到宿主机目录再进入容器执行。

## 启动 API

```bash
docker compose up --build -d
```

服务默认监听 `8000`。

如果宿主机 `8000` 已被占用，可以改端口：

```bash
GIT_API_PORT=18000 docker compose up --build -d
```

私钥默认保存在：

```text
./data/keys/default.key
```

### 启动时通过容器环境变量导入 key

如果你已经把私钥写在当前目录的 `key` 文件里，推荐在启动前转成 base64，再透传给容器环境变量：

```bash
export GIT_API_INIT_PRIVATE_KEY_B64="$(base64 < key | tr -d '\n')"
export GIT_API_INIT_HOST=github.com
export GIT_API_INIT_USER=git
docker compose up --build -d
```

容器启动后会自动把私钥写入 `data/keys/default.key`，并生成对应的公钥文件。

可选环境变量：

- `GIT_API_INIT_KEY_NAME`：默认 `default`
- `GIT_API_INIT_HOST`：默认 `github.com`
- `GIT_API_INIT_HOST_ALIAS`：可选，写入 SSH config 的别名
- `GIT_API_INIT_USER`：默认 `git`
- `GIT_API_INIT_EMAIL`：可选，传给 `setup_git_ssh.sh`
- `GIT_API_INIT_PRIVATE_KEY`：直接传原始私钥文本
- `GIT_API_INIT_PRIVATE_KEY_B64`：传 base64 后的私钥，推荐

## API

### 1. 导入你的私钥到 key 文件

如果你不想在容器启动时注入私钥，也可以先调用 API 保存私钥：

```bash
curl -X POST http://127.0.0.1:8000/keys/import \
  -H 'Content-Type: application/json' \
  -d '{
    "key_name": "default",
    "host": "github.com",
    "user": "git",
    "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----"
  }'
```

这会把私钥写入 `data/keys/default.key`，并自动生成对应的 `.pub` 文件。

### 2. 直接把内容传给 API 并推送

`/git/push` 现在支持直接接收文件内容。服务会在容器内创建临时仓库，拉取远端分支（如果存在），覆盖写入你传入的文件，提交后再推送。

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

常用参数：

- `repo`：目标仓库路径，例如 `owner/repo`
- `remote_url`：直接指定完整 remote 地址；传了它就不需要 `repo`
- `branch`：目标分支；不传时默认 `main`
- `commit_message`：提交信息
- `author_name` / `author_email`：覆盖默认提交作者
- `delete_missing`：默认 `true`，表示这次请求里的文件集合会覆盖远端分支工作区
- `force_push`：使用 `--force-with-lease`
- `content_b64`：二进制文件或不方便直接传文本时可用

如果你想一次请求里同时带私钥，也可以直接在 `/git/push` 的请求体中加入 `private_key`。服务会先把私钥写到 `data/keys/<key_name>.key`，再执行推送。

### 3. 兼容旧模式：推送已存在仓库

如果你仍然想推送一个已经存在于容器工作目录内的仓库，`/git/push` 仍然支持 `repo_dir` 模式：

```bash
curl -X POST http://127.0.0.1:8000/git/push \
  -H 'Content-Type: application/json' \
  -d '{
    "repo_dir": "my-repo",
    "key_name": "default",
    "host": "github.com",
    "repo": "owner/repo"
  }'
```

这个模式下需要传 `repo_dir`，且不能和 `files` 同时出现。

## 健康检查

```bash
curl http://127.0.0.1:8000/health
```

## 注意

- 推荐通过 API 传文件内容，不要把真实私钥提交到代码仓库。
- `keys/import` 只保存你提供的现有私钥，不会生成新的私钥。
- 私钥只会写到挂载目录 `data/keys/`。

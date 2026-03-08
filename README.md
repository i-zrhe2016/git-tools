# git-tools

一个 Git SSH 辅助工具，现已补成一个可通过 `docker compose` 启动的 API 服务。

这个版本不生成密钥，使用你提供的私钥，并写入单独的 key 文件保存。

## 直接用脚本

```bash
./setup_git_ssh.sh --host github.com --key-path ./key --require-existing-key
./push_git.sh --host github.com --repo owner/repo --key-path ./key
```

不显式传 `--key-path` 时，两个脚本都会只读取当前目录下的 `./key`，不会再自动回退到 `~/.ssh/`。

## 启动 API

```bash
docker compose up --build -d
```

服务默认监听 `8000`，并挂载两个目录：

- `./data`：持久化 SSH 配置和私钥文件
- `./workspace`：放需要执行 `git push` 的仓库

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

如果你没有在容器启动时通过环境变量注入私钥，也可以在服务启动后调用 API：

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

这会把私钥写入 `data/keys/default.key`，并自动生成对应的 `.pub` 文件，不会生成新的私钥。

### 2. 执行 git push

先把目标仓库挂到 `./workspace`，例如容器内路径为 `/workspace/my-repo`，然后调用：

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

可选参数：

- `branch`：指定分支，不传则取当前分支
- `remote`：默认 `origin`
- `remote_url`：直接指定完整 remote 地址
- `allow_dirty`：允许工作区有未提交改动时继续推送

如果你想一步完成，也可以在 `git push` 请求里直接带 `private_key`，服务会先保存到 `data/keys/<key_name>.key`，再执行推送；这种用法需要同时传 `host`。

## 健康检查

```bash
curl http://127.0.0.1:8000/health
```

## 注意

- `keys/import` 用于保存你提供的现有私钥，不会自动生成新密钥。
- 不建议把真实私钥提交到代码仓库，私钥只会写到挂载目录 `data/keys/`。

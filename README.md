# git-tools

一个纯脚本的 Git SSH 提交工具集，不再依赖 Docker、API 或 Python 服务。

仓库里保留 4 个核心脚本：

- `setup_git_ssh.sh`：准备 SSH key 和 `~/.ssh/config`
- `commit_git.sh`：执行 `git add -A` 并创建提交
- `push_git.sh`：把当前分支推送到远端
- `submit_git.sh`：先提交再推送，一步完成

## 快速开始

### 1. 配置 SSH

首次使用先准备 SSH key：

```bash
./setup_git_ssh.sh --host github.com --email you@example.com
```

脚本会：

- 在当前目录生成默认私钥 `./key`
- 写入 `~/.ssh/config`
- 输出公钥内容，方便你添加到 GitHub / GitLab

如果你已经有私钥，也可以直接指定：

```bash
./setup_git_ssh.sh --host github.com --key-path ./key --require-existing-key
```

### 2. 提交代码

只提交，不推送：

```bash
./commit_git.sh --message "Update README"
```

不传 `--message` 时，脚本会交互式要求输入提交信息。

### 3. 推送代码

推送当前分支：

```bash
./push_git.sh
```

如果远端还没配置，也可以直接指定：

```bash
./push_git.sh --repo owner/repo --branch main
```

### 4. 一步提交并推送

推荐直接使用：

```bash
./submit_git.sh --message "Update README" --repo owner/repo --branch main
```

如果远端和分支已经配置好了，可以更短：

```bash
./submit_git.sh --message "Update README"
```

## 脚本说明

### `setup_git_ssh.sh`

常用参数：

- `--email`：写入 SSH 公钥注释
- `--key-path`：指定私钥路径，默认当前目录 `./key`
- `--host`：Git 服务地址，默认 `github.com`
- `--host-alias`：写入到 `~/.ssh/config` 的别名
- `--user`：SSH 用户，默认 `git`
- `--require-existing-key`：要求私钥必须已存在

### `commit_git.sh`

常用参数：

- `--message`：提交信息
- `--author-name`：覆盖本次提交作者名
- `--author-email`：覆盖本次提交作者邮箱
- `--allow-empty`：允许空提交

行为说明：

- 自动执行 `git add -A`
- 如果当前仓库没有配置 `user.name` / `user.email`，脚本会交互式要求输入作者信息
- 如果没有变更，会直接退出，不创建 commit
- 如果 `.env` 已被 Git 跟踪，会拒绝提交

### `push_git.sh`

常用参数：

- `--remote`：远端名，默认 `origin`
- `--branch`：分支名，默认当前分支
- `--repo`：仓库路径，例如 `owner/repo`
- `--remote-url`：直接指定完整 remote URL
- `--host`：Git 服务地址
- `--user`：SSH 用户
- `--key-path`：私钥路径，默认当前目录 `./key`

行为说明：

- 默认要求工作区干净
- 如果 `.env` 已被 Git 跟踪，会拒绝推送

### `submit_git.sh`

这是 `commit_git.sh` 和 `push_git.sh` 的组合封装。

你可以把提交参数和推送参数一起传进去，例如：

```bash
./submit_git.sh \
  --message "Release" \
  --author-name "deploy-bot" \
  --author-email "bot@example.com" \
  --repo owner/repo \
  --branch main
```

## 注意

- 这些脚本必须在目标 Git 仓库目录内执行。
- 默认私钥路径是当前仓库目录下的 `./key`。
- 不要把真实私钥或 `.env` 提交到代码仓库。

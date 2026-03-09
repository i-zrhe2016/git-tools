---
name: git-tools-api
description: Operate and troubleshoot the Dockerized git-tools API service in this repository. Use when Codex needs to 启动或检查这个基于 Docker Compose 的服务、调用 `/health` `/keys/import` `/git/push`、导入 SSH 私钥、通过 API 直接推送文件到 Git provider，或排查这个服务的 SSH 认证、known_hosts、remote、branch、staging 路径和 payload 错误。
---

# Git Tools API

## 概览

使用这个 skill 处理当前仓库里的 Docker 化 Git 推送服务。这个服务现在只保留 API-first 流程：启动容器，检查 `/health`，导入或注入私钥，然后调用 `/git/push` 的 `files` 模式。

## 先核对实现

- 当仓库可能刚改过时，先重新读取 `../../../docker-compose.yml`、`../../../README.md` 和 `../../../app/main.py`，不要假设接口行为没变。
- 记住这些当前实现约束：
  - 宿主机端口来自 `GIT_API_PORT`，默认 `8000`
  - 持久化目录是 `../../../data`
  - 临时仓库目录是 `data/staging/`
  - 默认 key 名是 `default`
  - 私钥写入 `data/keys/<key_name>.key`

## 标准流程

### 1. 启动并检查服务

- 运行 `docker compose up --build -d`
- 如果 `8000` 被占用，运行 `GIT_API_PORT=18000 docker compose up --build -d`
- 检查 `curl http://127.0.0.1:<port>/health`
- 需要排查容器问题时，查看 `docker compose ps` 和 `docker compose logs git-tools-api --tail=100`

### 2. 准备 SSH key

- 用户已经有私钥时，优先建议在容器启动前用 `GIT_API_INIT_PRIVATE_KEY_B64` 注入
- 运行中的服务优先调用 `POST /keys/import`
- 只有当用户明确想一次请求完成导 key 和 push 时，才在 `/git/push` body 里直接带 `private_key`
- 不要建议把真实私钥提交到仓库
- 明确说明这个服务只导入已有私钥，不生成新私钥

### 3. 优先使用 `files` 模式推送

- 默认使用 `POST /git/push` 加 `files`
- 让请求体包含 `repo` 或 `remote_url`
- `branch` 不传时默认 `main`
- 每个文件必须二选一：`content` 或 `content_b64`
- 二进制内容或不方便直写文本时，用 `content_b64`
- `delete_missing` 默认是 `true`，意味着这次请求里的文件集合会覆盖远端分支工作区；除非用户要完整覆盖，否则主动考虑是否要设为 `false`
- 只有用户明确要求强推时才设置 `force_push=true`

## 请求构造规则

### `/keys/import`

发送这些字段：
- `key_name`
- `host`
- `user`
- `private_key`

按需补充：
- `host_alias`
- `email`

### `/git/push` 的 `files` 模式

最常用字段：
- `key_name`
- `repo` 或 `remote_url`
- `branch`
- `commit_message`
- `files`

按需补充：
- `author_name`
- `author_email`
- `private_key`
- `delete_missing`
- `force_push`

## 排查策略

- 400 错误优先读取响应里的 `detail.command`、`detail.stdout`、`detail.stderr`；这个服务会把底层命令失败细节回传出来
- 遇到以下错误时直接按实现含义处理：
  - `Field required` 或 `too_short`: `files` 缺失或为空
  - `repo or remote_url is required`: 没有提供远端
  - `file ... must set exactly one of content or content_b64`: 文件内容字段冲突
  - `key_name only allows ...`: key 名非法
  - `extra_forbidden`: 请求体还在传旧字段，例如 `repo_dir`、`allow_dirty` 或 `remote`
- SSH 相关报错通常优先检查：
  - 私钥内容是否正确
  - 公钥是否已加到 Git provider
  - `host` 或 `user` 是否匹配
  - `known_hosts` 是否已由 `keys/import` 或启动注入流程正确生成
  - 远端地址是否是预期仓库
- 如果用户反馈文件被意外删除，先检查是否使用了默认的 `delete_missing=true`

## 参考资料

- 需要可直接复用的 `curl` 模板时，读取 `references/api-examples.md`

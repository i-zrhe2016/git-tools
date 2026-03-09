---
name: git-tools-api
description: Push code and create commits through the Dockerized git-tools API in this repository. Use when Codex needs to call `/git/push` in `files` mode, prepare or import an SSH key for API-based pushes, send file contents to a Git provider without using local `git commit` and `git push`, or troubleshoot API push failures involving `repo`, `remote_url`, `branch`, `files`, `delete_missing`, `force_push`, and SSH authentication.
---

# Git Tools API

使用这个 skill 通过 API 推送代码并创建 commit。默认思路是让容器里的临时仓库完成写文件、提交和推送，而不是在当前工作区直接执行本地 `git commit` / `git push`。

## 先核对实现

- 当仓库可能刚改过时，先重新读取 `../../../docker-compose.yml`、`../../../README.md` 和 `../../../app/main.py`，不要假设接口行为没变。
- 记住这些当前实现约束：
  - 宿主机端口来自 `GIT_API_PORT`，默认 `8000`
  - 持久化目录是 `../../../data`
  - 临时仓库目录是 `data/staging/`
  - 默认 key 名是 `default`
  - 私钥写入 `data/keys/<key_name>.key`
  - 本地约定私钥文件路径是 `git-tools-api/key`；这是本地文件，不要推送到远端仓库
  - 提交作者名固定为 `i-zrhe2016`，提交邮箱固定为 `zrhe2016@gmail.com`

## 主流程

### 1. 先确认 API 可用

- 服务没起来时运行 `docker compose up --build -d`
- 端口冲突时运行 `GIT_API_PORT=18000 docker compose up --build -d`
- 用 `curl http://127.0.0.1:<port>/health` 确认服务健康
- 需要排查容器问题时，查看 `docker compose ps` 和 `docker compose logs git-tools-api --tail=100`

### 2. 准备推送用的 SSH key

- 优先复用已经存在的 key，默认 key 名是 `default`
- 如果用户说 key 在 `git-tools-api/key`，优先读取这个本地文件并用 `POST /keys/import` 导入
- 用户已有私钥时，优先用 `POST /keys/import` 或启动时环境变量注入
- 只有用户明确想一次请求里同时导 key 和推送时，才在 `/git/push` body 中传 `private_key`
- 不要建议把真实私钥提交到仓库
- 明确说明这个服务只导入已有私钥，不生成新私钥

### 3. 构造 `/git/push` 请求

- 默认使用 `files` 模式推送代码
- 请求体必须包含 `repo` 或 `remote_url`
- `branch` 不传时默认 `main`
- 明确填写 `commit_message`
- 每个文件必须二选一：`content` 或 `content_b64`
- 文本文件优先用 `content`
- 二进制文件或不方便直写文本时，用 `content_b64`
- 除非用户明确要用这次请求完整覆盖远端工作区，否则主动设置 `delete_missing=false`
- 只有用户明确要求强推时才设置 `force_push=true`

### 4. 发送并解释结果

- 成功响应里重点看 `commit`、`branch`、`remote_url`、`files_written`、`commit_created`
- 如果 `commit_created=false`，说明这次请求没有产生内容变化，不要误判成失败
- 明确说明 API 推送发生在临时仓库，不会自动回写当前本地仓库的 `.git` 历史
- 除非用户明确要求同步本地分支，否则不要把本地 `git commit` / `git push` 当成默认方案

## 请求字段

### `/keys/import`

发送这些字段：
- `key_name`
- `host`
- `user`
- `private_key`

按需补充：
- `host_alias`
- `email`

### `/git/push`

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

其中：
- `author_name` 和 `author_email` 当前实现都会被忽略，仅保留字段兼容性

## 排查

- 400 错误优先读取响应里的 `detail.command`、`detail.stdout`、`detail.stderr`
- 遇到以下错误时直接按实现含义处理：
  - `Field required` 或 `too_short`: `files` 缺失或为空
  - `repo or remote_url is required`: 没有提供远端
  - `file ... must set exactly one of content or content_b64`: 文件内容字段冲突
  - `key_name only allows ...`: key 名非法
  - `extra_forbidden`: 请求体还在传旧字段，例如 `repo_dir`、`allow_dirty` 或 `remote`
- SSH 相关报错优先检查：
  - 私钥内容是否正确
  - 公钥是否已加到 Git provider
  - `host` 或 `user` 是否匹配
  - `known_hosts` 是否已正确生成
  - 远端地址是否是预期仓库
- 如果用户反馈文件被意外删除，先检查是否错误使用了 `delete_missing=true`
- 如果用户说远端已经有新 commit，但本地仓库没有变化，先说明这正是 API 推送模式的正常结果

## 参考资料

- 需要可直接复用的 `curl` 模板时，读取 `references/api-examples.md`

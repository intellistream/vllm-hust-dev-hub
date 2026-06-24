# 代码合入操作指南（Fork Branch + PR 模式）

> **声明：** 本指南仅供团队内部参考，内容可能随项目演进而过时。欢迎所有贡献者一起完善——如果你发现描述不准确、遗漏或可以改进的地方，请直接提 PR 修改本文档。

本指南适用于向 vLLM-HUST 组织下的代码仓库提交代码。我们采用 **"Fork 分支，不 Fork 仓库"** 的协作模式：在组织仓库内创建特性分支，通过 Pull Request 合入 `main`。

---

## 目录

1. [核心概念](#1-核心概念)
2. [一次性环境准备](#2-一次性环境准备)
3. [分支命名规范](#3-分支命名规范)
4. [日常开发流程（Step by Step）](#4-日常开发流程step-by-step)
5. [保持 Work Tree 干净](#5-保持-work-tree-干净)
6. [创建 Pull Request](#6-创建-pull-request)
7. [PR 合入后的清理](#7-pr-合入后的清理)
8. [常见问题排查](#8-常见问题排查)
9. [速查表](#9-速查表)

---

## 1. 核心概念

```
┌──────────────────────────────────────────────────────────────┐
│  GitHub: vLLM-HUST/vllm-hust  (origin)                      │
│                                                              │
│   main ◄─── alice/fix-xxx-20260603   (PR #42)               │
│         ◄─── bob/feat-yyy-20260604   (PR #43)               │
└──────────────────────────────────────────────────────────────┘
        ▲ clone / fetch / push
        │
┌──────────────────────────────────────────────────────────────┐
│  本地: ~/workspace/vllm-hust                                 │
│                                                              │
│   main (只用于 sync，不直接修改)                               │
│   alice/fix-xxx-20260603  (你的开发分支)                      │
└──────────────────────────────────────────────────────────────┘
```

**核心原则：**
- `main` 分支 **只用于同步**，永远不在 `main` 上直接提交
- 每个任务一个独立分支，分支名包含 **GitHub ID 前缀 / 类型 / 简述 / 日期**
- 使用 GitHub ID 作为分支前缀，避免不同用户之间的分支名冲突
- 所有变更通过 PR 合入，禁止直接 push 到 `main`

---

## 2. 一次性环境准备

### 2.1 克隆 dev-hub 并初始化环境

我们使用 `vllm-hust-dev-hub` 作为统一的开发入口，它包含工作区配置和初始化脚本。

```bash
git clone https://github.com/vLLM-HUST/vllm-hust-dev-hub.git
cd vllm-hust-dev-hub

# 运行 quickstart 脚本，自动配置 workspace 代码仓及开发环境
bash scripts/quickstart.sh
```

> `quickstart.sh` 会自动完成：克隆各 workspace 代码仓、配置 git remote、设置 Python 虚拟环境等。完成后切换到目标代码仓目录继续开发。

### 2.2 推荐的全局 / 仓库级 Git 配置

进入你的目标代码仓目录（例如 `vllm-hust`）后执行：

```bash
cd vllm-hust   # 或你的目标仓库目录

# ---- 推荐在仓库级设置（只影响当前仓库）----

# pull 时默认 rebase，避免产生多余的 merge commit
git config pull.rebase true

# 自动设置上游跟踪
git config branch.autoSetupMerge true

# fetch 时自动清理已删除的远程分支引用
git config fetch.prune true

# 推送时只推送当前分支
git config push.default current
```

### 2.3 配置 Git 身份

```bash
# 仓库级（推荐，不影响全局配置）
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

### 2.4 验证配置

```bash
git remote -v
# 预期输出：
# origin  git@github.com:vLLM-HUST/vllm-hust.git (fetch)
# origin  git@github.com:vLLM-HUST/vllm-hust.git (push)

git config --get pull.rebase    # 预期: true
git config --get fetch.prune    # 预期: true
```

---

## 3. 分支命名规范

格式：`<github-id>/<type>-<short-desc>-<YYYYMMDD>`

| 字段 | 说明 | 示例 |
|------|------|------|
| `<github-id>` | 你的 GitHub 用户名 | `alice`, `bob`, `zhangsan` |
| `<type>` | 变更类型 | `fix`, `feat`, `hotfix`, `refactor`, `docs`, `bench`, `ci` |
| `<short-desc>` | 简短描述，用 `-` 连接 | `ascend-summary-fallback` |
| `<YYYYMMDD>` | 创建日期 | `20260603` |

> **为什么用 GitHub ID 作为前缀？** 多人协作时，不同开发者可能同时开发类似功能。使用 GitHub ID 作为分支名前缀，可以确保每个人的分支命名空间互不冲突，也方便在 `git branch -a` 输出中快速识别分支归属。

**示例（假设你的 GitHub ID 是 `alice`）：**
```
alice/fix-ascend-summary-model-fallback-20260602
alice/feat-add-kv-cache-metric-20260603
alice/hotfix-precommit-main-20260601
alice/refactor-scheduler-dispatch-20260604
```

> **为什么用日期后缀？** 避免同一人同时开发同类功能时分支名冲突，也方便按时间排序。

---

## 4. 日常开发流程（Step by Step）

### Step 1: 同步 main 到最新

**每次开始新任务前，务必先同步。**

```bash
# 切回 main
git checkout main

# 拉取最新（如果有 upstream）
git fetch origin --prune
git fetch upstream --prune    # 如果有 upstream

# 将 main 重置为远程最新，丢弃本地 main 上可能的脏改动
git reset --hard origin/main
```

> **为什么用 `reset --hard`？** 因为 `main` 不应该有任何本地修改。如果 reset 丢失了内容，说明你之前在 main 上做了不该做的修改。

### Step 2: 创建特性分支

```bash
# 从最新的 main 创建并切换到新分支
git checkout -b alice/fix-your-bug-description-20260603
```

### Step 3: 开发 & 提交

```bash
# 查看当前状态，确认在正确的分支上
git status
git branch --show-current

# 编辑文件...
# 暂存变更（推荐逐个文件 add，不要 git add .）
git add path/to/modified_file.py
git add path/to/new_file.py

# 提交（写清晰的 commit message）
git commit -m "fix: resolve model fallback issue on Ascend NPU

Detailed description of what changed and why.

Fixes: #<issue_number>

Signed-off-by: Your Name <your.email@example.com>"
```

**Commit message 规范：**
- 第一行：`<type>: <简短描述>`（50 字符以内）
- 空行
- 正文：解释 what & why（不是 how）
- 如果有 AI 辅助，加上 `Co-authored-by:` 标签
- 加上 `Signed-off-by:` 表示同意 DCO

### Step 4: 推送分支到远程

```bash
# 首次推送，设置上游跟踪
git push -u origin alice/fix-your-bug-description-20260603

# 后续推送（已经设置过 upstream 后）
git push
```

### Step 5: 创建 Pull Request

见 [第 6 节](#6-创建-pull-request)。

### Step 6: 响应 Review 意见

```bash
# 确保在正确的分支上
git checkout alice/fix-your-bug-description-20260603

# 修改代码后追加提交
git add <files>
git commit -m "fix: address review comments"
git push

# 如果 main 在你开发期间有新提交，rebase 你的分支
git fetch origin
git rebase origin/main
git push --force-with-lease    # 比 --force 更安全
```

> **为什么用 `--force-with-lease` 而不是 `--force`？** 它会检查远程分支是否被其他人更新过，如果别人也推了这个分支，会拒绝你的 force push，避免覆盖别人的提交。

---

## 5. 保持 Work Tree 干净

"Dirty work tree" 是指工作目录里有未预期的修改，是协作中最常见的事故来源。以下是防护规则：

### 规则 1: 永远不在 main 上开发

```bash
# ❌ 错误
git checkout main
vim some_file.py   # 直接在 main 上改

# ✅ 正确
git checkout main
git reset --hard origin/main    # 先同步
git checkout -b alice/fix-xxx-20260603   # 再建分支
vim some_file.py   # 在分支上改
```

### 规则 2: 切换分支前先处理当前改动

```bash
# 切换分支前检查状态
git status

# 如果有未提交的改动，三种处理方式：

# 方式 A: 提交（如果改动是完整的）
git commit -am "WIP: partial work"

# 方式 B: 暂存（如果改动还没做完）
git stash push -m "WIP: description"
# 之后恢复：
git stash pop

# 方式 C: 丢弃（如果改动是误操作）
git checkout -- .
git clean -fd    # 删除未跟踪文件（谨慎使用）
```

### 规则 3: 切换分支后验证

```bash
# 切到目标分支后，立刻确认状态
git checkout alice/fix-xxx-20260603
git status       # 应该是 clean 的
git log --oneline -3   # 确认在正确的提交上
```

### 规则 4: 不要用 `git add .` 或 `git add -A`

```bash
# ❌ 可能把不该提交的文件加进来
git add .

# ✅ 明确指定文件
git add vllm/model_executor/models/ascend_model.py
git add tests/test_ascend_model.py
```

### 规则 5: 定期清理

```bash
# 查看本地所有分支
git branch

# 删除已合入的本地分支
git branch -d alice/fix-already-merged-20260501

# 强制删除未合入的本地分支（确认不需要后）
git branch -D alice/fix-abandoned-20260501

# 批量清理已合入远程分支的本地跟踪分支
git fetch --prune
git branch --merged main | grep -v 'main' | xargs git branch -d
```

---

## 6. 创建 Pull Request

### ⚠️ 安全创建 PR（重要！）

`vLLM-HUST/vllm-hust` 是 `vllm-project/vllm` 的 fork。GitHub 在通过短链接创建 PR 时，可能默认指向 **上游仓库** 而非组织仓库，导致 PR 发错地方。

**必须使用以下安全方式之一：**

#### 方式 A: GitHub URL 模板（推荐）

```
https://github.com/vLLM-HUST/vllm-hust/compare/main...vLLM-HUST:<branch>?expand=1
```

将 `<branch>` 替换为你的分支名，例如：
```
https://github.com/vLLM-HUST/vllm-hust/compare/main...vLLM-HUST:alice/fix-ascend-summary-model-fallback-20260602?expand=1
```

#### 方式 B: GitHub CLI

```bash
gh pr create \
  --repo vLLM-HUST/vllm-hust \
  --base main \
  --head alice/fix-your-bug-description-20260603 \
  --title "fix: resolve model fallback issue on Ascend NPU" \
  --body "## What
Describe what this PR changes.

## Why
Describe why this change is needed.

## Test
Describe how you tested this change.

Fixes: #<issue_number>

Signed-off-by: Your Name <your.email@example.com>"
```

#### ❌ 不要使用短链接

```
# 这个链接可能指向 vllm-project/vllm，不要用！
https://github.com/vLLM-HUST/vllm-hust/pull/new/<branch>
```

### PR 描述模板

```markdown
## What
<!-- 简述这个 PR 做了什么 -->

## Why
<!-- 解释为什么需要这个变更 -->

## Test
<!-- 描述你做了哪些测试，附上命令和结果 -->

## Checklist
- [ ] PR 标题遵循 commit message 规范
- [ ] 已本地运行测试通过
- [ ] 已运行 lint 检查通过
- [ ] 如有 AI 辅助，已在 commit 中声明
- [ ] 不是重复 PR（已检查现有 PR 和 issue）
```

---

## 7. PR 合入后的清理

PR 被 merge 后，及时清理本地和远程分支：

```bash
# 1. 切回 main 并同步
git checkout main
git fetch origin --prune
git reset --hard origin/main

# 2. 删除本地特性分支
git branch -d alice/fix-your-bug-description-20260603

# 3. 删除远程特性分支（如果 GitHub 没有自动删除）
git push origin --delete alice/fix-your-bug-description-20260603

# 4. 验证状态
git status              # 应该是 clean，在 main 上
git branch              # 特性分支应该已消失
git worktree list       # 如果使用了 worktree，确认没有残留
```

---

## 8. 常见问题排查

### Q: 我不小心在 main 上做了提交怎么办？

```bash
# 如果还没 push：
git branch alice/rescue-my-commits-20260603   # 把当前提交保存到临时分支
git reset --hard origin/main                # 恢复 main

# 如果已经 push 了：
# 1. 创建新分支保存提交
git branch alice/rescue-my-commits-20260603
# 2. 在 GitHub 上删除远程 main 上的错误提交（需要 force push，联系负责人协助）
```

### Q: 我的分支和 main 冲突了怎么办？

```bash
git checkout alice/fix-your-bug-description-20260603
git fetch origin
git rebase origin/main

# 解决冲突...
git add <resolved-files>
git rebase --continue

# 推送（需要 force-with-lease 因为 rebase 改写了历史）
git push --force-with-lease
```

### Q: 我想在已有分支上继续新工作怎么办？

```bash
# 如果新工作和旧任务相关，可以继续在同一分支追加
git checkout alice/fix-existing-branch-20260601
# ... 继续开发 ...

# 如果新工作是独立的，从最新 main 创建新分支
git checkout main
git reset --hard origin/main
git checkout -b alice/new-task-20260603
```

### Q: `git status` 显示有未跟踪文件，怎么处理？

```bash
# 查看有哪些未跟踪文件
git status

# 如果是构建产物（通常已在 .gitignore 中），可以忽略
# 如果是不该存在的文件：
git clean -fd        # 删除未跟踪文件和目录
git clean -fdx       # 同时删除被 .gitignore 忽略的文件（谨慎使用）
```

### Q: 我怎么确认 PR 没有发错仓库？

在 PR 页面检查：
1. 页面顶部应该显示 `vLLM-HUST/vllm-hust`，不是 `vllm-project/vllm`
2. base 分支应该是 `main`
3. 用 `gh pr view` 确认：
   ```bash
   gh pr view --repo vLLM-HUST/vllm-hust <PR_NUMBER>
   ```

---

## 9. 速查表

```
┌─────────────────── 每日流程 ───────────────────┐
│                                                │
│  1. git checkout main                          │
│  2. git fetch origin --prune                   │
│  3. git reset --hard origin/main               │
│  4. git checkout -b <github-id>/<type>-<desc>-<date> │
│  5. ... 开发 ...                                │
│  6. git add <files>                            │
│  7. git commit -m "type: message"              │
│  8. git push -u origin <branch>                │
│  9. 用安全链接创建 PR                            │
│ 10. 响应 review → amend/rebase → push          │
│ 11. PR merge 后清理分支                         │
│                                                │
└────────────────────────────────────────────────┘

┌─────────────── 防脏三件套 ─────────────────────┐
│                                                │
│  切分支前:  git status                         │
│  切分支后:  git status && git log --oneline -3 │
│  提交之前:  git diff --cached                  │
│                                                │
└────────────────────────────────────────────────┘

┌─────────────── 安全推送 ───────────────────────┐
│                                                │
│  普通推送:  git push                           │
│  Rebase后:  git push --force-with-lease        │
│  绝不用:    git push --force (除非你完全清楚)    │
│  绝不用:    git push origin main               │
│                                                │
└────────────────────────────────────────────────┘
```

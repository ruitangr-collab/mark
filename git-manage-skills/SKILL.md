---
name: git-manage-skills
description: >-
  将 WorkBuddy 技能目录（~/.workbuddy/skills 或 <workspace>/.workbuddy/skills）用 git
  统一管理并推送到远程仓库的标准流程。覆盖：检查既有仓库、拍平嵌套 .git、编写防密钥
  .gitignore、生成技能索引 README、提交，以及处理最常见的 GitHub 凭证冲突（HTTPS 令牌
  只读 / SSH deploy key 可写）。当用户说"把技能用 git 管起来 / 远程备份技能 / 推技能到
  GitHub / 以后远程调用技能"时触发。
agent_created: true
---

# git-manage-skills

把 WorkBuddy 技能做成可版本控制、可远程克隆的单一 git 仓库。

## 触发场景
- "把你的技能用 git 管理起来"
- "推技能到 GitHub / 远程备份技能"
- "以后想远程调用这些技能"

## 标准流程

### 1. 勘察现状（不要上来就 init）
- `ls -la ~/.workbuddy/skills/` 看是否已是 git 仓库（可能有 `.git` 但未提交全）。
- `git -C ~/.workbuddy/skills status / branch -a / remote -v / log --oneline` 看状态。
- 查 `git config --global --list` 与仓库级 `user.email`——**git 全局常常没配 email**，
  提交前必须在仓库级设 `user.name` + `user.email`（无 email 提交会失败）。
- 扫描疑似密钥文件：`find . -iname '*.env' -o -iname '*secret*' -o -iname '*token*'`，
  确认无密钥再提交。

### 2. 拍平嵌套仓库
- 技能目录里可能套着自己的 `.git`（如 `douyin-live-monitor/.git`）。直接 `git add` 只会
  加成一个 gitlink，不会并进主仓库。
- 处理：`rm -rf <skill>/.git` 拍平成普通子目录（文件不丢，只丢那份独立历史）。属轻微破坏性，
  先告知用户。

### 3. 重写 .gitignore（防密钥 / 运行时垃圾）
至少包含：
```
.DS_Store
__pycache__/  *.pyc  *.egg-info/  dist/  build/
node_modules/
.env  .env.*
*session*.json   *.cache/
*.db  *.db-journal  livescope.db
*.log  logs/  tmp/  temp/
topic_report_*.md  last_*_result.txt
douyin-live-monitor/~
```
提交前 `git add -A` 后 `git diff --cached --name-only | grep -E '\.(db|db-journal)$|~|tiny\.pt'` 复核无垃圾。

### 4. 提交
- 建议分两步：先单独提交 `.gitignore`，再 `git add -A` 提交全部技能（历史更清晰）。
- 提交身份用仓库级：`git config user.name edwardg` / `git config user.email edwardg@users.noreply.github.com`
  （隐私邮箱，不暴露真实邮箱）。

### 5. 生成 README 索引（便于远程 clone 后使用）
- 写脚本遍历每个 `<skill>/SKILL.md` 的 YAML frontmatter，抽取 `name` / `description`，
  按前缀归类（dbs*/douyin*/xhs*/ima*/marketing*/other），生成 `README.md` 表格 + 远程安装说明。
- 注意清洗描述里的前导 `>` / `|` 字符。

### 6. 推送到远程（重点：凭证冲突）
**本机常见坑**：git 走 `osxkeychain`，HTTPS 令牌账号（如 `coverme128`）对目标仓库可能只有
【读】权限，push 会 `403 Permission denied`。而真正能写的是 **SSH deploy key**。

排查：
```
git ls-remote <https-url>          # 能读说明可达
ssh -T git@github.com             # 看返回的 "Hi <who>!" 判断 SSH 身份
git config --get-all --show-scope credential.helper   # 确认 osxkeychain
```
若 SSH 身份对仓库可写（返回 `Hi <owner>/<repo>!` 或对应账号）：
```
git remote set-url origin git@github.com:<owner>/<repo>.git   # 切 SSH
git push -u origin main --force-with-lease
```
- **优先用 `--force-with-lease`**（只覆盖刚 fetch 到的版本，远程被别人改过会拒绝，不会盲目强推）。
- 若远程已有分叉历史且用户确认要覆盖（代码无损），才强推。
- 若 SSH 也无写权限：让用户把当前账号加为仓库 collaborator（write），或提供有 `repo` 权限的
  PAT / 改用有写权限的 SSH key。

## 验证
`git rev-parse main origin/main` 两者一致即成功；`git ls-tree --name-only origin/main` 抽查远程根目录。

## 注意
- 远程非空（已有旧 commit）时普通 push 会被拒，必须先 fetch 看清历史再决定 merge / 强推。
- 不要把 `.env`、session、cookie、密钥文件提交进仓库。

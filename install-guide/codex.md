# 即梦短剧 Codex 插件安装指引（Jimeng Drama v1.0.11）

请按以下顺序为用户完成安装与校验。安装和验证过程仅做只读检查，不要提交任何扣费生成任务。

## 1. 安装或更新 `jimeng-novel` CLI

1. 检查基础环境：确认已安装 Node.js 18+（`node -v`）与 Python 3.10+（`python3 --version`），并检查当前是否已有 `jimeng-novel`（`METRICS_LOG_LEVEL=none jimeng-novel --version`）。
2. 若未安装或版本过旧，请执行以下命令安装或更新：
   - 推荐 · 跨平台 npm 安装（macOS / Linux / Windows，需 Node.js 18+）：
     ```bash
     npm install -g 'https://lf3-static.bytednsdoc.com/obj/eden-cn/psj_slcvu_hupthlyk/ljhwZthlaukjlkulzlp/jimeng-novel/versions/1.0.11/scm-1.0.0.424/general/jimeng-novel-1.0.11-dev.afb84393b7ee.tgz'
     ```
   - 备选 · macOS / Linux 一键安装脚本（自动隔离散装 Skill，不写入 `~/.agents/skills` 与 `~/.codex/skills`，避免与 Codex 插件重复加载）：
     ```bash
     (set -o pipefail; curl -fsSL https://jimeng.jianying.com/novel-cli | bash -s -- --skills-dir "$HOME/.local/share/jimeng-novel/standalone-skills")
     ```
3. 检查命令解析路径（macOS / Linux 执行 `command -v jimeng-novel`，Windows 执行 `where.exe jimeng-novel`），确认未被 `~/.local/bin/jimeng-novel` 旧入口遮蔽，再运行 `METRICS_LOG_LEVEL=none jimeng-novel --version` 核对版本。

## 2. 注册插件市场并安装插件

1. 通过 Codex CLI 添加市场并安装插件：

   ```bash
   codex plugin marketplace add https://github.com/Jeislu/jimeng-novel-plugin --ref main --json
   codex plugin add jimeng-drama@jimeng-plugins --json
   ```

   - 如果本地已注册过 `jimeng-plugins`，先执行 `codex plugin marketplace upgrade jimeng-plugins` 更新市场后再执行 `codex plugin add jimeng-drama@jimeng-plugins`。
2. 清理历史散装 Skill 软链接（仅删除 `~/.agents/skills` 与 `$CODEX_HOME/skills` 下由旧安装器创建、指向 `~/.local/share/jimeng-novel/releases/` 的软链接，绝不删除用户自建目录）：

   ```bash
   python3 -c 'import os; from pathlib import Path; rel = (Path.home() / ".local/share/jimeng-novel/releases").resolve(); dirs = [Path.home() / ".agents/skills", Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills"]; [p.unlink() for d in dirs for n in ("jimeng-drama", "jimeng-short-drama") for p in (d / n,) if p.is_symlink() and p.resolve().name == n and p.resolve().parent.name == "skills" and p.resolve().parent.parent.parent == rel]'
   ```

## 3. 授权即梦账号

1. 运行 `METRICS_LOG_LEVEL=none jimeng-novel status` 检查登录状态；若已登录可直接进入第 4 步。
2. 若未登录，查看 `jimeng-novel login --help` 发起非交互式登录，获取官方授权链接（`jimeng.jianying.com`）。在浏览器打开并向用户发送可点击链接，随后执行 CLI 返回的等待命令直至授权完成。

## 4. 零扣费只读验证

1. 运行以下只读命令核对账号与模型列表（不消耗积分）：
   ```bash
   METRICS_LOG_LEVEL=none jimeng-novel account get
   METRICS_LOG_LEVEL=none jimeng-novel model list --type image
   ```
2. 验证通过后告知用户安装完成，并提醒用户**新建一个 Codex 对话**以加载 `jimeng-drama` 插件 Skill。

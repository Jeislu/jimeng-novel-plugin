# Jimeng Drama — Codex Plugin

Version: `1.0.11`

Official Codex plugin packaging the `jimeng-drama` workflow skill for the `jimeng-novel` CLI.

## Option 1: Single-Prompt Install in Codex (Recommended)

Publish `install-guide/codex.html` (or `install-guide/codex.md`) to your static host, then send Codex:

```text
Read jeislu.github.io/jimeng-novel-plugin/ to install the Jimeng Drama plugin
```

## Option 2: Install via Codex CLI

```bash
# 1. Install jimeng-novel CLI (Node.js 18+, Python 3.10+; isolates standalone skills from Codex)
(set -o pipefail; curl -fsSL https://jimeng.jianying.com/novel-cli | bash -s -- --skills-dir "$HOME/.local/share/jimeng-novel/standalone-skills")

# 2. Add this marketplace and install the plugin
codex plugin marketplace add https://github.com/Jeislu/jimeng-novel-plugin --ref main
codex plugin add jimeng-drama@jimeng-plugins

# 3. (If previously installed via bare script) Clean up old installer-managed standalone skill symlinks
python3 -c 'import os; from pathlib import Path; rel = (Path.home() / ".local/share/jimeng-novel/releases").resolve(); dirs = [Path.home() / ".agents/skills", Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills"]; [p.unlink() for d in dirs for n in ("jimeng-drama", "jimeng-short-drama") for p in (d / n,) if p.is_symlink() and p.resolve().name == n and p.resolve().parent.name == "skills" and p.resolve().parent.parent.parent == rel]'

# 4. Authorize your Jimeng account
jimeng-novel login
jimeng-novel status
```

Start a new Codex session after installing so the plugin skills are discovered.

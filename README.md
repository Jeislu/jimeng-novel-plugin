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
# 1. Install jimeng-novel CLI (Node.js 18+, Python 3.10+)
(set -o pipefail; curl -fsSL https://jimeng.jianying.com/novel-cli | bash)

# 2. Add this marketplace and install the plugin
codex plugin marketplace add https://github.com/Jeislu/jimeng-novel-plugin --ref main
codex plugin add jimeng-drama@jimeng-plugins

# 3. Authorize your Jimeng account
jimeng-novel login
jimeng-novel status
```

Start a new Codex session after installing so the plugin skills are discovered.

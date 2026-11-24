# Install Jimeng Drama Plugin for Codex (v1.0.11)

Follow these steps in order to install and verify the plugin for the user. Do not submit any paid generation jobs during installation or verification.

## Step 1: Ensure `jimeng-novel` CLI is installed

1. Check prerequisites: Node.js 18+ (`node -v`), Python 3.10+ (`python3 --version`), and check whether `jimeng-novel` is already available (`METRICS_LOG_LEVEL=none jimeng-novel --version`).
2. If `jimeng-novel` is missing or outdated, install or upgrade it using:
   - macOS / Linux standalone installer:
     ```bash
     (set -o pipefail; curl -fsSL https://jimeng.jianying.com/novel-cli | bash)
     ```
3. Verify the active binary path (`command -v jimeng-novel` on macOS/Linux or `where.exe jimeng-novel` on Windows) so an older `~/.local/bin/jimeng-novel` launcher does not shadow the newly installed binary, then confirm `METRICS_LOG_LEVEL=none jimeng-novel --version` succeeds.

## Step 2: Register the Codex Plugin Marketplace & Install the Plugin

Run these commands via Codex CLI:

```bash
codex plugin marketplace add https://github.com/Jeislu/jimeng-novel-plugin --ref main --json
codex plugin add jimeng-drama@jimeng-plugins --json
```

- If `jimeng-plugins` is already registered, refresh it with `codex plugin marketplace upgrade jimeng-plugins` and re-run `codex plugin add jimeng-drama@jimeng-plugins`.

## Step 3: Authorize Jimeng Account

1. Run `METRICS_LOG_LEVEL=none jimeng-novel status`.
2. If already logged in, skip to Step 4.
3. If not logged in, check `jimeng-novel login --help` and start non-interactive login to obtain the official authorization URL (`jimeng.jianying.com`). Open the URL in the browser and share the clickable link with the user, then run the wait command returned by the CLI until authorization completes.

## Step 4: Verify Without Spending Credits

1. Run read-only checks:
   ```bash
   METRICS_LOG_LEVEL=none jimeng-novel account get
   METRICS_LOG_LEVEL=none jimeng-novel model list --type image
   ```
2. Tell the user installation is complete and remind them to **start a new Codex session** so the `jimeng-drama` plugin skills are loaded.

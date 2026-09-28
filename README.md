# NanoMaid

**A nano personal assistant living on a small VPS.** NanoMaid wraps the existing OpenCode V2 service in a private Telegram client and provides an approved, one-shot Colab code-verification path.

## Quick install

### Before you start

- Ubuntu 26.04 LTS, x86-64; run the installer as your normal user, not as root.
- OpenCode V2 must already be installed, configured with a model/provider, healthy, and bound to loopback.
- User-level systemd lingering must already be enabled. The installer will not use `sudo` or change lingering.
- At least 150 MiB of available RAM is required by the preflight check.
- Create a Telegram bot with BotFather. After configuration, disable group joining for the bot.

Clone NanoMaid and review the dry-run before installing:

```bash
git clone https://github.com/arinadi/nanomaid.git
cd nanomaid
./install.sh --dry-run
./install.sh
```

The installer uses pinned, user-local tools. It does not enter credentials or enable/start the service. It also changes the global OpenCode `shell` and `edit` permission policies to `ask`; this affects every client sharing that OpenCode configuration, including TUI and desktop.

In a real local terminal, configure the Telegram token, owner ID, and OpenCode password interactively. Never paste credentials or OAuth codes into Telegram or commit them:

```bash
~/.local/bin/nanomaid configure
```

Test the bot in the foreground. Wait for the bot and OpenCode to report ready, then press **Ctrl+C** before enabling the systemd service; do not run two Telegram pollers at once.

```bash
~/.local/bin/nanomaid start
```

After the foreground test succeeds and RAM headroom is safe, enable the service:

```bash
~/.local/bin/nanomaid enable
```

Check the service with `~/.local/bin/nanomaid status` and view logs with `journalctl --user -u nanomaid.service`.

## Supported target

- Ubuntu 26.04 LTS, x86-64
- OpenCode V2 already installed, authenticated, and configured with a model/provider
- A single Telegram owner; private chat only
- User-level `systemd` with lingering already enabled
- No Docker, public listener, or firewall changes

The installer pins Node.js, uv, the Telegram wrapper, and Google Colab CLI. It uses user-local tools only and does not require apt/sudo. It is safe to re-run and has dry-run/check modes. NPM lifecycle scripts are disabled; the pinned wrapper release includes a Linux SQLite prebuild, which is smoke-tested during validation. It does not install or configure OpenCode providers, store secrets in this repository, or publish a remote Git repository.

## Sequence diagrams

### Deployment

```mermaid
sequenceDiagram
    actor Admin as Operator
    participant GitHub
    participant VPS as Ubuntu VPS
    participant Installer as install.sh
    participant OpenCode as OpenCode V2
    participant Service as systemd user service

    Admin->>GitHub: Clone NanoMaid
    GitHub-->>Admin: Installer source
    Admin->>VPS: Run --dry-run, then install.sh
    VPS->>Installer: Check prerequisites and plan changes
    Installer->>OpenCode: Verify V2 version and loopback health
    OpenCode-->>Installer: Healthy
    Installer-->>VPS: Dry-run summary (no changes)
    Admin->>VPS: Run install.sh
    Installer->>VPS: Install pinned user-local tools
    Installer->>OpenCode: Set global shell/edit policy to ask
    Installer->>Service: Prepare unit (left disabled)
    Installer-->>Admin: Configure credentials locally
    Admin->>VPS: Configure and test NanoMaid in foreground
    VPS->>OpenCode: Check server readiness
    OpenCode-->>VPS: Ready
    Admin->>VPS: Stop foreground bot, then run nanomaid enable
    VPS->>Service: Enable and start NanoMaid
```

### Telegram request and OpenCode response

```mermaid
sequenceDiagram
    actor Owner
    participant Telegram
    participant Bot as NanoMaid
    participant OpenCode as OpenCode V2 API
    participant Provider as Configured model provider
    participant Helper as Colab verification helper
    participant CLI as Isolated Colab CLI
    participant Colab as Temporary Colab runtime

    Owner->>Telegram: Send a private-chat request
    Telegram->>Bot: Deliver update
    Bot->>OpenCode: Send request over loopback
    OpenCode->>Provider: Generate response
    Provider-->>OpenCode: Return model output
    OpenCode-->>Bot: Stream result
    Bot-->>Telegram: Send response
    Telegram-->>Owner: Display response

    opt OpenCode requests shell/edit permission
        OpenCode->>Bot: Permission request
        Bot->>Telegram: Ask owner for approval
        Telegram->>Owner: Show approval prompt
        Owner->>Telegram: Approve or reject
        Telegram->>Bot: Deliver decision
        Bot->>OpenCode: Submit permission decision
        OpenCode-->>Bot: Continue or cancel request
        Bot-->>Telegram: Send result
    end

    opt Owner requests one-shot code verification
        Owner->>Telegram: Request lint/build/test for a project
        Telegram->>Bot: Deliver verification request
        Bot->>OpenCode: Route request to OpenCode
        OpenCode->>Helper: Prepare archive and argv command plan
        Helper-->>OpenCode: Filtered manifest, SHA-256, exact commands
        OpenCode-->>Bot: Present plan and source-transfer notice
        Bot-->>Telegram: Show manifest, hash, commands, cost/policy warning
        Owner->>Telegram: Approve this job once
        Telegram->>Bot: One-time approval
        Bot->>OpenCode: Submit shell permission approval
        OpenCode->>Helper: Run approved job ID and archive hash
        Helper->>CLI: Check Colab usage and rate
        CLI-->>Helper: Confirm zero-cost usage
        alt Free use and policy checks pass
            Helper->>CLI: Create uniquely named temporary session
            CLI->>Colab: Allocate CPU or approved T4 session
            Helper->>CLI: Upload reviewed archive and job manifest
            CLI->>Colab: Transfer approved files and commands
            Colab->>Colab: Run approved argv commands only
            Colab-->>CLI: Complete verification and text log
            CLI->>Colab: Download result log
            Colab-->>CLI: Return text results
            CLI->>Colab: Stop temporary session
            Colab-->>CLI: Return stop status
            CLI->>CLI: Verify session stopped
            CLI-->>Helper: Return log and cleanup status
            Helper->>Helper: Delete local archive and job staging
            Helper-->>OpenCode: Return text logs
            OpenCode-->>Bot: Summarize verification result
            Bot-->>Telegram: Send text result
        else Cost or policy is paid or unclear
            Helper-->>OpenCode: Abort without creating a session
            OpenCode-->>Bot: Report verification was not run
            Bot-->>Telegram: Explain the check failed closed
        end
    end
```

Colab is for user-approved, one-shot code-verification checks only. CPU is the default; an optional T4 can be requested for a finite check when Colab allocates it and reports T4 hardware. NanoMaid requires zero paid-unit balance; a positive usage-rate meter by itself does not block a free allocation. No paid compute, TPU, high-memory runtime, Drive mount, persistent session, bot, web service, audio/image/video, or unrelated datasets. Only reviewed source files and exact argv commands are sent to Google. Free GPU availability is dynamic and not guaranteed; if T4 is not allocated, the job stops.

## Colab code verification

Colab CLI is installed in an isolated Python environment. All CLI calls should go through `~/.local/bin/nanomaid colab ...`, which uses NanoMaid's isolated OAuth `HOME`; a raw `colab` call may use a different profile. Run `~/.local/bin/nanomaid colab-auth` in a real terminal to authenticate. Never paste the OAuth code or credentials into Telegram. Check account state with `~/.local/bin/nanomaid colab sessions` and `~/.local/bin/nanomaid colab usage`.

For code verification, create a command JSON using argv arrays (not shell strings), then run `~/.local/bin/nanomaid verify plan PROJECT_DIR COMMANDS.json`. CPU is selected when `accelerator` is omitted; set `"accelerator": "T4"` only for a finite check. Review the complete source manifest, archive SHA-256, job-manifest SHA-256, commands, and accelerator before approving each upload/run. The helper requires zero paid-unit balance, requests T4 only when approved in the job, verifies T4 before upload, and treats a positive hourly rate as informational. Execute the exact plan with `~/.local/bin/nanomaid verify run JOB_ID ARCHIVE_SHA256 JOB_SHA256 --free-confirmed`. It excludes environment files, keys, secrets, common media, and datasets; returns text logs; stops the temporary session; and deletes local staging.

Example T4-only test manifest:

```json
{
  "commands": [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]],
  "accelerator": "T4"
}
```

Colab is not Docker or a persistent bot host. Free-tier capacity and policy are not guaranteed; a T4 may be unavailable even when usage is zero. NanoMaid verification never hosts bots or web services. Finance/transcription bots and their input media remain separate and are not installed by this project.

## Security and rollback

- The app token and OpenCode V2 password live only in the local bot config (`~/.config/opencode-telegram-bot/.env`) with mode `0600`; never commit that file.
- Disable group joining for the bot in BotFather; the installer cannot change BotFather settings. The installer sets `umask 077` for secret setup.
- OpenCode global shell and file-edit actions require approval; this also affects TUI/desktop clients sharing the service.
- The installer merges only a marked NanoMaid block into global `AGENTS.md`, preserving the existing rules and creating a mode-0600 backup before edits. `./check.sh` verifies the block; the uninstaller preserves it with the rest of OpenCode config.
- Local JSON shell commands, scheduled tasks, and the bot's OpenCode start/stop controls remain unused.
- `./check.sh` checks prerequisites and service health. `./uninstall.sh` stops/removes NanoMaid's service and runtime but preserves credentials, OpenCode sessions/config, and user lingering.

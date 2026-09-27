# NanoMaid

**A nano personal assistant living on a small VPS.** NanoMaid wraps the existing OpenCode V2 service in a private Telegram client and provides an approved, one-shot Colab code-verification path.

## Supported target

- Ubuntu 26.04 LTS, x86-64
- OpenCode V2 already installed, authenticated, and configured with a model/provider
- A single Telegram owner; private chat only
- User-level `systemd` with lingering already enabled
- No Docker, public listener, or firewall changes

The installer pins Node.js, uv, the Telegram wrapper, and Google Colab CLI. It uses user-local tools only and does not require apt/sudo. It is safe to re-run and has dry-run/check modes. NPM lifecycle scripts are disabled; the pinned wrapper release includes a Linux SQLite prebuild, which is smoke-tested during validation. It does not install or configure OpenCode providers, store secrets in this repository, or publish a remote Git repository.

## Install

```bash
./install.sh --dry-run
./install.sh
```

The installer preflights OpenCode, RAM, version checksums, and user-service persistence. It installs dependencies in user-local paths, creates the service unit, and prepares a local config with the current OpenCode model defaults.

In a real terminal, configure the Telegram bot interactively (token and OpenCode password are entered hidden, never pasted into chat):

```bash
~/.local/bin/nanomaid configure
```

In BotFather, disable group joining for the bot. Then test in the foreground:

```bash
~/.local/bin/nanomaid start
```

After confirming it works and memory headroom remains safe:

```bash
systemctl --user enable --now nanomaid.service
```

Check status with `~/.local/bin/nanomaid status` and logs with `journalctl --user -u nanomaid.service`.

## Colab code verification

Colab CLI is installed in an isolated Python environment. Run `~/.local/bin/nanomaid colab-auth` in a real terminal to authenticate your account into NanoMaid's isolated Colab home. Never paste the OAuth code or credentials into Telegram.

For code verification, review the proposed project file manifest and exact lint/build/test commands before approving each upload/run. Only approved source files are sent to Google. The helper excludes environment files, keys, secrets, media, and datasets; the first version is CPU-only and returns text logs. Stop the temporary Colab session after every job.

Colab is not Docker or a persistent bot host. Free-tier capacity and policy are not guaranteed. Finance/transcription bots and their input media remain separate and are not installed by this project.

## Security and rollback

- The app token and OpenCode V2 password live only in the local bot config (`~/.config/opencode-telegram-bot/.env`) with mode `0600`; never commit that file.
- The installer disables BotFather group joining and sets `umask 077` for secret setup.
- OpenCode global shell and file-edit actions require approval; this also affects TUI/desktop clients sharing the service.
- Local JSON shell commands, scheduled tasks, and the bot's OpenCode start/stop controls remain unused.
- `./check.sh` checks prerequisites and service health. `./uninstall.sh` stops/removes NanoMaid's service and runtime but preserves credentials, OpenCode sessions/config, and user lingering.

---
name: NanoMaid Colab CLI
description: Use NanoMaid's isolated Colab CLI profile for approved session checks and one-shot CPU or free-quota T4 code verification.
---

# NanoMaid Colab CLI

Use NanoMaid's wrapper for all Colab commands. It selects the isolated OAuth profile at `~/.local/share/nanomaid/colab-home`; calling the raw `colab` binary with the normal home may not see that login.

## Authentication and status

- `~/.local/bin/nanomaid colab-auth` performs OAuth and requires a real interactive terminal. Never paste OAuth codes or credentials into Telegram, OpenCode chat, command arguments, task files, or logs.
- Use `~/.local/bin/nanomaid colab sessions` and `~/.local/bin/nanomaid colab usage` for read-only session and cost checks.
- If auth, account entitlement, T4 availability, or paid-unit balance is unclear/nonzero, stop. A positive or omitted hourly-rate display alone is not an eligibility failure when the paid-unit balance is readable and zero.
- For source upload or code execution, use only the reviewed `nanomaid verify` workflow. Do not manually call `colab new`, `upload`, `exec`, `run`, or `stop` to bypass its manifest, cost, approval, and cleanup checks.

## Verification jobs

NanoMaid supports finite code-verification jobs only. CPU is the default. An optional T4 may be requested by putting `"accelerator": "T4"` in the reviewed `commands.json`; omit it for CPU. The command list must be arrays of argv strings, never shell command strings.

Example finite T4 test job:

```json
{
  "commands": [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]],
  "accelerator": "T4"
}
```

1. Prepare a job with `~/.local/bin/nanomaid verify plan PROJECT_DIR COMMANDS.json`.
2. Review the complete source manifest, archive size and SHA-256, job-manifest SHA-256, exact commands, and accelerator. The archive is transferred to Google and executes remotely.
3. Confirm the paid-unit balance is `0.00`. A positive hourly rate alone is not a rejection. For T4, confirm Colab allocates the requested accelerator and session status reports T4; if allocation or status fails, do not upload source.
4. Obtain explicit one-time approval for the exact job and transfer before running `~/.local/bin/nanomaid verify run JOB_ID ARCHIVE_SHA256 JOB_SHA256 --free-confirmed`.
5. The helper verifies hashes and paid-unit balance, creates a uniquely named temporary session, requests T4 only when approved in the job, checks the actual GPU, runs only the reviewed argv arrays, retrieves text output, stops/verifies the session, and deletes local staging. It never uses `--keep`.

For verification uploads/execution, do not bypass this helper with direct `nanomaid colab new/upload/exec/run` commands; those commands do not apply the reviewed-job contract.

Exclude secrets, `.env`, credentials, private data, audio/image/video media, datasets, dependencies, caches, and build output from every archive. Review the manifest; never assume ignored files are safe.

## Colab limits

- Do not host Telegram bots, workers, web services, public Gradio pages, or persistent processes on a Colab managed runtime. Do not use this workflow for transcription/media processing.
- T4 is for a finite code check only, not a long-running service. Require zero paid-unit balance; a displayed hourly rate alone is allowed. No paid compute, TPU, high-memory runtime, Drive mount, SSH, `colab console`, or VM-side GCP auth.
- Stop on policy uncertainty, nonzero/unreadable paid-unit balance, failed T4 validation, or any mismatch between the reviewed job and staged hashes.

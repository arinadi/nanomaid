---
name: NanoMaid Colab Code Verification
description: Run user-approved, one-shot lint/build/test checks on a temporary Colab CPU runtime.
---

# NanoMaid Colab verification policy

Use the Colab CLI only for finite code-verification jobs requested by the user. Do not host a bot or web service on Colab.

## Before any upload or run

1. Explain that selected project source is sent to Google and executes remotely.
2. Prepare and show the exact file manifest, archive size/hash, and lint/build/test commands in Telegram.
3. Exclude `.env`, credentials, API keys, financial data, audio/media, private datasets, `.git`, `node_modules`, virtual environments, and generated caches. Never infer that an ignored file is safe to transfer.
4. Wait for an explicit one-time approval. OpenCode shell/edit permissions must remain `ask`; do not save broad persistent approvals.
5. Check Colab usage/cost status. Use CPU only. If policy, cost, or account entitlement is unclear, stop without running the job.

## Run and clean up

- Use a uniquely named temporary session and the reviewed NanoMaid verification helper.
- Do not pass `--gpu`, `--tpu`, `--high-mem`, or `--keep`. Do not use Drive mount, VM-side GCP auth, SSH, or `colab console`.
- Run only the approved commands from the approved manifest. Do not substitute commands or files after approval.
- Return text logs only. Stop the named Colab session in cleanup even when a command fails; verify it is stopped.
- Never include credentials in the archive, command arguments, output, or logs.

Colab is not a Docker replacement: it is a temporary managed VM with dynamic availability and limits. The finance/transcription bots and their media workflows are separate and out of scope.

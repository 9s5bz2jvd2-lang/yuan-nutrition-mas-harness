# Security and Safety Policy

Yuan Nutrition MAS Harness is a local-first Multi-Agent System (MAS) harness for nutrition-AI workflows. It is designed to make orchestration, approvals, rollback, and task handoff more auditable, not to remove human responsibility.

## Supported security posture

This repository is an early public prototype. Please treat it as a local development tool until you have reviewed and configured it for your own environment.

Core safety assumptions:

- Run it on `127.0.0.1` for local use by default.
- Do not expose the local server directly to the public internet.
- Keep API keys and chat credentials out of git.
- Review external side effects before approval.
- Review nutrition/medical outputs before sending them to real users.

## Secrets and credentials

Do not commit real credentials. This includes, but is not limited to:

- API keys and model-provider tokens;
- WeChat / Telegram / Feishu / IMAP credentials;
- bearer tokens, cookies, session exports, private keys;
- screenshots or logs containing credentials.

The harness is designed around a Keychain-first Secret Vault with restricted `.secrets` fallback. If you use a fallback file, keep it outside tracked git history and restrict permissions.

Recommended checks before pushing or sharing logs:

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
git diff --check
grep -RInE 'sk-|Bearer |api_key|password|secret|token' . \
  --exclude-dir=.git --exclude-dir=__pycache__ --exclude='*.pyc'
```

The grep command is intentionally noisy. Investigate matches and redact real secrets before sharing.

## External side effects

The harness may coordinate actions that have effects outside the repository, such as:

- API calls that cost money;
- messages sent to WeChat or other channels;
- file edits and git commits;
- worker dispatch to another agent;
- exporting logs, screenshots, or reports.

High-impact actions should remain confirmation-gated. Rollback can help recover repository files, but it cannot undo API charges, messages already sent, public GitHub visibility changes, or external service actions.

## Nutrition and medical boundaries

This project is a workflow harness, not a medical device and not a replacement for a registered nutritionist, physician, or clinical judgment.

For nutrition workflows:

- cite or retain evidence for medical/nutrition claims;
- avoid fabricated references, fake guideline names, and overconfident claims;
- keep uncertain conclusions clearly labeled;
- require human review before user-facing medical or nutrition advice;
- follow local professional, clinical, privacy, and compliance requirements.

## Reporting a vulnerability

If you find a security issue, please open a private report through GitHub's vulnerability reporting if available, or contact the maintainer privately before posting exploit details publicly.

When reporting, include:

- affected version or commit;
- reproduction steps;
- expected vs. actual behavior;
- whether credentials, private data, or external side effects were involved;
- a redacted log excerpt if useful.

Please do not include real secrets in an issue, discussion, or pull request.

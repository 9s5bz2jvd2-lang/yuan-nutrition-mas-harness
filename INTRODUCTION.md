# Yuan Nutrition MAS Harness — Professor-facing Introduction

Yuan Nutrition MAS Harness is a local-first GUI prototype for coordinating multi-agent nutrition workflows under human professional review.

It was built for research and workflow exploration around AI-assisted nutrition work: intake, routing, approval, worker dispatch, result collection, safety review, and final return to a nutrition professional or maintainer. It is not a medical device, not a diagnostic system, and not an automatic treatment engine.

## What this prototype demonstrates

- A lightweight local GUI built with a Python standard-library HTTP server and vanilla HTML/CSS/JavaScript.
- A traceable workflow protocol: `intake -> route -> approval -> dispatch -> collect -> return`.
- Provider/model configuration paths for OpenAI-compatible model calls.
- Optional bridges to LingTai-style agents, mailbox dispatch/collection, avatars, daemons, Codex/Claude-style workers, and external message connectors.
- Approval gates for side effects, worker launching, GitHub PR/merge actions, and local editing workflows.
- Watchdog, recover, resolve, rollback, budget/cost guardrails, and secret-safety checks.
- A research scaffold for nutrition-oriented multi-agent workflows where a human nutrition professional remains the final reviewer.

## What it is not

- It is not a clinical diagnosis or treatment system.
- It is not a substitute for physicians, dietitians, or registered nutritionists.
- It does not provide emergency advice.
- It should not be used as an autonomous patient-facing decision system.

## Quick local start

```bash
git clone https://github.com/9s5bz2jvd2-lang/yuan-nutrition-mas-harness.git
cd yuan-nutrition-mas-harness
python3 server.py
# then open http://127.0.0.1:8765/
```

Or on macOS, double-click:

```text
Start Yuan Nutrition MAS Harness.command
```

## Research positioning

This repository is best understood as a transparent harness prototype: a local control surface for testing how nutrition-specific AI workflows can be routed, reviewed, audited, and bounded by human expertise. It is intended for demonstration, review, and further research collaboration rather than unsupervised deployment.

Maintainer: Wang Runyuan / 王润圆.

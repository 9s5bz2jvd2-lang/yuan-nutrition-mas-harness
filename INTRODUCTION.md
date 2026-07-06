# Yuan Nutrition MAS Harness — Nutritionist-friendly Multi-Agent System GUI Prototype

Yuan Nutrition MAS Harness is a **nutritionist-friendly Multi-Agent System (MAS) GUI harness** developed by Wang Runyuan. It is a local-first control surface for nutrition professionals and researchers to test how nutrition tasks can be received, routed, approved, dispatched to workers, collected, reviewed, and returned.

It is not just a button-only GUI and not a single nutrition chatbot. The intended workflow is:

```text
intake -> route -> approval -> dispatch -> collect -> return
```

In this prototype, WeChat/GUI input can enter a local `harness_run`; the operator can inspect routing, approve or reject side effects, launch or simulate workers, collect results, and keep the human nutrition professional as the final reviewer.

## What this prototype demonstrates

- A lightweight local GUI built with a Python standard-library HTTP server and vanilla HTML/CSS/JavaScript.
- A nutritionist-facing task console for intake, routing, approval, dispatch, collection, and return.
- Support for up to 5 local agent / child-agent cards for multi-agent orchestration (`MAX_AGENTS=5`), while optional worker launch modes remain separately approval-gated.
- Optional bridges to LingTai-style agents, mailbox dispatch/collection, avatars, daemons, Codex/Claude-style workers, and external message connectors.
- Standalone local status pages and health checks that can run after clone/download without full LingTai.
- Provider/model configuration paths for OpenAI-compatible model calls when the user supplies their own local configuration and credentials.
- Approval gates for side effects, worker launching, GitHub PR/merge actions, and local editing workflows.
- Watchdog, recover, resolve, rollback, budget/cost guardrails, and secret-safety checks.
- A research scaffold for nutrition-oriented MAS workflows where a human nutrition professional remains in control.

## What it is not

- It is not a medical device.
- It is not a clinical diagnosis or treatment system.
- It is not a substitute for physicians, dietitians, registered nutritionists, or clinical judgment.
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

This repository is best understood as a transparent GUI harness for a nutritionist-centered MAS workflow. It shows how nutrition-specific AI work can be bounded by evidence, approval gates, cost guardrails, worker isolation, and human professional review.

Maintainer: Wang Runyuan / 王润圆.

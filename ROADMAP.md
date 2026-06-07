# Roadmap

Yuan Nutrition MAS Harness is an early, runnable lightweight MAS harness inspired by LingTai, with an optional LingTai bridge. The core app runs standalone after clone/download with Python stdlib; the roadmap below keeps the project honest by separating what already works from optional bridge/tool hardening.

Current connector boundary: WeChat/external-channel inbound is no longer tied to a full LingTai install. The lightweight harness exposes a standalone HTTP connector (`/api/connectors/wechat/incoming`, pending, mark_sent, and status) that reuses the same routing/approval path and never starts a poller. Real outbound send still depends on an external WeChat provider/API/webhook credential, while the LingTai MCP bridge remains an optional compatibility path.

## Current baseline: v0.23

Current prototype capabilities include:

- local GUI and local server;
- unified Task Router for GUI / WeChat-style inputs;
- harness run chain: `intake -> route -> approval -> dispatch -> collect -> return`;
- approval queue and scoped grants;
- API / model center for OpenAI-compatible providers and custom endpoints;
- Keychain-first Secret Vault design with restricted `.secrets` fallback;
- local budget / cost guardrail panel;
- git Time Machine / rollback with confirmation;
- LingTai internal mailbox dispatch and reply collection;
- controlled worker dispatch protocol using structured `HARNESS_REPLY_JSON` results;
- lightweight multi-agent orchestration records, insight records, soul-flow records, and shougong records.

## Near-term priorities

### 1. Public-source readiness

- Keep README, Quickstart, Security, and Roadmap aligned with actual behavior.
- Add screenshots or a short demo GIF only after secret/log redaction.
- Add a small architecture diagram for the harness run chain.
- Keep `data/state.example.json` safe and representative.

### 2. Worker execution templates

- Stabilize the controller-to-worker prompt template.
- Make the required `HARNESS_REPLY_JSON` schema explicit and testable.
- Add clearer `needs_human`, `stuck`, and `failed` recovery examples.
- Keep worker dispatch auditable rather than silently autonomous.

### 3. Approval and side-effect gates

- Split approval scopes for:
  - API cost;
  - file write;
  - git commit / push;
  - outbound message;
  - log/screenshot/report export;
  - external service action.
- Add a review screen that shows the exact proposed side effect before approval.
- Keep rollback warnings clear: rollback cannot undo external side effects.

### 4. Nutrition workflow safety

- Add evidence-level labels for nutrition claims.
- Add a review checklist for user-facing nutrition/medical outputs.
- Add red-flag routing for clinical, emergency, pediatric, pregnancy, eating-disorder, or medication-sensitive cases.
- Keep the harness as workflow support, not diagnosis or treatment.

### 5. Cost and observability

- Improve cost estimates with provider-specific token/cost fields.
- Add run-level audit export with secret redaction.
- Add latency and failure summaries by harness stage.
- Keep local logs readable by non-engineers.

## Longer-term ideas

- Optional desktop packaging.
- Optional plugin/provider registry for model APIs.
- Optional multi-user role model for nutrition teams.
- Optional browser-based demo mode with mocked integrations.
- More robust import/export for harness runs and shougong records.

## Non-goals for now

- Replacing the full LingTai kernel.
- Running as an unmanaged public SaaS.
- Silently executing high-impact agent actions without approval.
- Providing clinical diagnosis, medical treatment, or unreviewed nutrition prescriptions.


## Current milestone: v0.24 GUI Worker Launcher

Completed in this milestone:

- GUI launch panel for daemon / Codex / Claude / avatar.
- Approval-gated `worker_launch` records and previews.
- Codex and Claude local read-only subprocess templates with redacted report files.
- daemon dispatch through the real LingTai controller mailbox.
- avatar same-network shallow spawn and `lingtai-agent run` startup path.

Next hardening targets: richer report viewer, cancellation for long-running subprocesses, per-worker cost estimates, and clearer controller-side daemon templates.

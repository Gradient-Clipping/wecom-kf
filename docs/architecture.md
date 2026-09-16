# Architecture Analysis

## Inspected Baseline

Repository: `Gradient-Clipping/server-gitops`, branch `main`, inspected revision
`acd2ecac9315ccf749bafa7d9c2bf65fb5cdcc81` on 2026-09-14. This is a source/configuration
inspection, not a live cluster health or capacity audit.

- One K3s node: `easy-platform-1`. Extra replicas do not provide host-level HA.
- Delivery: application CI -> Tencent TCR immutable image -> Flux image policy
  and shared image automation -> validated `main` -> `production` -> Flux apply.
- Edge: EdgeOne -> host Nginx -> loopback NodePort `32080` -> Traefik -> Service.
- Annotated Ingress hosts under `lazycampus.com` are eligible for EdgeOne domain,
  Cloudflare DNS-only CNAME and certificate reconciliation.
- Host Nginx and per-host EdgeOne rules require the repository's host/bootstrap
  process; Flux does not install host configuration files.
- Applications use the existing shared MySQL 8.4 service with separate databases
  and least-privilege users, not an extra application-owned database server.
- Runtime and registry credentials are absent from Git, restored into Kubernetes
  Secrets from root-only server recovery material.

Reference files in GitOps: `README.md`, `clusters/easy-platform/kustomization.yaml`,
`infrastructure/domain-automation/config.yaml` below that cluster,
`apps/status-page/ingress.yaml`, `apps/status-page/network-policy.yaml`, and
`host/nginx/lazycampus`. See [deployment handoff](../deploy/README.md).

## Suggested Service Shape

The platform repository is `Gradient-Clipping/wecom-kf`, with the `wecom_kf`
Python package and `https://kf.lazycampus.com` public host. Shared components own
WeCom transport, conversations, administrator SSO, authorization and job delivery.
Business-specific operations belong to separate service adapters; EduCoder is the
first planned adapter. Route commands through explicitly registered capabilities
and service permissions, not an unrestricted model-selected import or shell.
Future adapters must not depend on EduCoder credentials or its question bank.
This release has no adapters or execution worker yet.

Use a Python FastAPI HTTP boundary and a separate synchronous worker process that
imports the existing EduCoder library. Do not execute `example.py` or parse its
stdout from a web request. Start with one API replica and one worker deployment;
size their resources after checking current single-node headroom.

The public callback performs authentication/decryption and durable acceptance.
It does not log in to EduCoder, download every question, call DeepSeek, or wait
for evaluation. Jobs survive API restart and the worker can be rolled separately.

Use dedicated tables in shared MySQL for bindings, message inbox, sync cursors,
conversation state, jobs, task attempts and reply outbox. A transactional job table
is the durable queue; use leases and conditional state changes for worker ownership.
Redis, if needed, is scoped to this service for notification/cache/rate coordination,
not the only copy of jobs or accepted customer events.

## WeChat Message Flow

1. Verify and decrypt the POST event, validate its receive ID and configured
   customer-service account, and durably record its identity before acknowledging.
2. A `kf_msg_or_event` callback signals available data; it is not the full customer
   conversation. A sync consumer calls `kf/sync_msg` for that `open_kfid`.
3. Persist `next_cursor` together with accepted messages. Deduplicate with a unique
   key scoped to the enterprise, customer-service account and message ID.
4. Continue according to `has_more`, even if a page contains no messages. Serialize
   cursor advancement per customer-service account. Use a bounded catch-up process
   because callbacks are not guaranteed delivery. Never replay old historical
   commands into new exercise submissions on first installation.
5. Process customer messages as commands. Staff messages and system events must not
   accidentally trigger the solver or create a bot-to-bot reply loop.
6. Send replies through `kf/send_msg` using a durable outbox and stable message IDs.
   Check both API errors and subsequent delivery-failure events.

The callback event's sync Token is distinct from the configured signature Token.
Persist the former only as needed for prompt synchronization and never log it.
These protocol details were checked against the
[official receive API](https://developer.work.weixin.qq.com/document/path/94670).

Customer-service replies have a response window and a limited message budget.
The current [send API](https://developer.work.weixin.qq.com/document/path/94677)
describes five replies within 48 hours after a customer message and a 2048-byte
text limit. Send an acceptance and aggregate outcome, not one message per test
case or model attempt. Keep long numbered lists in a paginated/status view; never
rely on silent UTF-8 truncation. Support explicit status queries and delivery errors.

## Chat Workflow

Bind an account -> list unfinished shixuns (or all) -> persist a numbered snapshot
-> normalize full-width selection -> present the account/selection for confirmation
-> enqueue -> execute chosen shixuns sequentially -> aggregate result.

- Scope conversations by enterprise, customer-service account and external user ID.
- Numbers refer to the user's stored snapshot, not a freshly reordered API list.
  Expire stale lists and ask for a new list rather than selecting a different task.
- Preserve `0` for all in that snapshot and deduplicate selections in input order.
- Re-fetch completion and permissions before execution; skip passed challenges.
- Keep per-question full text, ordered images, starter code and the tool-call repair
  context. Only `submit_code(full_code=...)` may submit an AI answer.
- For multi-path tasks, submit only the first (main) file. Read the other listed
  files into AI context as read-only references; the bank stores main-file answers.
- Pass/fail/unknown are different states. An uncertain remote build must not be
  automatically retried by queue redelivery or a restarted worker.
- Cancellation stops future submissions; it cannot promise to cancel an already
  accepted remote evaluation.

## Cluster-Specific Changes To The Current Library

The current `SubmissionGate`, file/repository locks and bank-write lock are in one
Python process. Increasing Pod or worker counts without additional coordination
would violate their guarantees.

Route each EduCoder account to one active worker lease, and persist submission
admission state. Before scaling, provide shared account/repository ownership and
fencing checks around every save/build; preserve at least 0.5 seconds between
skip-enabled admissions. Sequential shixuns still require a pass before the next
challenge and do not gain an artificial delay. A stale lease must not permit
concurrent writes or blind replay of an accepted build.

Persist attempt state before external side effects and record returned build
context immediately. Recovery reconciles remote task state. Neither a database
transaction nor a distributed lock can make an uncooperative external API exactly
once; an ambiguous transport failure needs explicit reconciliation.

Keep the five-solution-round and eight-API-attempt policies at their current layer;
queue retries must not reset them. Bound per-user concurrency, costs, task counts
and execution duration independently of model decisions.

The current SQLite question bank is not a multi-writer network database. Before
scaling writers, add a MySQL-backed bank adapter preserving exact normalization,
raw source, ordered image bytes and collision handling. Import the current bank
explicitly, without adding user/course provenance to question tables. Do not bake
the notebook, local credentials, account sessions, or audit directories into an image.

The source image must contain a pinned, self-contained version of the EduCoder
library. This callback-only repository does not copy or package the parent project;
production must not depend on a local `../educoder` path.

## Identity And Security

- Initially allowlist one verified operator/account; do not make the parent's
  `.env` account available to every customer who sends a message.
- The web frontend is administrator-only, protected by administrator identity and
  authorization. Customers interact through WeChat Customer Service, not a web UI.
- Administrator SSO is automatic on entry, using the platform's existing identity
  provider. Check the server session first; if absent, begin the OIDC authorization
  redirect automatically, without a login button. Reuse a valid SSO session so
  already authenticated administrators need no extra interaction. An expired IdP
  session may still require authentication; never bypass it to appear seamless.
- Validate OIDC state, nonce and PKCE, use secure HttpOnly session cookies and check
  administrator roles on the backend. An authenticated non-admin receives 403,
  not a redirect loop. Callback and health routes must never require SSO.
- Reuse `https://auth.lazycampus.com/realms/lazycampus` and backend checks for the
  existing `platform-admin` realm role. Create a separate confidential client for
  this platform when the administrator frontend is implemented; no SSO client or
  frontend is provisioned in the callback-only release.
- Bind accounts through an explicitly authorized administrative workflow. Do not
  ask customers to put passwords directly in customer-service messages. Any future
  customer credential handoff needs a separately approved secure design.
- Encrypt stored account credentials with a separate managed key; rotate/revoke
  bindings, isolate cookies and sessions, and mask phone numbers in logs.
- Keep authorization, task ownership and execution feature gates outside the model.
  Statements, images, user text and evaluation output are untrusted task data.
- Generated solutions are uploaded only to the authorized remote task. Do not run
  them on the API/worker host. No unrestricted shell or cluster tool goes to the AI.
- Do not log callback query values, encrypted payloads, passwords, cookies, API
  tokens or full model contexts by default. Restrict and expire diagnostic artifacts.
- Use non-root containers, resource limits, probes, graceful shutdown and no API
  service-account token mount. Scope network access to ingress, DNS, the dedicated
  database/Redis and required HTTPS APIs. Do not expose internal administration routes.

## Staged Rollout

1. **Source repository:** independent private source, CI and runtime configuration.
2. **Current release, callback only:** authenticate GET/POST and durably buffer
   encrypted notifications; establish DNS/TLS/origin routing. Execution and message
   processing remain off. Actual console verification is administrator-driven.
3. **Message transport:** durable POST acceptance, cursor synchronization, outbox,
   allowlist and harmless commands. Do not take over active customer service earlier.
4. **Single-account pilot:** secure account binding, stable selections, confirmation,
   one worker and resumable job reporting. Explicit execution opt-in.
5. **Broader use:** shared bank adapter, distributed admission, resource/load tests,
   cost limits, backups and rollback. Single-node downtime remains a platform limit.

# WeCom KF

Shared WeChat Customer Service integration platform, with native reply menus,
durable account binding, task selection and confirmed EduCoder execution.
Source is maintained in the
private `Gradient-Clipping/wecom-kf` repository; production desired state is
maintained in `Gradient-Clipping/server-gitops`.

## Callback

```text
https://kf.lazycampus.com/callbacks/wecom/kf
```

GET verifies the signature, decrypts `echostr`, checks the enterprise receive ID
and returns the original bytes. POST authenticates encrypted `kf_msg_or_event`
notifications and stores their ciphertext in a dedicated MySQL inbox before
returning `success`. Duplicate notifications update a delivery counter.

The frontend at `/admin` is **administrator-only**, with automatic Keycloak SSO
and no login button. Customer interactions take place in WeChat Customer Service.

Callback verification needs CorpID, Token and EncodingAESKey. Message processing
also requires the API Secret and a configured OpenKfId. See [runtime operations](docs/runtime.md).

## Development

```powershell
uv sync --python 3.13
uv run python -m unittest discover -s tests -v
uv run --env-file .env uvicorn wecom_kf.app:create_app --factory --port 8000 --no-access-log
uv run --env-file .env python -m wecom_kf.worker gateway
uv run --env-file .env python -m wecom_kf.worker actions
uv run --env-file .env python -m wecom_kf.worker executor
```

Populate callback and MySQL settings from `.env.example`. Startup creates the
inbox table using the dedicated database account. MySQL integration tests run in
CI against an isolated MySQL 8.4 service; set `TEST_MYSQL=1` and a database ending
in `_test` to run them locally. Never point integration tests at production.

Routes: `/healthz`, `/readyz`, `/callbacks/wecom/kf`, `/admin` and the OIDC callback.
Message processing and execution require explicit feature gates. No end-user web UI.

## Delivery And Security

CI verifies the application and database integration, then publishes immutable
TCR tags. Flux follows validated GitOps production revisions. Runtime credentials
are excluded from Git and container builds. Application/origin access logging is disabled; payloads
and query parameters are not logged. Kubernetes network policy allows DNS,
MySQL and public HTTPS egress. The edge disables caching and authenticates requests to the
dedicated origin virtual host.

**Confirmed account/password bindings are stored in plaintext as requested by
the operator. Database or backup leakage exposes them.** Pending credentials and
incoming messages use a dedicated Fernet key; processed message bodies are erased.
Passwords are never echoed, logged, displayed in the admin console or sent to AI.

Five minutes without replying to the latest bot reply expires unconfirmed data,
selections and old menus. Confirmed bindings, failure counters and queued/running
executions persist. Three explicit credential failures lock that WeChat for 24h;
network/CAPTCHA failures do not consume attempts. Re-selection requires confirmation.

Each worker role holds a MySQL advisory lock. Deployments use Recreate. In-flight
submissions interrupted by restart are not replayed. WeCom reply limits are enforced;
completion summaries persist for the next customer message if delivery is unavailable.
API acceptance is not proof of delivery; asynchronous failures update the outbox.

The existing EduCoder library is snapshotted by `deploy/sync_educoder.py` with
checksums. No notebook or credentials are copied. The bank uses a persistent volume.

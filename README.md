# WeCom KF

Shared WeChat Customer Service integration platform, initially callback-only.
EduCoder is a planned service integration, not the platform's identity.
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

This release does **not** fetch chats, send replies, log in to EduCoder, execute
exercises or serve a frontend. A future frontend is **administrator-only**;
customer interactions take place in WeChat Customer Service.

Callback verification needs only CorpID, Token and EncodingAESKey. The unavailable
API Secret is not required or loaded. See [configuration](docs/callback-setup.md).

## Development

```powershell
uv sync --python 3.13
uv run python -m unittest discover -s tests -v
uv run --env-file .env uvicorn wecom_kf.app:create_app --factory --port 8000 --no-access-log
```

Populate callback and MySQL settings from `.env.example`. Startup creates the
inbox table using the dedicated database account. MySQL integration tests run in
CI against an isolated MySQL 8.4 service; set `TEST_MYSQL=1` and a database ending
in `_test` to run them locally. Never point integration tests at production.

Routes: `/healthz`, `/readyz`, `/callbacks/wecom/kf`. There are no documentation,
admin or end-user routes. Both execution feature gates must remain false.

## Delivery And Security

CI verifies the application and database integration, then publishes immutable
TCR tags. Flux follows validated GitOps production revisions. Runtime credentials
are excluded from Git and container builds. Application/origin access logging is disabled; payloads
and query parameters are not logged. Kubernetes network policy allows only DNS
and MySQL egress. The edge disables caching and authenticates requests to the
dedicated origin virtual host.

The inbox stores encrypted notifications, **not the customer conversation**.
Notification tokens expire; message synchronization, retention, cursor recovery,
replies and task execution are future work. Do not offer this as a working chat
assistant yet. See [architecture](docs/architecture.md) and
[deployment](deploy/README.md).

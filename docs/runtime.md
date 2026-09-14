# Runtime Operations

## Configuration

- Callback: `WECOM_CORP_ID`, `WECOM_CALLBACK_TOKEN`, `WECOM_ENCODING_AES_KEY`.
- Storage: `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`.
- Processing: `WECOM_MESSAGE_PROCESSING_ENABLED=true`, `WECOM_OPEN_KFID`,
  `DATA_ENCRYPTION_KEY` (Fernet; back up separately, never regenerate on rollout).
- Gateway: `WECOM_API_SECRET` (`WECOM_KF_SECRET` alias accepted).
- Executor: `EDUCODER_EXECUTION_ENABLED=true`, `QUESTION_BANK_PATH`,
  `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL_NAME`, `DEEPSEEK_BASE_URL` and optional
  `DEEPSEEK_TIMEOUT`, `DEEPSEEK_MAX_TOKENS`, `DEEPSEEK_THINKING`.
- Administrator API: `OIDC_CLIENT_SECRET`, `ADMIN_SESSION_SECRET` (32+ characters).

The application must be authorized for WeChat Customer Service, the configured
customer-service account managed by API, and production egress trusted by WeCom.
Human-served sessions are not forcibly taken over; new sessions must stay in the
newly-connected or intelligent-assistant state for API replies.

## Conversation And Data

Native menus have at most ten clicks, so lists and selected-item confirmation are
paged with stable global numbers. Typed input supports full/half width, commas,
ideographic commas, whitespace and zero-width removal. `0` selects all. Passwords
are opaque and never normalized. Old/foreign menu IDs cannot authorize execution.
Each WeChat identity has one confirmed account binding.

MySQL holds encrypted notifications/messages, immutable activation watermark,
per-KF cursor, per-WeChat conversation, plaintext confirmed binding, jobs and
outbox. Notification/message dedupe tombstones retain seven days, exceeding the
three-day API history. Pre-activation commands are not replayed. Five-minute expiry
erases transient credentials/selections, but not bindings, lockouts or executions.

The bank retains its existing SQLite schema on a single-writer persistent volume.
Back up via SQLite's backup API; do not overwrite a populated bank on rollout.
No notebook import is part of runtime. Add services via explicit adapters and
menu transitions, not user-provided callable names or URLs.

## Execution And Recovery

Gateway synchronizes incoming events, consumes messages and sends the outbox.
Actions verifies credentials and fetches lists. Executor processes confirmed jobs
serially; skip-enabled challenges may run concurrently, spaced at least 0.5s on
outbound submission. The existing solver sends complete files, skips passed tasks,
matches exact normalized stems/images, uses DeepSeek tool calls and retains the
same repair context. Maximum five answer attempts; API failures retry up to eight
times with one-second gaps. Only passing answers extend the bank.

Do not retry interrupted or unknown evaluations automatically. Inspect remote
results and let the customer select remaining work again. WeCom accepts at most
five ordinary replies within 48h of input; welcome replies require a 20s code and
opening an existing chat may emit no event. Deferred completion summaries appear
on the next input. Accepted API responses are not delivery receipts. Failure events
update outbox status. Ambiguous sends are not blindly replayed; explicit transient
errors retry at most three times with stable IDs.

Admin access requires a verified ID token with `platform-admin`. State, nonce,
PKCE S256, Secure/HttpOnly/SameSite=Lax cookies and five-minute sessions are used.
Cookies contain no access/refresh token or customer credentials. Non-admins get
403 without a redirect loop. The console is read-only.

Schema creation is additive. Back up MySQL, the bank and data-encryption key before
deployment. Restrict access to plaintext binding passwords and backups.

## Protocol References

- [Receive and sync](https://developer.work.weixin.qq.com/document/path/94670)
- [Messages and menus](https://developer.work.weixin.qq.com/document/path/94677)
- [Welcome replies](https://developer.work.weixin.qq.com/document/path/95122)

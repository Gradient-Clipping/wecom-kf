# Callback Configuration

```text
https://educoder.lazycampus.com/callbacks/wecom/kf
```

Use this URL without a trailing slash in **WeChat Customer Service** callback
settings. Configure the same CorpID, Token and 43-character EncodingAESKey as the
runtime. `.env` uses `WECOM_CORP_ID`, `WECOM_CALLBACK_TOKEN` and
`WECOM_ENCODING_AES_KEY`; `WECOM_KF_TOKEN` and `WECOM_KF_AES_KEY` aliases also work.
Local development loads `.env` explicitly through `uv run --env-file .env`.

The callback does not need the API Secret. Do not deploy an `xxxxxxxx` placeholder.
GET returns decrypted `echostr` unchanged; POST verifies the enterprise and event
type and acknowledges only after its encrypted notification is durable. Requests
with invalid signatures or timestamps more than ten minutes away are rejected.

After deployment and external signed verification, save these values in the
WeCom console. Only the console's actual result confirms WeCom has accepted its
own verification request. A normal browser visit with no signature returns 403;
this is expected and does not mean the endpoint is unavailable.

## Current Boundary

This release buffers encrypted event notifications only. It does not fetch chat
content or reply to users. `kf_msg_or_event` is a signal to fetch messages, not the
message itself. Its synchronization token expires after ten minutes, and the
message API only retrieves recent messages. Stored callbacks are not a permanent
chat backup. Do not switch a live customer-service workflow to this receiver until
the message transport is implemented and explicitly enabled.

Later stages need the selected `open_kfid` and a valid authorized application's
API Secret, cursor persistence, retention, message deduplication, reply outbox,
account authorization and explicit execution consent. No customer-facing web
frontend is planned; any frontend is an authenticated administrator console.

References: [callback protocol](https://developer.work.weixin.qq.com/document/path/90930),
[encryption](https://developer.work.weixin.qq.com/document/path/90968),
[receiving messages](https://developer.work.weixin.qq.com/document/path/94670).

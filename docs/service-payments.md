# Service Payments

Enable only after deploying the Easy SWU generic order API and publishing the
mini-program `features/pages/service-order/index` page:

```dotenv
SERVICE_PAYMENT_ENABLED=true
SERVICE_PAYMENT_URL=https://YOUR_EXISTING_MINIPROGRAM_API_HOST
SERVICE_PAYMENT_PLATFORM=educoder
SERVICE_PAYMENT_SECRET=SHARED_WITH_PAYMENT_BACKEND_PLATFORM_CONFIG
SERVICE_PAYMENT_TIMEZONE=Asia/Shanghai
```

Callback: `POST https://kf.lazycampus.com/callbacks/payments`. It verifies the
shared HMAC protocol and stores events before acknowledgement. The action worker
also polls authoritative order state; no financial fact relies on chat messages.
Changing these settings requires updating the API and action-worker environments.
Execution-worker settings still control whether task execution is enabled.

Selection is snapshotted into unpassed challenge IDs before order creation. The
payment API receives generic item IDs/names/counts, never EduCoder passwords.
The service adapter exposes `billing_items(snapshot)`: one charge item per
homework, with `quantity` equal to its selected, unfinished challenge count and
`billing_attributes.kind = "unit"`. Challenge IDs and titles stay in the private
execution snapshot, not the public purchase breakdown. Empty homeworks are omitted;
duplicate homeworks/challenges are rejected instead of being billed twice.

Other applications use the same contract: one entry per charge item, not one
entry per unit. With the configured `unit: 1` rule, the payment API returns each
entry's `billable_units = quantity` and calculates the authoritative total. For example:

```json
{
  "service_items": [
    {"id": "course:homework-a", "name": "Image Processing", "quantity": 2, "billing_attributes": {"kind": "unit"}},
    {"id": "course:homework-b", "name": "Data Analysis", "quantity": 3, "billing_attributes": {"kind": "unit"}}
  ]
}
```

The response retains those two items with `billable_units` of 2 and 3, an order
`billable_units` of 5, `unit_price_fen: 50`, and `amount_fen: 250`. The mini-program
shows item prices of 1.00 and 1.50 yuan and a total of 2.50 yuan, without showing
unit quantities. The minimum applies to the sum of units, not the number of items:
one item with two units is payable. Fulfillment and partial refunds still use the
original challenge snapshot. Existing order quotes are not rewritten.
Orders and code/manual-check state are independent of ordinary chat expiry.
Only a new effective UNPAID manual check counts. The fifth check atomically revokes
new checkout at the payment backend; an idempotent penalty ledger records the
business day. Late success returns that same penalty, including across midnight.
Pending attempts are never discarded merely because the code expired.

Task enqueue and `solve_job_id` are committed together under the purchase lock.
Sending the customer reply happens through the existing outbox, independently of
execution. The progress menu reads durable job progress without upstream calls.
Failed challenge lists are paginated so long results are not silently omitted.

Final refund: zero successes refunds the full amount; otherwise retain
`max(100, successful_units * 50)` fen, never more than the original total.
The same external refund number survives retries. Apple refunds remain a manual
after-sales action. Interrupted execution remains unresolved pending review.

`SERVICE_PAYMENT_ENABLED=false` preserves the pre-existing free execution flow;
it is the safe installation default, not an active production billing setup.
Tests simulate payment and task state; no real charge is made during tests.

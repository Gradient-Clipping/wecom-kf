# Deployment

Source: `Gradient-Clipping/wecom-kf`; callback host: `kf.lazycampus.com`.
Internal Kubernetes/database/registry identifiers retain `educoder-wecom` from the
initial bootstrap to preserve data and avoid unrelated resource recreation. These
are implementation identifiers, not a restriction to one business service.

Desired state lives in `Gradient-Clipping/server-gitops`:

- `clusters/easy-platform/apps/educoder-wecom/`: API, service, ingress, network
  policy and Flux image tracking.
- `host/nginx/educoder-wecom`: scoped origin route; query access logging disabled.
- `scripts/bootstrap-educoder-wecom.sh`: root-only runtime restoration and host setup.
- `scripts/reconcile-educoder-edge.py`: this host's no-cache and origin-auth rule.

Application CI tests with MySQL 8.4 and publishes
`ccr.ccs.tencentyun.com/lazycampus/educoder-wecom:1.0.<run_number>` plus a source-SHA
tag. GitOps validates `main` before promoting `production`; Flux deploys that
revision. Do not apply application workloads independently from the source repo.

Bootstrap from a committed GitOps checkout on the K3s host after placing these
root-only files in `/etc/platform-secrets`:

```text
educoder-wecom-corp-id
educoder-wecom-callback-token
educoder-wecom-aes-key
```

Existing platform TCR and Tencent credentials are reused for infrastructure only.
The script provisions a separate database/user `educoder_wecom`, runtime secret
`educoder-wecom-runtime`, MySQL secret `mysql-educoder-wecom`, registry pull secret
and an independent origin key. `--runtime-only` prepares dependencies without
installing Nginx or updating EdgeOne. No API Secret or parent EduCoder credentials
are required. Never place secret values in manifests or command output.

The public Ingress contains only the exact callback, health and readiness routes.
Domain automation manages EdgeOne, DNS and TLS; host Nginx and the EdgeOne rule
are installed by the versioned bootstrap. Check rollout, DNS, valid HTTPS, signed
GET, rejected invalid signatures, encrypted POST and durable deduplication before
asking an administrator to save the WeCom callback configuration.

Repeat the external verification without printing signed URLs or credentials:

```powershell
uv run --env-file .env python deploy/verify_callback.py --report reports/public-verification.json
```

Add `--post` to send two copies of a uniquely identified synthetic notification.
Verify its reported digest has a single ciphertext row and `delivery_count=2` in
the inbox, then delete only that synthetic row. HTTP acknowledgements alone are
not evidence of correct database deduplication. Reports contain no credentials.

Rollback: revert the scoped GitOps image/config commit and let validation promote
it; retain runtime keys and inbox data. AES key rotation needs a deliberate data
migration/key retention procedure because pending ciphertext uses the previous
key. A single-node cluster is not highly available.

# 管理后台本地启动与检查

以下命令适用于 `C:\kaifa\com two\wecom-kf`。本地预览使用隔离的 SQLite fixture，不连接企业微信、SSO、支付或真实 MySQL。

## 1. 只检查优化后的页面（推荐）

```powershell
cd 'C:\kaifa\com two\wecom-kf'
uv sync --frozen
uv run --frozen python -m tests.admin_preview
```

浏览器打开 `http://localhost:8766/admin`。预览会模拟管理员 SSO，页面应看到：

- 总任务 205 条，任务表第 1/11 页；点击下一页变为第 2/11 页；
- 点击任务可查看持久化进度、通过关卡和失败记录；
- 绑定搜索 `login-205` 返回 1 条；
- worker 未上报显示“未知/未上报”；
- 390×844 窄屏下菜单、详情抽屉和长 ID 均可用。

左侧导航是四个独立的哈希页面，可直接打开或刷新：`#overview` 总览、`#jobs` 任务中心、`#bindings` 账号绑定、`#settings` 服务设置。每次切页只加载当前页面需要的数据；左侧边框和当前导航标记使用 `#FFBE6E`。页面背景已迁移 SecMind 的 `ControlStarfield` 思路，使用同源 Canvas 绘制浅蓝星云、发光粒子和轻微指针视差；它不拦截交互，且在 `prefers-reduced-motion` 下只绘制静态帧。

预览中的服务开关和解绑是只读 mock，不会修改任何数据。按 `Ctrl+C` 停止服务。

## 2. 运行自动检查

```powershell
cd 'C:\kaifa\com two\wecom-kf'
uv run --frozen python -m unittest discover -s tests -v
node --check src/wecom_kf/admin_assets/console.js
uv build --wheel
```

以本次命令实际输出为准；需要隔离 MySQL 的测试在未提供测试数据库时会跳过。wheel 应包含：

```text
wecom_kf/admin_assets/console.css
wecom_kf/admin_assets/console.js
```

## 3. 生产配置沿用已有 GitOps

生产应用和 SSO 已在相邻的 `server-gitops` 仓库声明，不需要重建 `.env` 或 OIDC 客户端：

- `clusters/easy-platform/apps/wecom-kf/callback.yaml`：callback 应用通过 `envFrom` 读取 `wecom-kf-config` 以及已有 MySQL、运行时和管理端 Secret。
- `clusters/easy-platform/apps/wecom-kf/workers.yaml`：共享 ConfigMap 显式声明 `OIDC_ISSUER=https://auth.lazycampus.com/realms/lazycampus`、`OIDC_CLIENT_ID=lazycampus-wecom-kf`、`PUBLIC_BASE_URL=https://kf.lazycampus.com`；gateway/actions/executor 沿用同一 ConfigMap，但不注入管理端 Secret。
- `clusters/easy-platform/infrastructure/identity/wecom-kf.yaml`：已有 Keycloak 客户端和协调任务，允许回调 `https://kf.lazycampus.com/admin/auth/callback`，使用已有 `wecom-kf-oidc-secret`。
- `clusters/easy-platform/apps/wecom-kf/ingress.yaml` 与 `host/nginx/educoder-wecom`：`/admin` 子路径覆盖登录、API 和静态资源；nginx 保留源站认证，并转发公开 Host 和 HTTPS 协议。

`OIDC_CLIENT_SECRET`、`ADMIN_SESSION_SECRET` 和 `DATA_ENCRYPTION_KEY` 保持在现有受控 Secret 流程中，不写入 ConfigMap。应用会读取上述三个公开环境变量，未设置时保留原生产默认值；URL 会去除外层空白和尾部斜杠。`PUBLIC_BASE_URL` 必须为不含路径的 HTTP(S) origin，issuer 可以带 realm 路径；显式空值、凭据、查询参数及 fragment 会被拒绝。

离线核对 GitOps 契约：

```powershell
cd 'C:\kaifa\com two\server-gitops'
uv run --no-project python -m unittest discover -s scripts/tests -p test_wecom_admin_contract.py -v
```

这些检查只验证仓库声明，不代表已检查或部署线上状态。应用版本发布仍通过已有镜像构建及 GitOps 流程处理。

## 4. 可选：隔离环境的真实 MySQL/SSO 联调

仅在需要真实认证联调时，准备受控测试数据库、HTTPS 测试域名和对应的测试 OIDC 客户端，再填写本地 `.env`，不要把真实密钥提交到 Git：

```powershell
cd 'C:\kaifa\com two\wecom-kf'
Copy-Item .env.example .env
notepad .env
```

至少需要 `WECOM_CORP_ID`、回调三元组、`MYSQL_*`、`DATA_ENCRYPTION_KEY`、`OIDC_CLIENT_SECRET`、长度至少 32 的 `ADMIN_SESSION_SECRET`。另外显式设置 `OIDC_ISSUER`、`OIDC_CLIENT_ID`、`PUBLIC_BASE_URL` 指向测试环境，客户端允许的回调必须等于 `${PUBLIC_BASE_URL}/admin/auth/callback`。会话使用 `__Host-` Secure cookie，真实浏览器 SSO 联调需要 HTTPS 入口；下面的 HTTP 地址仅供本机反向代理连接和健康检查，不能作为完整登录验收入口。

启动应用：

```powershell
uv run --env-file .env uvicorn wecom_kf.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

应用启动前应确认目标 MySQL 已由受控的 worker/初始化流程创建 `kf_*` 表；不要用生产数据库做首次验证。真实服务检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/healthz
Invoke-WebRequest http://127.0.0.1:8000/readyz
```

随后通过 `PUBLIC_BASE_URL` 对应的 HTTPS 入口打开 `/admin`，完成测试 Keycloak 登录。未登录 API 应返回 401 JSON；登录后页面的统计和任务列表应来自测试 MySQL。

如果明确要启动消息处理 worker，再分别开三个终端运行：

```powershell
uv run --env-file .env python -m wecom_kf.worker gateway
uv run --env-file .env python -m wecom_kf.worker actions
uv run --env-file .env python -m wecom_kf.worker executor
```

这三条会访问企业微信/头歌并产生业务副作用，只应在测试环境、明确打开对应 feature gate 后运行。

## 5. 与原目录的差异结论

`C:\kaifa\com\wecom-kf` 当前仍有未提交的 `admin.py`、`store.py`、`tests/test_admin.py` 和 `scripts/preview_admin.py`。其中包含取消 pending 任务和旧页面详情实验；新版已采用外置资源、只读脱敏 API、稳定分页和严格 CSP，因此没有直接合并这些改动。若后续要增加“取消任务”，应单独设计 API、CSRF、状态竞争和审计测试，不能把旧 `job_detail_for_admin` 的 payload/result 返回逻辑直接搬回后台。

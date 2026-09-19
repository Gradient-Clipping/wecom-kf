# 管理后台独立验收记录

本记录对应管理员控制台重构的验收。验收以运行行为和可复现证据为准；源代码自述不能替代接口或浏览器测试证据。未填项不是通过项。

## 通过门槛

### API 与数据安全

- [x] 未认证请求被拒绝；过期 session 对 `/admin/api/*` 返回 401 JSON `{"error":"session_expired"}`。
- [x] 读取响应包含 `Cache-Control: no-store`；参数错误为 400，数据不可用为 503 `{"error":"data_unavailable"}`。
- [x] `/overview` 返回全库 counts、bindings、workers（缺失心跳为未知/未上报）、replies、services 和人工客服开关，并有 `generated_at`。
- [x] `/jobs` 支持组合筛选；`page_size` 仅 20/50/100，205 条 fixture 稳定分页到末页。
- [x] `/jobs` 每条记录只包含契约字段；`progress` 只含白名单且来自持久化结果，非 solve 任务不伪造验证结果。
- [x] 运行中的 solve 任务持久化通过数、总数、当前步骤、`unknown` 和 `has_error`；异常分支保留最后进度，不写入原始异常文本。
- [x] 朔日适配器也统一写入 `has_error`，并保留 `passed_units/total_units` 与 `current_step/total_steps` 等安全进度字段；管理 API 白名单化输出。
- [x] `complete` 与业务成功/失败不混同；结束状态、失败结果和进度分别可辨认。
- [x] `/jobs/{id}` 非法/不存在 id 行为正确，响应不含 payload、result、profile、付款文档、密码、token 或原始订单 JSON。
- [x] `/bindings` 保持最大 50 条和精确匹配语义，只返回契约字段；fixture 敏感值不进入 JSON 或 session cookie。

### 既有管理能力与会话

- [x] SSO 管理员角色校验、CSRF、Origin 校验和 `__Host-` 安全 cookie 仍有效（unit tests）。
- [x] 服务开关、人工客服开关和解绑 JSON API（PUT/POST）由 unit tests 覆盖；preview 中写操作明确为只读 mock，未产生副作用。
- [x] 手动/自动同步只调用读取 API；fixture UI 显示同步、分页、错误和会话过期状态。

### UI 与资源

- [x] 页面由 `frontend/` 的 Vue 3 + Vite 构建，后端仅提供静态入口和 `/admin/api` JSON；生产镜像通过 `ADMIN_STATIC_DIR=/opt/admin` 装载构建产物。
- [x] 前端无内联业务脚本，API 只返回脱敏数据；fixture 响应不泄露用户数据。
- [x] 1280×720 与 390×844 fixture 浏览器均完成导航、分页、详情、绑定搜索、空/错误状态检查；移动端无横向溢出。
- [x] 任务表显示全局与筛选结果口径；时间为 Asia/Shanghai；worker 未上报状态可见。
- [x] 任务行直接显示账号/客户、原生进度条、当前步骤和错误状态；总数未知时不伪造百分比。Node view-model tests cover running, unknown, ended-with-error and non-solve cases.
- [x] 根入口、`/admin` 与 `/admin/` 兼容；旧入口 307 到根页面，OIDC callback 仍为 `/admin/auth/callback`，写操作统一走 JSON API。

## 证据记录

| 项目 | 命令/URL/截图 | 结果 | 日期 |
| --- | --- | --- | --- |
| API/全量测试 | `uv run --with pytest --with pytest-asyncio python -m pytest -q` | 118 passed / 15 skipped. JSON 401/400/404/503, no-store, signed-cookie clearing and progress projections pass on isolated fixture. | 2026-09-19 |
| >100 分页 | `tests/test_admin_queries.py`; `tests/test_admin_integration.py` | 205 fixture jobs: HTTP pages 1–3 yield 100/100/5 unique stable IDs; UI preview showed 20 rows and page 1/11, then page 2/11. No live MySQL evidence. | 2026-09-18 |
| 敏感字段检查 | query/integration tests | Successful HTTP projection excludes fixture payload/password/token/profile; nested counters rejected; binding exact search returns one safe row. Pass within isolated fixture boundary. | 2026-09-18 |
| 认证/CSRF/SSO 回归 | `tests/test_admin.py` via pytest | Passed, including root/static serving, SSO/CSRF and JSON mutation cases. | 2026-09-19 |
| 桌面浏览器 | `http://localhost:8766/admin` fixture preview; parent-provided interaction/screenshots | 1280×720 showed 205 global jobs, 20-row page 1/11; next page, detail, exact binding searches, no-result and inverted-date error states exercised. | 2026-09-18 |
| 窄屏浏览器 | same fixture preview, 390×844; parent-provided screenshots | Menu/task navigation, detail drawer, wrapped long IDs and no horizontal overflow observed. | 2026-09-18 |
| 前端构建与单测 | `cd frontend; npm test; npm run build` | Vitest 3 tests passed; Vite production build passed. | 2026-09-19 |
| 完整回归测试 | pytest + frontend Vitest | 118 Python tests passed, 15 MySQL tests skipped; 3 frontend tests passed. | 2026-09-19 |
| 根域名契约 | `uv run --no-project python -m unittest discover -s scripts/tests -p 'test_wecom_admin_contract.py' -q` in `server-gitops` | 5 GitOps contract tests passed. Ingress/Nginx changes are not deployed. | 2026-09-18 |

## 缺陷与复验

记录必须包含路径、行号或可重现请求、实际结果、期望结果和回交 agent。修复后重新运行原证据，不得仅凭 diff 标记通过。

| 编号 | 严重度 | 位置/复现 | 实际与期望 | 回交 | 复验 |
| --- | --- | --- | --- | --- | --- |
| A-01 | P1 | `src/wecom_kf/admin_queries.py:_progress` | Numeric counters now allow only finite int/float in 0..2147483647; bool/string/nested/list/negative values become null. | API agent | Closed: source inspection + targeted tests independently rerun |
| A-02 | P1 | `frontend/src/progress.js` 与 `JobProgress.vue` | Task rows now show account/customer, progress bar, current step and error/failed records; unknown totals remain indeterminate. | 当前重构 | Closed: Vitest view-model tests, Vite build and source audit |
| A-03 | P2 | `frontend/src/views/Bindings.vue` | Binding search contract only advertises fields supported by `/admin/api/bindings`; no fake customer-ID capability. | 当前重构 | Closed: source recheck |
| A-04 | P2 | `frontend/src/style.css` | Long identifiers wrap safely; responsive sidebar and detail dialog work on narrow screens. | 当前重构 | Closed: responsive CSS review and Vite build |

## 最终意见

验收状态：代码与契约验收通过。数据层、认证/CSRF、分页、脱敏、Vue 构建、运行中任务进度/错误展示和根域名路由均有测试或源代码证据。A-01 至 A-04 已关闭。

边界：15 项真实 MySQL 集成测试未运行；SQLite/loopback preview 使用 disposable fixture，不证明生产 MySQL、线上 SSO/WeCom、支付联调、DNS、Ingress rollout 或镜像已更新。GitOps 变更必须提交并同步后，才能宣称 `kf.lazycampus.com` 线上生效。

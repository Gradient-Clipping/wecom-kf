# 微信客服平台开发规则

## 项目范围

- 本项目对应 GitHub 仓库 `Gradient-Clipping/wecom-kf`，源码目录为 `C:\kaifa\com two\wecom-kf`。
- 相邻的 `server-gitops` 是生产期望状态仓库；应用代码和集群配置分开提交。
- 本项目是 FastAPI 微信客服后端，包含企业微信回调、消息网关、任务执行、支付、管理员面板和可选服务适配器。

## 运行入口

- 本地依赖：`uv sync --python 3.13`。
- 管理员离线预览：`uv run --frozen python -m tests.admin_preview`，访问 `http://127.0.0.1:8766/` 或 `/admin`。
- 真实应用：`uv run --env-file .env uvicorn wecom_kf.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log`。
- Worker 必须按角色单独运行：`gateway`、`actions`、`executor`。
- 回调入口为 `/callbacks/wecom/kf`，健康检查为 `/healthz`、`/readyz`；管理员入口为 `/`、`/admin`，登录使用 OIDC/SSO。

## 配置与数据

- MySQL、OIDC、企业微信、支付和加密密钥通过 `.env` 或 `server-gitops` 的 ConfigMap/Secret 注入；不要把真实值写入源码、日志、测试或文档。
- 任务、消息、绑定、支付和进度由 MySQL 持久化；管理员页面只能读取脱敏数据。
- 历史任务使用创建时保存的 `job_context` 归属，不根据当前绑定猜测历史账号。
- 账号密码按现有业务约定存储，任何日志、管理员输出和 AI 输入都必须脱敏。

## 服务与扩展

- Educoder（头歌）是现有主服务；服务通过注册表按 service code 创建，业务流程不能硬编码成单一平台。
- Shuori（朔日）适配器已接入但默认关闭；默认只评分不提交成绩，提交必须显式授权。
- 新服务需要同时补齐适配器、客服菜单、任务快照、计费单位、进度/失败结果归一化和契约测试，不能只添加 YAML 或元数据。
- 当前绑定表仍是一位客户一条绑定记录；同一客户同时绑定多个平台前，先设计 `(customer_id, service)` 迁移和调度隔离。

## 管理员任务状态

- 任务进度必须来自服务真实上报；未知总数不得伪造百分比。
- 失败记录需要保存任务/关卡、平台诊断或异常类型；异常内容先限长并脱敏。平台没有返回原因时要明确说明“平台未返回诊断信息”，不能用空字符串或占位符掩盖。
- 任务结束不等于业务成功，管理员应结合持久化进度、失败原因和支付状态判断。

## 开发与验收

- 常规测试：`uv run --frozen python -m unittest discover -s tests -q`。
- 前端脚本检查：`node --check src/wecom_kf/admin_assets/console.js`；前端测试：`node --test tests/admin_frontend.test.js`。
- 静态检查：`uv run --frozen ruff check src tests`；构建检查：`uv build --wheel`。
- MySQL 集成测试只能使用数据库名以 `_test` 结尾的隔离实例，设置 `TEST_MYSQL=1` 后运行；没有隔离库时跳过，不得连接生产。
- 修改运行架构、生产域名、GitOps 路径、Secret 名称或安全边界时，同步更新 `docs/integration-release.md` 和本文件；普通业务修改不需要改工作区根规则。

## 发布边界

- 应用发布链路为业务仓库 CI → 腾讯云 TCR → `server-gitops` → Flux → K3s。
- 生产发布前必须完成数据库 schema、OIDC、企业微信回调、Worker 心跳和管理员 API 的真实环境验收。
- 未提供真实朔日地址、隔离账号、依赖锁定、计费/退款规则和提交授权前，不开启朔日真实扣款或成绩提交。

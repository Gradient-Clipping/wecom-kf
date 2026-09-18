# 跨项目衔接与发布检查

本轮修改只在本地，未连接生产数据库、改变 Secret、执行部署或提交 Git。

## 接口与数据边界

- `server-gitops` 的 `wecom-kf-config` 声明公开 OIDC 参数；应用读取环境变量，秘密沿用既有 Secret。
- `/admin/api/metadata` 提供统一服务与任务类型/状态元数据；只列出已实现服务。增加描述不是增加业务执行能力。
- `Store.enqueue` 在同一事务内写 `kf_jobs` 和新增 `kf_job_context`。快照只含 service/account/login_no/created_at；不含 password/profile/payload/result。
- 后台按任务快照显示与搜索账号，不按当前绑定猜测历史。没有快照的旧任务显示“未记录”，仍可按任务ID、客户ID、微信标识定位。不回填不可靠历史。
- 支付查款/支付成功派生的执行任务继承原 purchase 任务的归属，并校验客户及任务类型；旧订单缺失快照时保留未知。付款协议和执行逻辑未改变。
- 机器人新增可选 `job_context` 只读数据表，catalog version 为 6；`jobs.id = job_context.job_id` 可关联历史归属。现有 jobs/bindings 字段保持不变。SQL 模板在 lazycampus-agent/deploy/host 与 server-gitops 的 config、host/agent 三处一致。

## 发布顺序（需由现有受控 GitOps 流程执行）

1. 在隔离 MySQL 验证现有表升级及完整工作流。不要指向生产运行测试；测试库名必须以 `_test` 结尾。
2. 先以新版本的受控初始化/worker 启动流程执行 `Store.initialize()`，创建 `kf_job_context`。这只是新增表，不更改旧表，不回填历史。初始化账号须具备建表权限。不要为了建表随意启动会处理真实消息的 worker。
3. 确认新表存在后发布新 callback/admin 和所有 worker；现有镜像流水线生成新版本，再由 GitOps引用。旧 worker 混跑期间产生的任务没有快照，页面会明确未知；建议按现有 Recreate 策略统一版本。仅改 ConfigMap 不会自动重启既有进程，配置更改也需受控 rollout。
4. 新表存在后，再由机器人既有受控 bootstrap 流程更新只读视图/列授权，然后发布 catalog version 6。不能先发布引用不存在新表的视图；不要扩大数据库账号权限到原始秘密字段。
5. 通过实际 HTTPS 域名检查 SSO、无权限拒绝、任务列表/详情/搜索、服务开关与解绑确认；检查 worker 心跳、企业微信回调和付款回调。测试支付仅使用受控测试订单。

新后台提前于建表部署时，任务查询会返回脱敏 503，而不是伪造空数据。若需要回滚，回滚应用/机器人版本即可；保留新增表及快照，不执行删表。原表和既有 API字段未移除。

## 后续业务扩展边界

当前仅实现头歌。朔日需提供主逻辑后实现服务适配、对话入口、结果归一化及相应测试，不能只加 YAML 或元数据条目。现有绑定仍是每客户一条；同时接入多个平台前需单独设计 `(customer_id, service)` 绑定迁移和任务调度隔离，不在本轮贸然修改生产主键。

未提供真实 MySQL、SSO、企业微信、支付测试环境时，本地离线通过不等于生产联调通过。

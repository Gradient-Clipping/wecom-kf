# 管理员前端

这是微信客服管理台的 Vue 3 + Vite 前端。它不直接连接 MySQL，也不在浏览器保存 OIDC 凭据；所有数据通过后端的 `/admin/api` JSON 接口读取，写操作携带后端签发的 CSRF token。

## 本地开发

```powershell
cd 'C:\kaifa\com two\wecom-kf\frontend'
npm ci
$env:ADMIN_API_TARGET='http://127.0.0.1:8000'
npm run dev
```

生产构建：

```powershell
npm run build
```

构建目录为 `dist/`。容器构建阶段会自动执行同样的命令，并将结果放入后端镜像的 `/opt/admin`；后端通过 `ADMIN_STATIC_DIR` 提供根页面和 `/admin/assets`，因此开发时可以独立运行 Vite，生产时仍由同一域名提供安全会话和 API。

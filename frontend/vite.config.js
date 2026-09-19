import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
const apiTarget = process.env.ADMIN_API_TARGET || 'http://127.0.0.1:8000'
const apiOrigin = new URL(apiTarget).origin
const proxy = Object.fromEntries(['/admin/api', '/admin/auth'].map(path => [path, {
  target: apiTarget,
  changeOrigin: true,
  configure(proxyServer) {
    // The backend's CSRF policy accepts the configured public origin. During
    // Vite development the browser origin is 5173, so proxy mutations as the
    // backend origin while keeping the browser session cookie intact.
    proxyServer.on('proxyReq', proxyReq => proxyReq.setHeader('Origin', apiOrigin))
  },
}]))
export default defineConfig({
  plugins: [vue()],
  // The document is served at the public root, while the ingress already
  // reserves /admin for console APIs and static assets.
  base: '/admin/',
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 5173, strictPort: true, proxy },
  test: { environment: 'jsdom', include: ['src/**/*.test.js'], clearMocks: true },
})

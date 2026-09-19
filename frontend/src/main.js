import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', component: () => import('./views/Overview.vue'), meta: { title: '运营总览' } },
    { path: '/jobs', component: () => import('./views/Jobs.vue'), meta: { title: '任务中心' } },
    { path: '/bindings', component: () => import('./views/Bindings.vue'), meta: { title: '账号绑定' } },
    { path: '/settings', component: () => import('./views/Settings.vue'), meta: { title: '服务设置' } },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})
// Preserve bookmarks from the former server-rendered console.
if (/^#(overview|jobs|bindings|settings)$/.test(location.hash)) location.replace('#/' + location.hash.slice(1))
createApp(App).use(router).mount('#app')


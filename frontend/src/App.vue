<script setup>
import { ref, provide, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { session, loadSession } from './api'
import { loadMetadata } from './metadata'
import Nebula from './components/Nebula.vue'
const route = useRoute(), menu = ref(false), error = ref(''), refreshKey = ref(0)
provide('refreshKey', refreshKey)
const links = [['overview', '总览'], ['jobs', '任务中心'], ['bindings', '账号绑定'], ['settings', '服务设置']]
async function initialize() {
  error.value = ''
  try { await loadSession(); await loadMetadata() } catch(e) { error.value = e.message }
}
watch(() => route.path, () => { menu.value = false })
onMounted(initialize)
</script>
<template>
  <Nebula />
  <div class="app-shell" @keydown.esc="menu = false">
    <button v-if="menu" class="menu-backdrop" aria-label="关闭导航" @click="menu = false"></button>
    <aside class="sidebar" :class="{open:menu}">
      <div class="brand"><span class="brand-mark">L</span> LaZy</div>
      <nav aria-label="主导航"><RouterLink v-for="[path,title] in links" :key="path" :to="'/'+path" class="nav-item" active-class="active">{{ title }}</RouterLink></nav>
      <p class="sidebar-foot">WECHAT CUSTOMER SERVICE<br>每 15 秒同步当前页面</p>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <button class="menu-toggle btn" :aria-expanded="menu" aria-label="切换导航" @click="menu = !menu">☰</button>
        <div><h1>客服运营台</h1><p class="eyebrow">LAZY CAMPUS · SERVICE CONSOLE</p></div>
        <div class="top-actions"><span class="user-pill">{{ session.name || '正在验证登录' }}</span><button class="btn btn-ghost" :disabled="!session.ready" @click="refreshKey++">刷新</button></div>
      </header>
      <main id="main-content">
        <div v-if="error" class="alert" role="alert">{{ error }} <button class="btn" @click="initialize">重新连接</button><a href="/admin/auth/login">重新登录</a></div>
        <RouterView v-else-if="session.ready" />
        <p v-else role="status">正在连接身份服务…</p>
      </main>
      <footer class="footer">LaZy Campus · 客服运营台</footer>
    </div>
  </div>
</template>

import { ref, onMounted, onUnmounted, inject } from 'vue'
import { request } from '../api'
export function useResource(path, { immediate = true } = {}) {
  const data = ref(null), error = ref(''), loading = ref(false), syncedAt = ref(null)
  const refreshKey = inject('refreshKey', ref(0))
  let disposed = false, active = immediate, running = false, queued = false, timer
  async function refresh() {
    active = true
    if (running) { queued = true; return }
    running = true; loading.value = true
    try {
      const result = await request(typeof path === 'function' ? path() : path)
      if (!disposed) { data.value = result; error.value = ''; syncedAt.value = Date.now() }
    } catch (e) { if (!disposed) error.value = e.message }
    finally {
      running = false; loading.value = false
      if (queued && !disposed) { queued = false; refresh() }
    }
  }
  const poll = () => {
    if (active && document.visibilityState === 'visible' && !document.activeElement?.matches('input,select,textarea')) refresh()
  }
  onMounted(() => { if (immediate) refresh(); timer = setInterval(poll, 15000); document.addEventListener('visibilitychange', poll) })
  onUnmounted(() => { disposed = true; clearInterval(timer); document.removeEventListener('visibilitychange', poll) })
  return { data, error, loading, syncedAt, refresh, refreshKey }
}


import { ref } from 'vue'
import { request } from './api'
export const metadata = ref({})
export async function loadMetadata() { metadata.value = await request('/metadata') }
export function label(group, code) {
  const entry = (metadata.value[group] || []).find(item => item.code === code)
  return entry?.label || entry?.name || code || '未记录'
}
export function time(value) {
  return value == null ? '未记录' : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value * 1000))
}


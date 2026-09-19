import { reactive } from 'vue'
export const session = reactive({ name: '', csrf: '', ready: false })
const messages = {
  session_expired: '登录已过期，请重新登录',
  invalid_csrf: '会话校验失效，请刷新页面后重试',
  invalid_origin: '请求来源不被允许',
  invalid_query: '查询条件无效，请检查后重试',
  binding_mismatch: '登录号不匹配或账号绑定已变化',
  binding_busy: '存在进行中任务或未结算订单，暂时不能解绑',
  invalid_customer: '客户编号无效',
  not_found: '记录不存在',
  data_unavailable: '数据暂不可用，请稍后重试',
}
export async function request(path, options = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch('/admin/api' + path, {
      ...options, signal: options.signal || controller.signal, credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf } : {}), ...options.headers },
    })
    if (response.status === 401) {
      session.ready = false
      window.location.assign('/admin/auth/login')
      throw new Error(messages.session_expired)
    }
    const data = await response.json()
    if (!response.ok) throw new Error(messages[data.error] || (response.status === 422 ? '提交内容无效' : '请求失败，请重试'))
    return data
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，请稍后重试')
    throw error
  } finally { clearTimeout(timer) }
}
export const update = (path, value, method = 'PUT') => request(path, { method, body: JSON.stringify(value) })
export async function loadSession() {
  const data = await request('/session')
  Object.assign(session, data, { ready: true })
}


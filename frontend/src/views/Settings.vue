<script setup>
import { ref, watch, computed } from 'vue'
import { update } from '../api'
import { metadata } from '../metadata'
import ResourceState from '../components/ResourceState.vue'
import { useResource } from '../composables/useResource'
const { data, error, loading, syncedAt, refresh, refreshKey } = useResource('/overview')
const saving = ref(false), actionError = ref('')
watch(refreshKey,refresh)
const services = computed(() => [
  ...(metadata.value.services || []).map(s => ({...s, enabled:data.value?.services?.find(x=>x.code===s.code)?.enabled})),
  {code:'human-support', name:'人工客服', enabled:data.value?.human_support_enabled},
])
async function toggle(service) {
  saving.value=true; actionError.value=''
  try {
    await update(service.code === 'human-support' ? '/human-support' : '/services/'+encodeURIComponent(service.code), {enabled:!service.enabled})
    await refresh()
  } catch(e) { actionError.value=e.message }
  finally { saving.value=false }
}
</script>
<template>
  <div class="section-heading"><h2>服务设置</h2></div>
  <ResourceState :error="error" :loading="loading" :synced-at="syncedAt" @retry="refresh" />
  <p v-if="actionError" class="alert" role="alert">{{ actionError }}</p>
  <div class="settings-grid"><article v-for="service in services" :key="service.code" class="setting-card"><div><strong>{{ service.name }}</strong><p class="muted">{{ typeof service.enabled !== 'boolean' ? '状态尚未加载' : service.enabled ? '已开启' : '已关闭' }}</p></div><button class="btn btn-ghost" role="switch" :aria-checked="service.enabled === true" :aria-label="service.name+'开关'" :disabled="saving || loading || typeof service.enabled !== 'boolean'" @click="toggle(service)">{{ service.enabled ? '关闭' : '开启' }}</button></article></div>
</template>

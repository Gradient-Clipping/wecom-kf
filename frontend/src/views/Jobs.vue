<script setup>
import { ref, reactive, watch } from 'vue'
import { useResource } from '../composables/useResource'
import { metadata, label, time } from '../metadata'
import JobProgress from '../components/JobProgress.vue'
import JobDrawer from '../components/JobDrawer.vue'
import ResourceState from '../components/ResourceState.vue'
const empty = () => ({ q:'', status:'', kind:'', from:'', to:'' })
const draft = reactive(empty()), applied = ref(empty()), page = ref(1), pageSize = ref(20), selected = ref(null)
function path() {
  const params = new URLSearchParams({ page:String(page.value), page_size:String(pageSize.value) })
  for(const [key,value] of Object.entries(applied.value)) {
    if (!value) continue
    params.set(key, key === 'from' || key === 'to' ? String(Math.floor(new Date(value + (key === 'from' ? 'T00:00:00+08:00' : 'T23:59:59+08:00')).getTime()/1000)) : value)
  }
  return '/jobs?' + params
}
const { data, error, loading, syncedAt, refresh, refreshKey } = useResource(path)
watch(refreshKey, refresh)
function query() { applied.value = {...draft}; page.value = 1; refresh() }
function clear() { Object.assign(draft,empty()); query() }
async function turn(next) { page.value = next; await refresh() }
</script>
<template>
  <div class="section-heading"><div><p class="eyebrow">执行记录</p><h2>任务中心</h2></div><button class="btn btn-ghost" @click="clear">清空筛选</button></div>
  <ResourceState :error="error" :loading="loading" :synced-at="syncedAt" @retry="refresh" />
  <form class="filters" @submit.prevent="query">
    <label>关键词<input v-model="draft.q" maxlength="128" placeholder="任务、客户、账号或微信标识"></label>
    <label>状态<select v-model="draft.status"><option value="">全部状态</option><option v-for="s in metadata.job_statuses?.filter(s => s.filterable !== false)" :key="s.code" :value="s.code">{{ s.label }}</option></select></label>
    <label>类型<select v-model="draft.kind"><option value="">全部类型</option><option v-for="s in metadata.job_kinds" :key="s.code" :value="s.code">{{ s.label }}</option></select></label>
    <label>开始日期<input v-model="draft.from" type="date"></label><label>结束日期<input v-model="draft.to" type="date"></label>
    <button class="btn btn-primary" :disabled="loading">查询</button>
  </form>
  <div v-if="data" class="table-wrap">
    <table><thead><tr><th>任务</th><th>账号 / 客户</th><th>类型</th><th>状态</th><th>进度与失败原因</th><th>更新时间</th><th>操作</th></tr></thead>
      <tbody><tr v-for="job in data.items" :key="job.id">
        <td class="identifier" :title="job.id">{{ job.id }}</td><td class="identifier" :title="job.customer_id">{{ job.account || job.customer_id }}</td>
        <td>{{ label('job_kinds',job.kind) }}</td><td><span class="badge" :class="job.status==='failed'?'bad':''">{{ label('job_statuses',job.status) }}</span></td>
        <td><JobProgress :job="job" /></td><td>{{ time(job.updated_at) }}</td><td><button class="btn btn-ghost" @click="selected=job.id">查看</button></td>
      </tr><tr v-if="!data.items.length"><td colspan="7" class="empty">没有匹配任务</td></tr></tbody>
    </table>
  </div>
  <div v-if="data" class="pager"><label>每页 <select v-model.number="pageSize" :disabled="loading" @change="query"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option></select> 条</label>
    <button :disabled="loading || data.page <= 1" @click="turn(data.page-1)">上一页</button><span>第 {{ data.page }} / {{ Math.max(1,data.pages) }} 页 · {{ data.total }} 条</span><button :disabled="loading || data.page >= data.pages" @click="turn(data.page+1)">下一页</button>
  </div>
  <JobDrawer v-if="selected" :id="selected" @close="selected=null" />
</template>

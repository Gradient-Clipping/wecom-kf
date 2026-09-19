<script setup>
import { computed, watch } from 'vue'
import { useResource } from '../composables/useResource'
import { metadata, label } from '../metadata'
import ResourceState from '../components/ResourceState.vue'
const { data, error, loading, syncedAt, refresh, refreshKey } = useResource('/overview')
watch(refreshKey, refresh)
const counts = computed(() => data.value?.counts || [])
const count = group => counts.value.filter(x => !group || metadata.value.job_statuses?.find(s => s.code === x.status)?.group === group).reduce((sum,x) => sum + x.count, 0)
const metrics = computed(() => [['全部任务',count()],['进行中',count('active')],['已结束',count('ended')],['已绑定账号',data.value?.bindings]])
</script>
<template>
  <div class="section-heading"><div><p class="eyebrow">实时概况</p><h2>运营总览</h2></div></div>
  <ResourceState :error="error" :loading="loading" :synced-at="syncedAt" @retry="refresh" />
  <template v-if="data">
    <div class="metric-grid"><article v-for="[title,value] in metrics" :key="title" class="metric-card"><p class="metric-label">{{ title }}</p><strong class="metric-value">{{ value }}</strong><p class="metric-note">{{ title === '已结束' ? '结束不代表业务成功' : '全库统计' }}</p></article></div>
    <div class="overview-grid">
      <section class="panel"><h3>任务状态</h3><div v-for="item in counts" :key="item.kind+item.status" class="status-line"><span>{{ label('job_kinds',item.kind) }} · {{ label('job_statuses',item.status) }}</span><strong>{{ item.count }}</strong></div><p v-if="!counts.length" class="muted">暂无任务</p></section>
      <section class="panel"><h3>运行进程</h3><div v-for="worker in data.workers" :key="worker.role" class="worker-line"><span>{{ worker.role }}</span><span class="badge" :class="worker.healthy ? 'good' : 'warn'">{{ worker.heartbeat == null ? '尚未上报' : worker.healthy ? '正常' : '心跳延迟' }}</span></div><p v-if="!data.workers.length" class="muted">暂无心跳记录</p></section>
      <section class="panel"><h3>消息投递</h3><div v-for="item in data.replies" :key="item.status" class="reply-line"><span>{{ label('reply_statuses',item.status) }}</span><strong>{{ item.count }}</strong></div><p v-if="!data.replies.length" class="muted">暂无投递记录</p></section>
    </div>
  </template>
</template>

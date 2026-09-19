<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import JobProgress from './JobProgress.vue'
import ResourceState from './ResourceState.vue'
import { useResource } from '../composables/useResource'
import { label, time } from '../metadata'
const props = defineProps({ id: String })
const emit = defineEmits(['close'])
const dialog = ref()
const { data, error, loading, syncedAt, refresh } = useResource(() => '/jobs/' + encodeURIComponent(props.id))
watch(() => props.id, refresh)
let previous
onMounted(() => { previous = document.activeElement; dialog.value.showModal() })
onUnmounted(() => previous?.focus())
</script>
<template>
  <dialog ref="dialog" class="job-dialog" aria-labelledby="detail-title" @cancel.prevent="emit('close')" @click="event => { if(event.target === dialog) emit('close') }">
    <header class="drawer-head"><h2 id="detail-title">任务详情</h2><button class="btn" autofocus @click="emit('close')">关闭</button></header>
    <ResourceState :error="error" :loading="loading" :synced-at="syncedAt" @retry="refresh" />
    <template v-if="data">
      <dl><div v-for="(value,key) in {'任务 ID':data.job.id,'状态':label('job_statuses',data.job.status),'服务':label('services',data.job.service),'账号':data.job.account || '未记录','客户':data.job.customer_id,'创建时间':time(data.job.created_at),'更新时间':time(data.job.updated_at)}" :key="key" class="detail-row"><dt>{{ key }}</dt><dd>{{ value }}</dd></div></dl>
      <JobProgress :job="data.job" />
      <h3>失败原因</h3>
      <p v-for="(failure,index) in data.job.progress?.failures || []" :key="index" class="failure-detail">{{ failure }}</p>
      <p v-if="!data.job.progress?.failures?.length" class="muted">{{ data.job.status === 'failed' || data.job.progress?.has_error ? '该任务未保存详细失败原因，无法从历史记录恢复。' : '该任务没有上报失败记录。' }}</p>
      <p class="muted">任务结束不代表业务成功，请结合进度和失败原因判断。</p>
    </template>
  </dialog>
</template>

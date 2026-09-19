<script setup>
import { computed } from 'vue'
import { jobProgressModel } from '../progress'
const props = defineProps({ job: { type: Object, required: true } })
const model = computed(() => jobProgressModel(props.job))
</script>
<template>
  <div class="job-progress">
    <div class="progress-caption">{{ model.summary }} <strong v-if="model.known">{{ model.percent }}%</strong></div>
    <progress v-if="model.solve" class="job-progress-bar" :value="model.known ? model.done : undefined" :max="model.known ? model.total : 100" :aria-label="model.summary"></progress>
    <p class="progress-current">{{ model.current }}</p>
    <span v-if="model.failed || model.error !== '错误状态未上报'" class="badge" :class="model.failed ? 'bad' : model.unknown ? 'warn' : ''">{{ model.error }}</span>
    <p v-if="model.failures.length" class="progress-error">{{ model.failures[0] }}</p>
  </div>
</template>

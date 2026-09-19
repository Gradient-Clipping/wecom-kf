<script setup>
defineProps({ error: String, loading: Boolean, syncedAt: Number })
defineEmits(['retry'])
</script>
<template>
  <div v-if="error" class="alert" role="alert">{{ error }}<span v-if="syncedAt"> · 保留上次成功数据</span> <button class="btn" @click="$emit('retry')">重试</button></div>
  <p class="muted" role="status">{{ loading ? '正在同步…' : syncedAt ? '最近同步：' + new Date(syncedAt).toLocaleTimeString('zh-CN') : '尚未同步' }}</p>
</template>


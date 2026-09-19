<script setup>
import { ref, watch } from 'vue'
import { update } from '../api'
import { useResource } from '../composables/useResource'
import ResourceState from '../components/ResourceState.vue'
import { time } from '../metadata'
const draft = ref(''), query = ref(''), confirming = ref(null), login = ref(''), saving = ref(false), actionError = ref(''), notice = ref('')
const { data, error, loading, syncedAt, refresh, refreshKey } = useResource(() => '/bindings?q='+encodeURIComponent(query.value), {immediate:false})
watch(refreshKey, () => { if(data.value) refresh() })
function search() { query.value = draft.value; refresh() }
async function unbind() {
  saving.value = true; actionError.value = ''; notice.value = ''
  try { await update('/bindings/'+confirming.value.customer_id+'/unbind', {login_no:login.value}, 'POST'); confirming.value=null; login.value=''; notice.value='账号已解绑'; await refresh() }
  catch(e) { actionError.value=e.message }
  finally { saving.value=false }
}
</script>
<template>
  <div class="section-heading"><h2>账号绑定</h2></div>
  <ResourceState :error="error" :loading="loading" :synced-at="syncedAt" @retry="refresh" />
  <p v-if="notice" class="alert ok" role="status">{{ notice }}</p>
  <form class="binding-search" @submit.prevent="search"><label for="binding-query">查询账号</label><input id="binding-query" v-model="draft" maxlength="128" placeholder="账号、客户 ID、登录号或微信标识"><button class="btn btn-primary" :disabled="loading">查询</button></form>
  <p v-if="!data" class="muted">查询后展示匹配的绑定，最多 100 条；结果较多时请使用完整账号定位。</p>
  <div v-else class="table-wrap"><table><thead><tr><th>客户</th><th>账号</th><th>登录号</th><th>微信标识</th><th>绑定时间</th><th>操作</th></tr></thead>
    <tbody><tr v-for="row in data.items" :key="row.customer_id"><td class="identifier" :title="row.customer_id">{{ row.customer_id }}</td><td>{{ row.account }}</td><td>{{ row.login_no }}</td><td class="identifier" :title="row.external_userid">{{ row.external_userid }}</td><td>{{ time(row.created_at) }}</td><td><button class="btn btn-ghost" @click="confirming=row;login='';actionError=''">解绑</button></td></tr><tr v-if="!data.items.length"><td colspan="6" class="empty">没有匹配绑定</td></tr></tbody>
  </table></div>
  <section v-if="confirming" class="panel confirm-panel" aria-labelledby="confirm-title">
    <h3 id="confirm-title">确认解绑 {{ confirming.account }}</h3><p>请输入该账号的登录号确认。进行中任务或未结算订单会阻止解绑。</p>
    <p v-if="actionError" class="alert" role="alert">{{ actionError }}</p>
    <form class="binding-search" @submit.prevent="unbind"><label for="login-confirm">登录号</label><input id="login-confirm" v-model="login" required maxlength="128" :disabled="saving"><button class="btn btn-primary" :disabled="saving">确认解绑</button><button type="button" class="btn" :disabled="saving" @click="confirming=null">取消</button></form>
  </section>
</template>

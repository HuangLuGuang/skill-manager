<template>
  <div class="iam-page">
    <header class="iam-header">
      <div><h2>{{ t(`iam.${kind}`) }}</h2><p>{{ t(`iam.pageDescriptions.${kind}`) }}</p></div>
      <a-space wrap>
        <a-button :loading="loading" :disabled="submitting" @click="load">{{ t('iam.refresh') }}</a-button>
        <a-button v-if="can(`${kind}:create`) && (kind !== 'users' || can('users:assign_role'))" type="primary" :disabled="submitting" @click="openCreate()">{{ t('iam.create') }}</a-button>
      </a-space>
    </header>
    <p v-if="kind === 'users'">{{ t('iam.timezone') }}</p>
    <a-alert v-if="kind === 'menus'" :message="t('iam.menuHint')" type="info" show-icon class="iam-note" />
    <a-card>
      <div class="iam-filters"><a-space wrap>
        <a-input v-if="kind !== 'menus'" v-model:value="filters.q" :placeholder="t(kind === 'roles' ? 'iam.roleKeyword' : 'iam.accountKeyword')" allow-clear @pressEnter="search" />
        <template v-if="kind === 'users'">
          <a-select v-model:value="filters.role" :placeholder="t('iam.role')" allow-clear :options="roleOptions" />
          <a-select v-model:value="filters.active" :placeholder="t('iam.status')" allow-clear :options="statusOptions" />
          <a-select v-model:value="filters.group_id" :placeholder="t('iam.groups')" allow-clear :options="groupOptions" />
        </template>
        <template v-if="kind !== 'menus'">
          <a-button type="primary" :disabled="loading" @click="search">{{ t('iam.search') }}</a-button>
          <a-button :disabled="loading" @click="reset">{{ t('iam.reset') }}</a-button>
        </template>
        <template v-else>
          <a-button @click="expanded = rows.map(item => item.name)">{{ t('iam.expand') }}</a-button>
          <a-button @click="expanded = []">{{ t('iam.collapse') }}</a-button>
        </template>
      </a-space></div>
      <a-table :columns="columns" :data-source="kind === 'menus' ? menuTree : rows" :row-key="kind === 'users' ? 'id' : 'name'"
        :loading="loading" :pagination="kind === 'menus' ? false : pagination" :scroll="{ x: 1050 }"
        v-model:expandedRowKeys="expanded" @change="tableChange">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'role'"><a-tag>{{ roleLabel(record.role) }}</a-tag></template>
          <template v-else-if="column.key === 'group_ids'">{{ record.group_ids.map(id => options.groups.find(g => g.id === id)?.name || id).join(', ') || '—' }}</template>
          <template v-else-if="column.key === 'is_active'"><a-tag :color="record.is_active ? 'green' : 'default'">{{ t(record.is_active ? 'iam.enabled' : 'iam.disabled') }}</a-tag></template>
          <template v-else-if="column.key === 'is_system'"><a-tag>{{ t(record.is_system ? 'iam.system' : 'iam.custom') }}</a-tag></template>
          <template v-else-if="column.key === 'display_name'">{{ record.display_key ? t(record.display_key) : record.display_name }}</template>
          <template v-else-if="column.key === 'title'">{{ record.title_key ? t(record.title_key) : locale === 'en-US' ? record.title_en : record.title_zh }}</template>
          <template v-else-if="column.key === 'actions'">
            <a-space wrap size="small" class="iam-actions">
              <a-button v-if="can(`${kind}:update`) || (kind === 'users' && can('users:assign_role'))" type="link" size="small" :disabled="submitting" @click="openEdit(record)">{{ t('iam.edit') }}</a-button>
              <template v-if="kind === 'users'">
                <a-button v-if="can('users:reset_password')" type="link" size="small" :disabled="submitting" @click="openPassword(record)">{{ t('iam.passwordReset') }}</a-button>
                <a-popconfirm v-if="can('users:set_status')" :title="t('iam.statusConfirm')" @confirm="toggleUser(record)">
                  <a-button type="link" size="small" :disabled="submitting">{{ t(record.is_active ? 'iam.disable' : 'iam.enable') }}</a-button>
                </a-popconfirm>
              </template>
              <a-button v-if="kind === 'roles' && can('roles:grant')" type="link" size="small" :disabled="submitting || ['admin', 'super_admin'].includes(record.name)" @click="openGrant(record)">{{ t('iam.permissions') }}</a-button>
              <template v-if="kind === 'menus'">
                <a-popconfirm v-if="can('menus:set_status')" :title="t('iam.statusConfirm')" @confirm="toggleMenu(record)">
                  <a-button type="link" size="small" :disabled="submitting">{{ t(record.is_active ? 'iam.disable' : 'iam.enable') }}</a-button>
                </a-popconfirm>
                <a-button v-if="!record.path && can('menus:create')" type="link" size="small" :disabled="submitting" @click="openCreate(record.name)">{{ t('iam.child') }}</a-button>
                <a-button v-if="can('menus:sort')" type="link" size="small" :disabled="submitting" @click="move(record, 'up')">{{ t('iam.up') }}</a-button>
                <a-button v-if="can('menus:sort')" type="link" size="small" :disabled="submitting" @click="move(record, 'down')">{{ t('iam.down') }}</a-button>
              </template>
              <a-popconfirm v-if="can(`${kind}:delete`) && !record.is_system" :title="t('iam.deleteConfirm')" @confirm="remove(record)">
                <a-button danger type="link" size="small" :disabled="submitting">{{ t('iam.delete') }}</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="formOpen" :title="t(mode === 'password' ? 'iam.passwordReset' : editing ? 'iam.edit' : 'iam.create')"
      :confirm-loading="submitting" :ok-button-props="{ disabled: submitting }" :cancel-button-props="{ disabled: submitting }"
      :mask-closable="!submitting" :closable="!submitting" :keyboard="!submitting" :width="640" @ok="save">
      <a-form ref="formRef" layout="vertical" :model="form" class="iam-form">
        <template v-if="kind === 'users'">
          <a-form-item :label="t('iam.username')" name="username" :rules="required"><a-input v-model:value="form.username" :disabled="!!editing" :maxlength="64" /></a-form-item>
          <template v-if="mode !== 'password'">
            <a-form-item :label="t('iam.email')" name="email" :rules="[{ type: 'email', message: t('iam.invalidEmail') }]"><a-input v-model:value="form.email" :disabled="!!editing && !can('users:update')" /></a-form-item>
            <a-form-item :label="t('iam.role')" name="role" :rules="required">
              <a-select v-model:value="form.role" :disabled="!can('users:assign_role')" :options="assignableRoleOptions" />
              <div class="iam-help">{{ options.roles.find(r => r.name === form.role)?.description }}</div>
            </a-form-item>
            <a-form-item :label="t('iam.groups')"><a-select v-model:value="form.group_ids" mode="multiple" :options="groupOptions" :disabled="!!editing && !can('users:update')" /></a-form-item>
          </template>
          <a-form-item v-if="!editing || mode === 'password'" :label="t('iam.password')" name="password" :rules="required" :extra="t('iam.passwordHint')">
            <a-input-password v-model:value="form.password" autocomplete="new-password" />
          </a-form-item>
          <a-form-item v-if="!editing" :label="t('iam.status')"><a-switch v-model:checked="form.is_active" /></a-form-item>
        </template>
        <template v-else-if="kind === 'roles'">
          <a-form-item :label="t('iam.name')" name="name" :rules="required"><a-input v-model:value="form.name" :disabled="!!editing" :maxlength="64" /></a-form-item>
          <a-form-item :label="t('iam.displayName')" name="display_name" :rules="required"><a-input v-model:value="form.display_name" :maxlength="128" /></a-form-item>
          <a-form-item :label="t('iam.description')"><a-textarea v-model:value="form.description" :maxlength="2000" :rows="3" /></a-form-item>
          <a-form-item v-if="editing" :label="t('iam.home')"><a-select v-model:value="form.default_path" :options="homeOptions(editing.permissions)" /></a-form-item>
        </template>
        <template v-else>
          <a-form-item :label="t('iam.name')" name="name" :rules="required"><a-input v-model:value="form.name" :disabled="!!editing" :maxlength="64" /></a-form-item>
          <div class="iam-grid">
            <a-form-item :label="t('iam.titleZh')" name="title_zh" :rules="required"><a-input v-model:value="form.title_zh" :maxlength="128" /></a-form-item>
            <a-form-item :label="t('iam.titleEn')" name="title_en" :rules="required"><a-input v-model:value="form.title_en" :maxlength="128" /></a-form-item>
          </div>
          <a-form-item :label="t('iam.parent')"><a-select v-model:value="form.parent_name" :disabled="!!editing && !can('menus:sort')" :options="parentOptions" /></a-form-item>
          <a-form-item :label="t('iam.path')"><a-select v-model:value="form.path" show-search :options="pageOptions" /></a-form-item>
          <div class="iam-grid">
            <a-form-item :label="t('iam.icon')"><a-select v-model:value="form.icon" :options="options.icons.map(value => ({ value, label: value }))" /></a-form-item>
            <a-form-item :label="t('iam.sort')"><a-input-number v-model:value="form.sort_order" :disabled="!!editing && !can('menus:sort')" :min="0" :max="100000" /></a-form-item>
          </div>
          <a-form-item :label="t('iam.status')"><a-switch v-model:checked="form.is_active" :disabled="!!editing && !can('menus:set_status')" /></a-form-item>
        </template>
      </a-form>
    </a-modal>

    <a-modal v-model:open="grantOpen" :title="t('iam.permissions')" :width="900" :confirm-loading="submitting"
      :ok-button-props="{ disabled: submitting }" :cancel-button-props="{ disabled: submitting }" :mask-closable="!submitting" :closable="!submitting" :keyboard="!submitting" @ok="saveGrant">
      <a-alert :message="t('iam.permissionHint')" type="info" show-icon class="iam-note" />
      <p><strong>{{ roleLabel(editing?.name) }}</strong> · {{ t('iam.selected', { count: granted.length }) }}</p>
      <div class="iam-grants">
        <section v-for="(actions, module) in options.modules" :key="module" class="iam-grant-group">
          <div class="iam-header"><strong>{{ t(`iam.modules.${module}`) }}</strong>
            <a-space><a-button type="link" size="small" @click="selectModule(module, actions)">{{ t('iam.selectAll') }}</a-button>
              <a-button type="link" size="small" @click="granted = granted.filter(code => !code.startsWith(`${module}:`))">{{ t('iam.clear') }}</a-button></a-space>
          </div>
          <a-checkbox-group v-model:value="granted" class="iam-checks">
            <a-checkbox v-for="action in actions.split(' ')" :key="action" :value="`${module}:${action}`" :disabled="!canGrant(`${module}:${action}`)">{{ t(`iam.operations.${action}`) }}</a-checkbox>
          </a-checkbox-group>
        </section>
      </div>
      <a-form layout="vertical"><a-form-item :label="t('iam.home')"><a-select v-model:value="grantHome" :options="homeOptions(granted)" /></a-form-item></a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { iamList, iamOptions, iamCreate, iamUpdate, iamDelete, iamAction, iamGrant } from '../api'
import { can, refreshAccess } from '../access'
import { formatBeijingDateTime as formatDateTime } from '../utils/format'

const route = useRoute()
const { t, locale } = useI18n()
const kind = computed(() => route.meta.iamKind)
const rows = ref([]), loading = ref(false), submitting = ref(false), expanded = ref([])
const loadState = { version: 0 }
const formOpen = ref(false), grantOpen = ref(false), editing = ref(null), mode = ref('edit'), formRef = ref()
const form = reactive({}), granted = ref([]), grantHome = ref('')
const options = reactive({ roles: [], groups: [], pages: {}, home_pages: [], icons: [], modules: {} })
const filters = reactive({ q: '', role: undefined, active: undefined, group_id: undefined })
const pager = reactive({ current: 1, pageSize: 20, total: 0, sort: 'created_at', order: 'desc' })
const required = computed(() => [{ required: true, message: t('iam.required') }])
const pagination = computed(() => ({ ...pager, showSizeChanger: true, showTotal: count => t('iam.total', { count }) }))
const statusOptions = computed(() => [true, false].map(value => ({ value, label: t(value ? 'iam.enabled' : 'iam.disabled') })))
const roleLabel = name => {
  const row = options.roles.find(r => r.name === name)
  return row?.display_key ? t(row.display_key) : row?.display_name || name
}
const roleOptions = computed(() => options.roles.map(r => ({ value: r.name, label: `${roleLabel(r.name)} (${r.name})` })))
const assignableRoleOptions = computed(() => roleOptions.value.filter(option => options.roles.find(r => r.name === option.value)?.assignable))
const groupOptions = computed(() => options.groups.map(g => ({ value: g.id, label: g.name })))
const pageOptions = computed(() => [{ value: '', label: t('iam.directory') }, ...Object.keys(options.pages).map(value => ({ value, label: value }))])
const parentOptions = computed(() => [{ value: '', label: t('iam.root') }, ...rows.value.filter(r => !r.path && r.name !== editing.value?.name).map(r => ({ value: r.name, label: locale.value === 'en-US' ? r.title_en : r.title_zh }))])
const homeOptions = codes => [{ value: '', label: t('iam.autoHome') }, ...Object.entries(options.pages).filter(([path, code]) => options.home_pages.includes(path) && (path === '/system-audit' ? ['audit:login', 'audit:operation', 'audit:security'].some(item => codes?.includes(item)) : codes?.includes(code))).map(([value]) => ({ value, label: value }))]
const columns = computed(() => {
  const fields = kind.value === 'users'
    ? [['username', 'username'], ['email', 'email'], ['role', 'role'], ['group_ids', 'groups'], ['is_active', 'status'], ['created_at', 'createdAt'], ['last_login_at', 'lastLogin']]
    : kind.value === 'roles' ? [['name', 'name'], ['display_name', 'displayName'], ['description', 'description'], ['default_path', 'home'], ['user_count', 'userCount'], ['is_system', 'type']]
      : [['title', 'displayName'], ['name', 'name'], ['path', 'path'], ['icon', 'icon'], ['sort_order', 'sort'], ['is_active', 'status']]
  return [...fields.map(([key, label]) => ({ key, dataIndex: key, title: t(`iam.${label}`),
    ...(key.endsWith('_at') ? { sorter: true, customRender: ({ text }) => text ? formatDateTime(text) : '—' } : {}),
  })), { key: 'actions', title: t('iam.actions'), width: kind.value === 'menus' ? 310 : 260 }]
})
const menuTree = computed(() => {
  const nodes = Object.fromEntries(rows.value.map(row => [row.name, { ...row }]))
  const roots = []
  for (const row of rows.value) {
    if (row.parent_name && nodes[row.parent_name]) (nodes[row.parent_name].children ||= []).push(nodes[row.name])
    else roots.push(nodes[row.name])
  }
  return roots
})
const error = e => message.error(typeof e.response?.data?.detail === 'string' ? e.response.data.detail : t('iam.failed'))
async function load() {
  const version = ++loadState.version
  const requestedKind = kind.value
  loading.value = true
  try {
    const [data, opts] = await Promise.all([iamList(requestedKind, { ...filters, page: pager.current, page_size: pager.pageSize, sort: pager.sort, order: pager.order }), iamOptions()])
    if (version !== loadState.version || requestedKind !== kind.value) return
    rows.value = requestedKind === 'menus' ? data : data.items
    pager.total = data.total || 0
    Object.assign(options, opts)
  } catch (e) { if (version === loadState.version) error(e) }
  finally { if (version === loadState.version) loading.value = false }
}
function search() { pager.current = 1; load() }
function reset() { Object.assign(filters, { q: '', role: undefined, active: undefined, group_id: undefined }); search() }
function tableChange(p, _, sorter) {
  Object.assign(pager, { current: p.current, pageSize: p.pageSize })
  if (sorter?.field) {
    pager.sort = sorter.order ? sorter.field : 'created_at'
    pager.order = sorter.order === 'ascend' ? 'asc' : 'desc'
  }
  load()
}
function setForm(data) { for (const key of Object.keys(form)) delete form[key]; Object.assign(form, data); formRef.value?.clearValidate() }
function openCreate(parent = '') {
  editing.value = null; mode.value = 'edit'
  setForm(kind.value === 'users' ? { username: '', email: '', password: '', role: 'user', group_ids: [], is_active: true }
    : kind.value === 'roles' ? { name: '', display_name: '', description: '', default_path: '' }
      : { name: '', parent_name: parent, title_zh: '', title_en: '', path: '', icon: 'setting', sort_order: rows.value.length, is_active: true })
  formOpen.value = true
}
function openEdit(row) { editing.value = row; mode.value = 'edit'; setForm({ ...row, group_ids: [...(row.group_ids || [])], parent_name: row.parent_name || '', path: row.path || '' }); formOpen.value = true }
function openPassword(row) { editing.value = row; mode.value = 'password'; setForm({ username: row.username, password: '' }); formOpen.value = true }
async function mutate(fn) {
  if (submitting.value) return
  submitting.value = true
  try { await fn(); message.success(t('iam.saved')); await refreshAccess(); await load() }
  catch (e) { error(e) } finally { submitting.value = false }
}
async function save() {
  if (submitting.value) return
  try { await formRef.value.validate() } catch { return }
  await mutate(async () => {
    if (mode.value === 'password') await iamAction('users', editing.value.id, 'password', { password: form.password })
    else {
      let payload
      if (kind.value === 'users') {
        payload = editing.value ? Object.fromEntries(['email', 'role', 'group_ids'].filter(key => JSON.stringify(form[key]) !== JSON.stringify(editing.value[key])).map(key => [key, key === 'email' ? form[key] || null : form[key]])) : { ...form, email: form.email || null }
      } else if (kind.value === 'roles') payload = { display_name: form.display_name, description: form.description, default_path: form.default_path, ...(!editing.value ? { name: form.name } : {}) }
      else payload = { parent_name: form.parent_name || null, title_zh: form.title_zh, title_en: form.title_en, path: form.path || null, icon: form.icon, sort_order: form.sort_order, is_active: form.is_active, ...(!editing.value ? { name: form.name } : {}) }
      if (editing.value) { if (Object.keys(payload).length) await iamUpdate(kind.value, editing.value.id || editing.value.name, payload) }
      else await iamCreate(kind.value, payload)
    }
    formOpen.value = false; form.password = ''
  })
}
const remove = row => mutate(() => iamDelete(kind.value, row.id || row.name))
const toggleUser = row => mutate(() => iamUpdate('users', row.id, { is_active: !row.is_active }))
const toggleMenu = row => mutate(() => iamAction('menus', row.name, 'status', { is_active: !row.is_active }))
const move = (row, direction) => mutate(() => iamAction('menus', row.name, 'move', { direction }))
function openGrant(row) { editing.value = row; granted.value = [...row.permissions]; grantHome.value = row.default_path; grantOpen.value = true }
const canGrant = code => options.roles.find(row => row.name === editing.value?.name)?.grantable_permissions?.includes(code) && can(code)
function selectModule(module, actions) { granted.value = [...new Set([...granted.value, ...actions.split(' ').map(action => `${module}:${action}`).filter(canGrant)])] }
const saveGrant = () => mutate(async () => { await iamGrant(editing.value.name, { permissions: granted.value, default_path: grantHome.value }); grantOpen.value = false })
watch(kind, () => { rows.value = []; pager.current = 1; formOpen.value = false; grantOpen.value = false; reset() })
onMounted(load)
onUnmounted(() => { loadState.version += 1 })
</script>

<style scoped>
.iam-page { max-width: 1600px; margin: 0 auto; }
.iam-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
h2 { margin: 0 0 6px; } p, .iam-help { color: #64748b; }
.iam-filters { margin-bottom: 20px; } .iam-filters :deep(.ant-select) { min-width: 170px; }
.iam-filters :deep(.ant-input-affix-wrapper) { width: 260px; }
.iam-note { margin-bottom: 18px; } .iam-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.iam-grants { max-height: 50vh; overflow: auto; padding-right: 8px; margin-bottom: 16px; }
.iam-grant-group { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.iam-checks { display: flex; gap: 12px; flex-wrap: wrap; } .iam-actions { max-width: 310px; }
@media (max-width: 640px) { .iam-grid { grid-template-columns: 1fr; gap: 0; } .iam-filters :deep(.ant-input-affix-wrapper) { width: 220px; } }
</style>

<template>
  <div>
    <a-page-header :title="$t('legacy.kh1ras')" :sub-title="$t('legacy.2fxvx')" />

    <a-card style="margin-top: 16px">
      <a-space style="margin-bottom: 16px" wrap>
        <a-segmented v-model:value="activeTab" :options="tabs" />
        <a-select v-model:value="risk" style="width: 160px">
          <a-select-option value="all">{{ $t("legacy.hah0r4") }}</a-select-option>
          <a-select-option value="benign">benign</a-select-option>
          <a-select-option value="suspicious">suspicious</a-select-option>
          <a-select-option value="malicious">malicious</a-select-option>
        </a-select>
        <a-input v-model:value="keyword" :placeholder="$t('legacy.m25h41')" style="width: 240px" allow-clear />
        <a-button type="primary" @click="fetchRows" :loading="loading">{{ $t("legacy.16mfmhy") }}</a-button>
        <a-button @click="resetFilters" :disabled="loading">{{ $t("legacy.1wq9feq") }}</a-button>
        <a-button @click="fetchRows" :loading="loading">{{ $t("legacy.12qo56a") }}</a-button>
      </a-space>

      <div class="table-meta"> {{ $t("legacy.1vsm2qk") }} {{ total }} {{ $t("legacy.conkzy") }} {{ activeTab === 'ready' ? $t('legacy.k2spsg') : $t('legacy.1t00jqn') }}
      </div>

      <a-table
        :data-source="rows"
        :columns="columns"
        rowKey="skill_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: activeTab === 'ready' ? $t('legacy.1gwlzz1') : $t('legacy.iag57a') }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.name }}</a>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)" :title="statusTitle(record.status)">{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.key === 'risk_level'">
            <a-tag v-if="record.risk_level === 'malicious'" color="red" :title="$t('legacy.m36raq')">malicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange" :title="$t('legacy.1x3ukv1')">suspicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'benign'" color="green" :title="$t('legacy.1apxo2s')">benign</a-tag>
            <a-tag v-else color="default">-</a-tag>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button
                v-if="record.status === 'APPROVED'"
                size="small"
                type="primary"
                :loading="actionLoading && selectedRecord?.skill_id === record.skill_id && deployMode"
                @click="handleDeploy(record)"
              > {{ $t("legacy.1sp0ywv") }} </a-button>
              <a-button
                v-if="record.status === 'DEPLOYED'"
                size="small"
                danger
                @click="openRetireModal(record)"
              > {{ $t("legacy.1vpkzo2") }} </a-button>
              <a-button size="small" @click="$router.push(`/skills/${record.skill_id}`)">{{ $t("legacy.xc5h04") }}</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="retireModalOpen"
      :title="$t('legacy.jedo35')"
      :ok-text="$t('legacy.zr93e4')"
      :cancel-text="$t('legacy.1589w37')"
      :confirm-loading="actionLoading"
      @ok="submitRetire"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="selectedRecord?.name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.125mnpo')">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1pkmunp')" required>
          <a-textarea v-model:value="retireReason" :rows="4" :placeholder="$t('legacy.g1u22u')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { translateLegacy as phrase, translateText as text } from '../i18n'

import { onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'

import { deploySkill, listSkillsPaged, retireSkill } from '../api'
import { formatDateTime } from '../utils/format'
import { lifecycleVersionId } from '../utils/skillVersions'

const activeTab = ref('ready')
const risk = ref('all')
const keyword = ref('')
const loading = ref(false)
const actionLoading = ref(false)
const deployMode = ref(false)
const rows = ref([])
const total = ref(0)
const selectedRecord = ref(null)
const retireModalOpen = ref(false)
const retireReason = ref('')
const sortState = ref({ field: 'submitted_at', order: 'descend' })
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: value => text(`共 ${value} 条`, `${value} total`),
})

const tabs = [
  { label: phrase('legacy.1px7mf2'), value: 'ready' },
  { label: phrase('legacy.1t00jqn'), value: 'deployed' },
]

const columns = [
  { title: phrase('legacy.1k4wwtv'), dataIndex: 'name', key: 'name', sorter: true },
  { title: 'Skill ID', dataIndex: 'skill_id', key: 'skill_id', sorter: true },
  { title: phrase('legacy.1ccx4t4'), dataIndex: 'status', key: 'status', width: 140, sorter: true },
  { title: phrase('legacy.1qgsa3s'), dataIndex: 'risk_level', key: 'risk_level', width: 120, sorter: true },
  { title: phrase('legacy.1tve2zn'), dataIndex: 'submitted_at', key: 'submitted_at', width: 190, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: phrase('legacy.501w24'), key: 'actions', width: 220 },
]

const fetchRows = async () => {
  loading.value = true
  try {
    const res = await listSkillsPaged({
      status: activeTab.value === 'ready' ? 'APPROVED' : 'DEPLOYED',
      risk_level: risk.value === 'all' ? undefined : risk.value,
      q: keyword.value.trim() || undefined,
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
      sort_by: sortState.value.field,
      sort_order: sortState.value.order === 'ascend' ? 'asc' : 'desc',
    })
    rows.value = Array.isArray(res.items) ? res.items : []
    total.value = Number(res.total || 0)
    pagination.value = {
      ...pagination.value,
      total: total.value,
      current: Number(res.page || pagination.value.current),
      pageSize: Number(res.page_size || pagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.3i4xon'))
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const currentUser = () => localStorage.getItem('username') || 'admin'

const handleDeploy = async (record) => {
  selectedRecord.value = record
  actionLoading.value = true
  deployMode.value = true
  try {
    await deploySkill(lifecycleVersionId(record))
    message.success(text(`已部署 ${record.name}`, `Deployed ${record.name}`))
    fetchRows()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.ohm64d'))
  } finally {
    actionLoading.value = false
    deployMode.value = false
  }
}

const openRetireModal = (record) => {
  selectedRecord.value = record
  retireReason.value = ''
  retireModalOpen.value = true
}

const submitRetire = async () => {
  if (!selectedRecord.value) return
  if (!retireReason.value.trim()) {
    message.warning(phrase('legacy.g1u22u'))
    return
  }
  actionLoading.value = true
  try {
    await retireSkill(lifecycleVersionId(selectedRecord.value), { actor: currentUser(), reason: retireReason.value.trim() })
    message.success(text(`已退役 ${selectedRecord.value.name}`, `Retired ${selectedRecord.value.name}`))
    retireModalOpen.value = false
    fetchRows()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.h714hg'))
  } finally {
    actionLoading.value = false
  }
}

const handleTableChange = (pager, _filters, sorter) => {
  pagination.value = {
    ...pagination.value,
    current: pager.current,
    pageSize: pager.pageSize,
  }
  if (sorter?.field) {
    sortState.value = {
      field: sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchRows()
}

const resetFilters = () => {
  risk.value = 'all'
  keyword.value = ''
  sortState.value = { field: 'submitted_at', order: 'descend' }
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchRows()
}

const statusColor = (value) =>
  ({
    APPROVED: 'green',
    DEPLOYED: 'blue',
  }[value] || 'default')

const statusTitle = (value) =>
  ({
    APPROVED: phrase('legacy.10hmnl2'),
    DEPLOYED: phrase('legacy.1t00jqn'),
  }[value] || phrase('legacy.1lpnuh4'))

const riskColor = (value) =>
  ({
    benign: 'green',
    suspicious: 'orange',
    malicious: 'red',
  }[value] || 'default')

onMounted(fetchRows)

watch(activeTab, () => {
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchRows()
})
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>

<template>
  <div>
    <a-page-header title="策略配置" sub-title="维护公司策略、允许工具和风险阈值" />

    <a-card style="margin-top: 16px">
      <a-alert
        type="info"
        show-icon
        :message="policyPath ? '当前策略文件' : '当前使用默认策略'"
        :description="policyPath || '尚未发现 policy.yaml，首次保存会写入 ~/.skill-manager/policy.yaml'"
        style="margin-bottom: 16px"
      />

      <a-form layout="vertical" :model="formState" @finish="handleSave">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="自动批准最大风险">
              <a-select v-model:value="formState.auto_approve_max_risk">
                <a-select-option value="LOW">LOW</a-select-option>
                <a-select-option value="MEDIUM">MEDIUM</a-select-option>
                <a-select-option value="HIGH">HIGH</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="扫描策略">
              <a-select v-model:value="formState.scanner_policy">
                <a-select-option value="strict">strict</a-select-option>
                <a-select-option value="balanced">balanced</a-select-option>
                <a-select-option value="permissive">permissive</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>

        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="需要人工审核">
              <a-select v-model:value="formState.require_human_review" mode="multiple" placeholder="选择需要人工审核的风险等级">
                <a-select-option value="LOW">LOW</a-select-option>
                <a-select-option value="MEDIUM">MEDIUM</a-select-option>
                <a-select-option value="HIGH">HIGH</a-select-option>
                <a-select-option value="EXTREME">EXTREME</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="自动拒绝风险">
              <a-select v-model:value="formState.auto_reject_risk" mode="multiple" placeholder="选择自动拒绝的风险等级">
                <a-select-option value="LOW">LOW</a-select-option>
                <a-select-option value="MEDIUM">MEDIUM</a-select-option>
                <a-select-option value="HIGH">HIGH</a-select-option>
                <a-select-option value="EXTREME">EXTREME</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>

        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="允许声明工具上限">
              <a-input-number v-model:value="formState.max_allowed_tools" :min="1" :max="100" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="必须声明 License">
              <a-switch v-model:checked="formState.require_license" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="禁止权限/工具">
          <a-select v-model:value="formState.blocked_permissions" mode="tags" placeholder="每项代表一个被禁止的 permission/tool" />
        </a-form-item>

        <a-form-item label="允许工具白名单">
          <a-select v-model:value="formState.allowed_tools_allowlist" mode="tags" placeholder="允许 skill 声明的工具列表" />
        </a-form-item>

        <a-form-item label="可信作者">
          <a-select v-model:value="formState.trusted_authors" mode="tags" placeholder="可信作者，可为空" />
        </a-form-item>

        <a-form-item label="允许 License">
          <a-select v-model:value="formState.accepted_licenses" mode="tags" placeholder="可接受 license 列表" />
        </a-form-item>

        <a-form-item>
          <a-space>
            <a-button type="primary" html-type="submit" :loading="saving">保存</a-button>
            <a-button @click="fetchPolicy" :loading="loading">重新加载</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </a-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import { getPolicy, updatePolicy } from '../api'

const loading = ref(false)
const saving = ref(false)
const policyPath = ref('')

const formState = reactive({
  auto_approve_max_risk: 'LOW',
  require_human_review: ['HIGH', 'EXTREME'],
  auto_reject_risk: ['EXTREME'],
  blocked_permissions: [],
  trusted_authors: [],
  allowed_tools_allowlist: [],
  max_allowed_tools: 20,
  require_license: false,
  accepted_licenses: [],
  scanner_policy: 'balanced',
})

const applyPolicy = (policy) => {
  formState.auto_approve_max_risk = policy.auto_approve_max_risk
  formState.require_human_review = [...(policy.require_human_review || [])]
  formState.auto_reject_risk = [...(policy.auto_reject_risk || [])]
  formState.blocked_permissions = [...(policy.blocked_permissions || [])]
  formState.trusted_authors = [...(policy.trusted_authors || [])]
  formState.allowed_tools_allowlist = [...(policy.allowed_tools_allowlist || [])]
  formState.max_allowed_tools = policy.max_allowed_tools
  formState.require_license = Boolean(policy.require_license)
  formState.accepted_licenses = [...(policy.accepted_licenses || [])]
  formState.scanner_policy = policy.scanner_policy
}

const fetchPolicy = async () => {
  loading.value = true
  try {
    const res = await getPolicy()
    policyPath.value = res.policy_path || ''
    applyPolicy(res.policy)
  } catch (error) {
    message.error(error.response?.data?.detail || '获取策略失败')
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const payload = {
      auto_approve_max_risk: formState.auto_approve_max_risk,
      require_human_review: formState.require_human_review,
      auto_reject_risk: formState.auto_reject_risk,
      blocked_permissions: formState.blocked_permissions,
      trusted_authors: formState.trusted_authors,
      allowed_tools_allowlist: formState.allowed_tools_allowlist,
      max_allowed_tools: Number(formState.max_allowed_tools || 0),
      require_license: formState.require_license,
      accepted_licenses: formState.accepted_licenses,
      scanner_policy: formState.scanner_policy,
    }
    const res = await updatePolicy(payload)
    policyPath.value = res.policy_path || ''
    applyPolicy(res.policy)
    message.success('策略已保存')
  } catch (error) {
    message.error(error.response?.data?.detail || '保存策略失败')
  } finally {
    saving.value = false
  }
}

onMounted(fetchPolicy)
</script>

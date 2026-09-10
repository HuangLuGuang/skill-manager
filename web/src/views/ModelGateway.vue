<template>
  <div>
    <a-page-header :title="pageTitle" :sub-title="pageSubtitle" />

    <a-row v-if="showGatewayStats" :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :md="8">
        <a-statistic :title="$t('legacy.7lz8o0')" :value="stats.total_requests ?? $t('legacy.rjjxll')" />
      </a-col>
      <a-col :xs="24" :md="8">
        <a-statistic :title="$t('legacy.gy11hx')" :value="stats.pii_checked_requests ?? $t('legacy.rjjxll')" />
      </a-col>
      <a-col :xs="24" :md="8">
        <a-statistic :title="$t('legacy.zv4967')" :value="stats.active_mappings ?? $t('legacy.rjjxll')" />
      </a-col>
      <a-col :xs="24" :md="8">
        <a-statistic :title="$t('legacy.1nlereu')" :value="stats.created_tokens ?? $t('legacy.rjjxll')" />
      </a-col>
      <a-col :xs="24" :md="8">
        <a-statistic :title="$t('legacy.14hkdpt')" :value="stats.reused_tokens ?? $t('legacy.rjjxll')" />
      </a-col>
      <a-col :xs="24" :md="8">
        <a-statistic :title="$t('legacy.akbipv')" :value="Object.keys(stats.pii_hits || {}).length" />
      </a-col>
    </a-row>

    <div style="margin-top: 16px">
      <section v-if="activeTab === 'providers'" class="provider-catalog">
        <div class="catalog-toolbar">
          <span class="catalog-summary">{{ $t('modelGateway.catalog.summary', { providers: providers.length, models: models.length }) }}</span>
          <a-space wrap>
            <a-button :loading="loading" @click="loadAll">{{ $t('modelGateway.catalog.refresh') }}</a-button>
            <a-button type="primary" @click="openProvider()">{{ $t('modelGateway.catalog.addProvider') }}</a-button>
          </a-space>
        </div>
        <a-spin :spinning="loading">
          <a-empty v-if="!providers.length" :description="$t('modelGateway.catalog.emptyProviders')" />
          <div class="provider-groups">
            <article v-for="provider in providerGroups" :key="provider.id" class="provider-group" :class="{ 'provider-group-default': provider.defaultModel }">
              <div class="provider-heading">
                <div class="provider-identity">
                  <span class="provider-avatar" aria-hidden="true">{{ provider.name.slice(0, 1).toUpperCase() }}</span>
                  <div class="provider-details">
                    <div class="provider-name-line">
                      <h2>{{ provider.name }}</h2>
                      <a-tooltip v-if="provider.defaultModel" :title="$t('modelGateway.catalog.defaultProviderHelp')">
                        <a-tag class="default-badge"><StarFilled aria-hidden="true" /> {{ $t('modelGateway.catalog.defaultProvider') }}</a-tag>
                      </a-tooltip>
                      <a-tag :color="provider.enabled ? 'green' : 'default'">{{ $t(provider.enabled ? 'modelGateway.catalog.enabled' : 'modelGateway.catalog.disabled') }}</a-tag>
                    </div>
                    <div class="provider-url">{{ provider.base_url }}</div>
                    <div class="provider-tags">
                      <a-tag>{{ provider.api_format === 'anthropic' ? 'Anthropic' : 'OpenAI-compatible' }}</a-tag>
                      <a-tag>LLM</a-tag>
                      <a-tag v-if="provider.enable_compression">{{ $t('modelGateway.catalog.compression') }}</a-tag>
                    </div>
                  </div>
                </div>
                <a-space class="provider-actions" :size="6">
                  <a-button class="configure-button" @click="openProvider(provider)">{{ $t('modelGateway.catalog.configure') }}</a-button>
                  <a-popconfirm :title="$t('modelGateway.catalog.deleteProviderConfirm')" @confirm="handleDeleteProvider(provider)">
                    <a-button class="delete-button" type="text" :title="$t('modelGateway.catalog.deleteProvider')" :aria-label="$t('modelGateway.catalog.deleteProvider')"><DeleteOutlined /></a-button>
                  </a-popconfirm>
                </a-space>
              </div>
              <div class="provider-model-toolbar">
                <div class="model-overview">
                <button class="model-expander" :aria-expanded="expandedProviders.has(provider.id)" :aria-controls="'provider-models-' + provider.id" @click="toggleProviderModels(provider.id)">
                  <DownOutlined v-if="expandedProviders.has(provider.id)" /><RightOutlined v-else />
                  {{ $t('modelGateway.catalog.modelCount', { count: provider.models.length }) }}
                </button>
                <span v-if="provider.defaultModel" class="default-model-summary"><StarFilled aria-hidden="true" /><span>{{ $t('modelGateway.catalog.defaultModelLabel', { model: provider.defaultModel.name }) }}</span></span>
                </div>
                <a-space class="model-management-actions" wrap :size="8">
                  <a-button class="fetch-models-button" :loading="discoveringProviderId === provider.id" :disabled="discoveringProviderId !== null" @click="fetchProviderModels(provider)"><ReloadOutlined aria-hidden="true" />{{ $t('modelGateway.catalog.fetch') }}</a-button>
                  <a-button class="add-model-button" type="primary" ghost @click="openModel(null, provider.id)"><PlusOutlined aria-hidden="true" />{{ $t('modelGateway.catalog.addModel') }}</a-button>
                </a-space>
              </div>
              <div v-show="expandedProviders.has(provider.id)" :id="'provider-models-' + provider.id" class="provider-models">
                <p v-if="!provider.models.length" class="provider-model-empty">{{ $t('modelGateway.catalog.emptyModels') }}</p>
                <div v-for="model in provider.models" :key="model.id" class="provider-model-row">
                  <div class="model-description">
                    <span class="model-symbol" aria-hidden="true"><ApiOutlined /></span>
                    <div class="model-labels">
                      <span class="model-name">{{ model.name }}</span>
                      <span v-if="model.display_name && model.display_name !== model.name" class="model-display-name">{{ model.display_name }}</span>
                      <a-tag>CHAT</a-tag>
                      <a-tooltip v-if="model.context_window" :title="$t('modelGateway.catalog.contextWindow', { count: model.context_window })"><a-tag>{{ formatContextWindow(model.context_window) }}</a-tag></a-tooltip>
                      <a-tag v-if="model.is_default" class="default-badge"><StarFilled aria-hidden="true" /> {{ $t('modelGateway.catalog.defaultModel') }}</a-tag>
                    </div>
                  </div>
                  <div class="model-actions">
                    <a-button class="test-model-button" size="small" :disabled="testingProvider" @click="openModelTest(model)"><PlayCircleOutlined aria-hidden="true" />{{ $t('modelGateway.providerTest.action') }}</a-button>
                    <a-button class="edit-model-button" type="text" size="small" @click="openModel(model)">{{ $t('modelGateway.catalog.edit') }}</a-button>
                    <a-popconfirm :title="$t('modelGateway.catalog.deleteModelConfirm')" @confirm="handleDeleteModel(model)">
                      <a-button class="delete-button" type="text" size="small" :title="$t('modelGateway.catalog.deleteModel')" :aria-label="$t('modelGateway.catalog.deleteModel')"><DeleteOutlined /></a-button>
                    </a-popconfirm>
                    <a-tooltip :title="$t(model.enabled ? 'modelGateway.catalog.enabled' : 'modelGateway.catalog.disabled')">
                      <a-switch :checked="model.enabled" :loading="updatingModelIds.has(model.id)" :disabled="updatingModelIds.has(model.id)" :aria-label="$t('modelGateway.catalog.toggleModel', { model: model.name })" @change="value => toggleModelEnabled(model, value)" />
                    </a-tooltip>
                  </div>
                </div>
              </div>
            </article>
          </div>
        </a-spin>
      </section>

      <section v-if="activeTab === 'keys'">
        <a-card>
          <template #extra>
            <a-button type="primary" @click="router.push('/credentials')">{{ $t("legacy.ntpgmd") }}</a-button>
          </template>
          <a-alert
            type="info"
            show-icon
            :message="$t('legacy.bsue3t')"
            :description="$t('legacy.1fyldk3')"
            style="margin-bottom: 16px"
          />
          <a-table :data-source="apiKeys" :columns="keyColumns" row-key="id" :loading="loading" size="small">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'compression'">
                <a-tag v-if="record.enable_compression" color="purple">{{ record.compression_level || 'auto' }}</a-tag>
                <span v-else class="muted">{{ $t("legacy.g0fanx") }}</span>
              </template>
              <template v-else-if="column.key === 'promptGuard'">
                <a-tag :color="promptGuardColor(record.prompt_guard_mode)">
                  {{ promptGuardLabel(record.prompt_guard_mode) }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'models'">
                <a-space wrap>
                  <a-tag v-for="name in record.allowed_models || []" :key="name">{{ name }}</a-tag>
                  <span v-if="!record.allowed_models?.length" class="muted">{{ $t("legacy.1b657i5") }}</span>
                </a-space>
              </template>
              <template v-else-if="column.key === 'expires_at'">
                {{ record.expires_at ? formatDateTime(record.expires_at) : $t('legacy.4rvo30') }}
              </template>
              <template v-else-if="column.key === 'action'">
                <a-space>
                  <a-button type="link" @click="openKey(record)">{{ $t("legacy.qreyeg") }}</a-button>
                  <a-popconfirm v-if="record.status === 'active'" :title="$t('legacy.10sjqb8')" @confirm="handleRevokeKey(record)">
                    <a-button type="link" danger>{{ $t("legacy.1xammsn") }}</a-button>
                  </a-popconfirm>
                  <a-popconfirm :title="$t('legacy.1m8mqmz')" @confirm="handleDeleteKey(record)">
                    <a-button type="link" danger>{{ $t("legacy.1t2vi4h") }}</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-card>
      </section>

      <section v-if="activeTab === 'users-groups'">
        <a-row :gutter="[16, 16]">
          <a-col :xs="24" :xl="12">
            <a-card :title="$t('legacy.1in002o')">
              <template #extra>
                <a-button type="primary" @click="openUser()">{{ $t("legacy.183giky") }}</a-button>
              </template>
              <a-table :data-source="users" :columns="userColumns" row-key="id" :loading="loading" size="small">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'active'">
                    <a-tag :color="record.is_active ? 'green' : 'default'">{{ record.is_active ? $t('legacy.5pm2ma') : $t('legacy.1dcdrxo') }}</a-tag>
                  </template>
                  <template v-else-if="column.key === 'groups'">
                    <a-space wrap>
                      <a-tag v-for="groupId in record.group_ids || []" :key="groupId">{{ groupNameMap.get(groupId) || groupId }}</a-tag>
                      <span v-if="!record.group_ids?.length" class="muted">{{ $t("legacy.adui4f") }}</span>
                    </a-space>
                  </template>
                  <template v-else-if="column.key === 'action'">
                    <a-button type="link" @click="openUser(record)">{{ $t("legacy.qreyeg") }}</a-button>
                  </template>
                </template>
              </a-table>
            </a-card>
          </a-col>
          <a-col :xs="24" :xl="12">
            <a-card :title="$t('legacy.19kaip8')">
              <template #extra>
                <a-button type="primary" @click="openGroup()">{{ $t("legacy.13naskl") }}</a-button>
              </template>
              <a-table :data-source="groups" :columns="groupColumns" row-key="id" :loading="loading" size="small">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'members'">
                    {{ record.user_ids?.length || 0 }} {{ $t("legacy.1h3mm7h") }} </template>
                  <template v-else-if="column.key === 'policy'">
                    <a-tag :color="record.privacy_policy_id ? 'blue' : 'default'">{{ groupPolicyName(record) }}</a-tag>
                  </template>
                  <template v-else-if="column.key === 'action'">
                    <a-button type="link" @click="openGroup(record)">{{ $t("legacy.qreyeg") }}</a-button>
                  </template>
                </template>
              </a-table>
            </a-card>
          </a-col>
        </a-row>
      </section>

      <section v-if="activeTab === 'policy-bindings'">
        <a-card :title="$t('legacy.1iapecz')">
          <template #extra>
            <a-space>
              <a-button @click="loadAll" :loading="loading">{{ $t("legacy.12qo56a") }}</a-button>
              <a-button type="primary" @click="openPolicy()">{{ $t("legacy.1j7mjes") }}</a-button>
            </a-space>
          </template>
          <a-alert
            type="info"
            show-icon
            :message="$t('legacy.tlc2fb')"
            style="margin-bottom: 16px"
          />
          <a-table :data-source="groups" :columns="groupPolicyColumns" row-key="id" :loading="loading" size="small">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'members'">
                {{ record.user_ids?.length || 0 }} {{ $t("legacy.1h3mm7h") }} </template>
              <template v-else-if="column.key === 'policy'">
                <a-tag :color="record.privacy_policy_id ? 'blue' : 'default'">{{ groupPolicyName(record) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'action'">
                <a-space>
                  <a-button type="link" @click="openGroupPolicy(record)">{{ $t("legacy.n4xb9n") }}</a-button>
                  <a-button type="link" @click="openPolicy()">{{ $t("legacy.1g3fhju") }}</a-button>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-card>
      </section>

      <section v-if="activeTab === 'policies'">
        <a-card>
          <template #extra>
            <a-button type="primary" @click="openPolicy()">{{ $t("legacy.15zxxn") }}</a-button>
          </template>
          <a-alert
            type="info"
            show-icon
            :message="$t('legacy.1lerf2o')"
            :description="$t('legacy.4d029z')"
            style="margin-bottom: 16px"
          />
          <a-table :data-source="policies" :columns="policyColumns" row-key="id" :loading="loading" size="small">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <a-space>
                  <span>{{ policyDisplayName(record) }}</span>
                  <a-tag v-if="record.is_default" color="blue">{{ $t("legacy.1jmrycz") }}</a-tag>
                  <a-tag v-else-if="record.group_id" color="purple">{{ $t("legacy.vj12xa") }}</a-tag>
                  <a-tag v-else>{{ $t("legacy.ofub6j") }}</a-tag>
                </a-space>
              </template>
              <template v-else-if="column.key === 'entity_types'">
                <a-space wrap>
                  <a-tag v-for="name in record.entity_types || []" :key="name">{{ entityLabel(name) }}</a-tag>
                </a-space>
              </template>
              <template v-else-if="column.key === 'flags'">
                <a-tag :color="record.enabled ? 'green' : 'default'">{{ text('隐私处理', 'Privacy') }}: {{ record.enabled ? text('开', 'On') : text('关', 'Off') }}</a-tag>
                <a-tag :color="record.detect_system_messages ? 'blue' : 'default'">system: {{ record.detect_system_messages ? text('检测', 'Inspect') : text('跳过', 'Skip') }}</a-tag>
                <a-tag :color="record.allow_bypass ? 'orange' : 'default'">bypass: {{ record.allow_bypass ? text('允许', 'Allowed') : text('禁止', 'Denied') }}</a-tag>
                <a-tag :color="record.dp_enabled ? 'green' : 'default'">DP: {{ record.dp_enabled ? text('开', 'On') : text('关', 'Off') }}</a-tag>
              </template>
              <template v-else-if="column.key === 'action'">
                <a-space>
                  <a-button type="link" @click="openPolicy(record)">{{ $t("legacy.qreyeg") }}</a-button>
                  <a-popconfirm v-if="!record.is_default" :title="$t('legacy.1g0wpcn')" @confirm="handleDeletePolicy(record)">
                    <a-button type="link" danger>{{ $t("legacy.1t2vi4h") }}</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-card>
      </section>

      <section v-if="activeTab === 'prompt-guard'">
        <a-card :title="$t('legacy.1yae1mb')">
          <a-alert
            type="info"
            show-icon
            :message="$t('legacy.1n68ot2')"
            :description="$t('legacy.nizzaf')"
            style="margin-bottom: 16px"
          />
          <a-row :gutter="[16, 16]">
            <a-col :xs="24" :lg="12">
              <a-form layout="vertical" :model="promptGuardForm">
                <a-form-item :label="$t('legacy.1uw63aw')">
                  <a-radio-group v-model:value="promptGuardForm.mode">
                    <a-radio value="log">{{ $t("legacy.4drpun") }}</a-radio>
                    <a-radio value="warn">{{ $t("legacy.gjwe4z") }}</a-radio>
                    <a-radio value="block">{{ $t("legacy.enaw4e") }}</a-radio>
                  </a-radio-group>
                </a-form-item>
                <a-form-item :label="$t('legacy.1s33gfn')">
                  <a-textarea
                    v-model:value="promptGuardForm.content"
                    :rows="10"
                    :placeholder="$t('legacy.1sib2cs')"
                  />
                </a-form-item>
                <a-space wrap>
                  <a-button type="primary" :loading="testingPromptGuard" @click="runPromptGuardTest">{{ $t("legacy.1rqbpwt") }}</a-button>
                  <a-button @click="fillPromptGuardSample">{{ $t("legacy.1ckue96") }}</a-button>
                  <a-button @click="clearPromptGuardTest">{{ $t("legacy.9mbwb2") }}</a-button>
                  <a-button @click="router.push('/credentials')">{{ $t("legacy.z26gt3") }}</a-button>
                </a-space>
              </a-form>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-card size="small" :title="$t('legacy.1czspmb')" class="prompt-guard-result">
                <a-empty v-if="!promptGuardResult" :description="$t('legacy.airzfg')" />
                <template v-else>
                  <a-descriptions size="small" bordered :column="1">
                    <a-descriptions-item :label="$t('legacy.hm077g')">
                      <a-tag :color="promptRiskColor(promptGuardResult.risk_level)">{{ promptRiskLabel(promptGuardResult.risk_level) }}</a-tag>
                    </a-descriptions-item>
                    <a-descriptions-item :label="$t('legacy.16syihm')">
                      <a-tag :color="promptActionColor(promptGuardResult.action)">{{ promptActionLabel(promptGuardResult.action) }}</a-tag>
                    </a-descriptions-item>
                    <a-descriptions-item :label="$t('legacy.l6iuzr')">{{ promptGuardResult.findings_count || 0 }}</a-descriptions-item>
                    <a-descriptions-item :label="$t('legacy.12sj4tc')">{{ promptGuardResult.duration_ms || 0 }} ms</a-descriptions-item>
                  </a-descriptions>
                  <a-list
                    style="margin-top: 16px"
                    :data-source="promptGuardResult.findings || []"
                    :locale="{ emptyText: $t('legacy.1utty0t') }"
                    bordered
                  >
                    <template #renderItem="{ item }">
                      <a-list-item>
                        <a-space direction="vertical" size="small" style="width: 100%">
                          <a-space wrap>
                            <a-tag :color="promptRiskColor(item.severity)">{{ promptRiskLabel(item.severity) }}</a-tag>
                            <a-typography-text strong>{{ promptRuleLabel(item.rule) }}</a-typography-text>
                            <a-tag>{{ item.role }}</a-tag>
                          </a-space>
                          <span class="muted">{{ item.reason }}</span>
                          <a-typography-paragraph code class="prompt-snippet">{{ item.snippet }}</a-typography-paragraph>
                        </a-space>
                      </a-list-item>
                    </template>
                  </a-list>
                </template>
              </a-card>
            </a-col>
          </a-row>
        </a-card>
      </section>

      <section v-if="activeTab === 'audit'">
        <a-card :title="$t('legacy.ehbs8g')">
          <template #extra>
            <a-space>
              <a-input-search
                v-model:value="mappingQuery.q"
                :placeholder="$t('legacy.h6ln60')"
                allow-clear
                style="width: 360px"
                :loading="mappingLoading"
                @search="searchMappings"
              />
              <a-button :loading="mappingLoading" @click="loadMappings">{{ $t("legacy.12qo56a") }}</a-button>
            </a-space>
          </template>
          <a-table
            :data-source="mappings"
            :columns="mappingColumns"
            row-key="id"
            :loading="mappingLoading"
            size="small"
            :pagination="mappingPagination"
            :scroll="{ x: 1480 }"
            @change="handleMappingTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'tenant_id'"><a-typography-text :ellipsis="{ tooltip: record.tenant_id }">{{ record.tenant_id }}</a-typography-text></template>
              <template v-else-if="column.key === 'conversation_id'">
                <a-tooltip :title="record.conversation_id">
                  <a-typography-text code>{{ compactId(record.conversation_id) }}</a-typography-text>
                </a-tooltip>
              </template>
              <template v-else-if="column.key === 'token'"><a-typography-text code :ellipsis="{ tooltip: record.token }">{{ record.token }}</a-typography-text></template>
              <template v-else-if="column.key === 'entity_type'">{{ entityLabel(record.entity_type) }}</template>
              <template v-else-if="column.key === 'original'"><a-typography-text :ellipsis="{ tooltip: record.original_value }">{{ record.original_value }}</a-typography-text></template>
              <template v-else-if="column.key === 'created_at'">{{ formatDateTime(record.created_at) }}</template>
              <template v-else-if="column.key === 'expires_at'">{{ formatDateTime(record.expires_at) }}</template>
              <template v-else-if="column.key === 'action'">
                <a-popconfirm :title="$t('legacy.inkm1m')" @confirm="removeMapping(record)">
                  <a-button type="link" danger>{{ $t("legacy.1t2vi4h") }}</a-button>
                </a-popconfirm>
              </template>
            </template>
          </a-table>
        </a-card>
      </section>
    </div>

    <a-modal v-model:open="discoveryVisible" :title="$t('modelGateway.catalog.discovered', { provider: discoveryProvider?.name })" :footer="null" :closable="!addingDiscovered" :mask-closable="!addingDiscovered" :keyboard="!addingDiscovered" width="800px">
      <a-alert type="info" show-icon :message="$t('modelGateway.catalog.discoveryHelp')" style="margin-bottom: 16px" />
      <a-alert v-if="discoveryError" type="warning" show-icon :message="discoveryError" style="margin-bottom: 16px" />
      <a-alert v-if="failedDiscoveredNames.length" type="warning" show-icon :message="$t('modelGateway.catalog.batchFailed', { names: failedDiscoveredNames.join(', ') })" style="margin-bottom: 16px" />
      <a-space wrap style="margin-bottom: 16px">
        <a-button :loading="discoveringProviderId !== null" :disabled="discoveringProviderId !== null || addingDiscovered" @click="fetchProviderModels(discoveryProvider)">{{ $t('modelGateway.catalog.fetch') }}</a-button>
        <a-button :disabled="addingDiscovered" @click="openDiscoveredModel()">{{ $t('modelGateway.catalog.custom') }}</a-button>
        <a-button type="primary" :loading="addingDiscovered" :disabled="addingDiscovered || submitting || !selectedDiscoveredNames.length" @click="addSelectedModels">{{ $t('modelGateway.catalog.addSelected', { count: selectedDiscoveredNames.length }) }}</a-button>
      </a-space>
      <a-table :data-source="discoveredModels" :columns="discoveryColumns" :row-selection="discoveryRowSelection" row-key="name" :loading="discoveringProviderId !== null" :scroll="{ x: 550 }" size="small">
        <template #bodyCell="{ column, record }">
          <a-space v-if="column.key === 'action'" wrap>
            <a-button type="link" :disabled="addingDiscovered || models.some(item => item.name === record.name)" @click="openDiscoveredModel(record)">{{ $t(models.some(item => item.name === record.name) ? 'modelGateway.catalog.registered' : 'modelGateway.catalog.add') }}</a-button>
            <a-button type="link" @click="openModelTest({ ...record, provider_id: discoveryProvider.id })">{{ $t('modelGateway.providerTest.action') }}</a-button>
          </a-space>
        </template>
      </a-table>
    </a-modal>

    <a-modal v-model:open="providerVisible" :title="$t('legacy.1vcp6w4')" @ok="saveProvider" :confirm-loading="submitting" :ok-button-props="{ disabled: submitting }">
      <a-form layout="vertical" :model="providerForm">
        <a-form-item :label="$t('legacy.hzx914')" required><a-input v-model:value="providerForm.name" /></a-form-item>
        <a-form-item label="Base URL" required :extra="$t('modelGateway.provider.baseUrlHelp')">
          <a-input v-model:value="providerForm.base_url" :placeholder="$t('modelGateway.provider.baseUrlPlaceholder')" />
        </a-form-item>
        <a-form-item :label="$t('legacy.849biy')" required>
          <a-select v-model:value="providerForm.api_format">
            <a-select-option value="openai">OpenAI-compatible</a-select-option>
            <a-select-option value="anthropic">Anthropic-compatible</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="API Key"><a-input-password v-model:value="providerForm.api_key" :placeholder="$t('legacy.x2xaci')" /></a-form-item>
        <a-form-item><a-checkbox v-model:checked="providerForm.clear_api_key">{{ $t("legacy.1h2ipsy") }}</a-checkbox></a-form-item>
        <a-form-item :label="$t('legacy.tabbi8')"><a-input-number v-model:value="providerForm.timeout_seconds" :min="1" :max="600" style="width: 100%" /></a-form-item>
        <a-form-item>
          <a-checkbox v-model:checked="providerForm.enable_compression">{{ $t("legacy.10di3wx") }}</a-checkbox>
          <div style="color: #888; font-size: 12px; margin-top: 4px">{{ $t("legacy.1y0xlm4") }}</div>
        </a-form-item>
        <a-form-item><a-checkbox v-model:checked="providerForm.enabled">{{ $t("legacy.5pm2ma") }}</a-checkbox></a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="providerTestVisible"
      :title="$t('modelGateway.providerTest.title')"
      :ok-text="$t('modelGateway.providerTest.submit')"
      :confirm-loading="testingProvider"
      :ok-button-props="{ disabled: testingProvider }"
      @ok="runProviderTest"
    >
      <a-descriptions size="small" bordered :column="1" style="margin-bottom: 16px">
        <a-descriptions-item :label="$t('modelGateway.providerTest.provider')">
          {{ providerUnderTest?.name }}
        </a-descriptions-item>
        <a-descriptions-item label="Base URL">
          {{ providerUnderTest?.base_url }}
        </a-descriptions-item>
      </a-descriptions>
      <a-alert
        type="warning"
        show-icon
        :message="$t('modelGateway.providerTest.realRequestWarning')"
        style="margin-bottom: 16px"
      />
      <a-form layout="vertical" :model="providerTestForm">
        <a-form-item :label="$t('modelGateway.providerTest.model')" required>
          <a-auto-complete
            v-model:value="providerTestForm.model"
            :options="providerTestModelOptions"
            :placeholder="$t('modelGateway.providerTest.modelPlaceholder')"
            allow-clear
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="modelVisible" :title="$t('legacy.1ow6qt')" @ok="saveModel" :confirm-loading="submitting" :ok-button-props="{ disabled: submitting }">
      <a-form layout="vertical" :model="modelForm">
        <a-form-item :label="$t('legacy.1x7qpl0')" required>
          <a-select v-model:value="modelForm.provider_id">
            <a-select-option v-for="item in providers" :key="item.id" :value="item.id">{{ item.name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('legacy.1hmiuig')" required><a-input v-model:value="modelForm.name" /></a-form-item>
        <a-form-item :label="$t('legacy.1m2bn1g')"><a-input v-model:value="modelForm.display_name" /></a-form-item>
        <a-form-item :label="$t('legacy.wbvjnl')"><a-input-number v-model:value="modelForm.context_window" style="width: 100%" /></a-form-item>
        <a-form-item :label="$t('legacy.rvvikw')"><a-input-number v-model:value="modelForm.max_output_tokens" style="width: 100%" /></a-form-item>
        <a-space>
          <a-checkbox v-model:checked="modelForm.enabled">{{ $t("legacy.5pm2ma") }}</a-checkbox>
          <a-checkbox v-model:checked="modelForm.is_default">{{ $t("legacy.9tnz09") }}</a-checkbox>
        </a-space>
      </a-form>
    </a-modal>

    <a-modal v-model:open="keyVisible" :title="editingKeyId ? $t('legacy.rvmojw') : $t('legacy.1dlpoh0')" @ok="saveKey" :confirm-loading="submitting" width="720px">
      <a-form layout="vertical" :model="keyForm">
        <a-form-item :label="$t('legacy.hzx914')" required><a-input v-model:value="keyForm.name" /></a-form-item>
        <a-alert type="info" show-icon :message="$t('legacy.1rret3q')" style="margin-bottom: 16px" />
        <a-form-item :label="$t('legacy.1o3mles')">
          <a-select v-model:value="keyForm.allowed_models" mode="multiple" :placeholder="$t('legacy.1hrenha')">
            <a-select-option v-for="item in models" :key="item.name" :value="item.name">{{ item.name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item :label="$t('legacy.1wuxzav')"><a-input-number v-model:value="keyForm.max_body_kb" :min="1" :max="10240" style="width: 100%" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="$t('legacy.1bdr3ch')"><a-input-number v-model:value="keyForm.max_concurrent_requests" :min="1" :max="100" style="width: 100%" /></a-form-item></a-col>
        </a-row>
        <a-divider style="font-size: 13px; color: #888">{{ $t("legacy.17h4ugg") }}</a-divider>
        <a-form-item>
          <a-checkbox v-model:checked="keyForm.enable_compression">{{ $t("legacy.8gpyto") }}</a-checkbox>
          <div style="color: #888; font-size: 12px; margin-top: 4px">{{ $t("legacy.1lvxy18") }}</div>
        </a-form-item>
        <a-form-item v-if="keyForm.enable_compression" :label="$t('legacy.1xs6jxf')">
          <a-radio-group v-model:value="keyForm.compression_level">
            <a-radio value="auto">{{ $t("legacy.8wl6r3") }}</a-radio>
            <a-radio value="conservative">{{ $t("legacy.wrbkd") }}</a-radio>
            <a-radio value="aggressive">{{ $t("legacy.ksjya4") }}</a-radio>
          </a-radio-group>
        </a-form-item>
        <a-divider style="font-size: 13px; color: #888">{{ $t("legacy.5h548n") }}</a-divider>
        <a-form-item :label="$t('legacy.1uw63aw')">
          <a-radio-group v-model:value="keyForm.prompt_guard_mode">
            <a-radio value="off">{{ $t("legacy.g0fanx") }}</a-radio>
            <a-radio value="log">{{ $t("legacy.4drpun") }}</a-radio>
            <a-radio value="warn">{{ $t("legacy.gjwe4z") }}</a-radio>
            <a-radio value="block">{{ $t("legacy.enaw4e") }}</a-radio>
          </a-radio-group>
          <div style="color: #888; font-size: 12px; margin-top: 4px">{{ $t("legacy.4p9xot") }}</div>
        </a-form-item>
        <a-form-item v-if="keyForm.prompt_guard_mode !== 'off'" :label="$t('legacy.otccp4')">
          <div style="color: #888; font-size: 12px; margin-top: 4px">{{ $t("legacy.16x9kox") }}</div>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item :label="$t('legacy.1oc35yx')">
              <a-date-picker
                v-model:value="keyForm.expires_at"
                show-time
                format="YYYY-MM-DD HH:mm:ss"
                value-format="YYYY-MM-DDTHH:mm:ss"
                :disabled="keyForm.never_expires"
                :placeholder="$t('legacy.5yas67')"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12"><a-form-item :label="$t('legacy.h75f9d')"><a-checkbox v-model:checked="keyForm.never_expires">{{ $t("legacy.4rvo30") }}</a-checkbox></a-form-item></a-col>
        </a-row>
        <a-row :gutter="16" v-if="editingKeyId">
          <a-col :span="12" v-if="editingKeyId"><a-form-item :label="$t('legacy.1ccx4t4')"><a-select v-model:value="keyForm.status"><a-select-option value="active">{{ $t("legacy.5pm2ma") }}</a-select-option><a-select-option value="disabled">{{ $t("legacy.1dcdrxo") }}</a-select-option><a-select-option value="revoked">{{ $t("legacy.1ouf8s7") }}</a-select-option></a-select></a-form-item></a-col>
        </a-row>
      </a-form>
    </a-modal>

    <a-modal v-model:open="createdKeyVisible" :title="$t('legacy.qlsmer')" :footer="null" width="760px">
      <a-alert type="warning" show-icon :message="$t('legacy.15s0714')" style="margin-bottom: 16px" />
        <a-input-group compact>
          <a-input :value="createdKey" readonly style="width: calc(100% - 96px)" />
        <a-button type="primary" @click="copy(createdKey)" :disabled="!createdKey">{{ $t("legacy.1xbipwq") }}</a-button>
        </a-input-group>
    </a-modal>

    <a-modal v-model:open="userVisible" :title="$t('legacy.1in002o')" @ok="saveUser" :confirm-loading="submitting">
      <a-form layout="vertical" :model="userForm">
        <a-form-item :label="$t('legacy.u9jq8n')" required><a-input v-model:value="userForm.username" :disabled="!!editingUserId" /></a-form-item>
        <a-form-item :label="$t('legacy.185tvls')" required><a-input v-model:value="userForm.email" /></a-form-item>
        <a-form-item :label="$t('legacy.1x858ed')"><a-select v-model:value="userForm.role"><a-select-option value="admin">admin</a-select-option><a-select-option value="super_admin">super_admin</a-select-option><a-select-option value="privacy_auditor">privacy_auditor</a-select-option><a-select-option value="security_auditor">security_auditor</a-select-option></a-select></a-form-item>
        <a-form-item :label="$t('legacy.2qkjxx')">
          <a-select v-model:value="userForm.group_ids" mode="multiple" :placeholder="$t('legacy.f5lws8')">
            <a-select-option v-for="item in groups" :key="item.id" :value="item.id">{{ item.name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('legacy.1aph6eg')"><a-input-password v-model:value="userForm.password" :placeholder="editingUserId ? $t('legacy.x2xaci') : ''" /></a-form-item>
        <a-form-item><a-checkbox v-model:checked="userForm.is_active">{{ $t("legacy.5pm2ma") }}</a-checkbox></a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="groupVisible" :title="$t('legacy.19kaip8')" @ok="saveGroup" :confirm-loading="submitting">
      <a-form layout="vertical" :model="groupForm">
        <a-form-item :label="$t('legacy.hzx914')" required><a-input v-model:value="groupForm.name" /></a-form-item>
        <a-form-item :label="$t('legacy.1kxyax6')"><a-textarea v-model:value="groupForm.description" /></a-form-item>
        <a-form-item :label="$t('legacy.ceyxit')">
          <a-select v-model:value="groupForm.user_ids" mode="multiple">
            <a-select-option v-for="item in users" :key="item.id" :value="item.id">{{ item.username }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('legacy.jt33j7')">
          <a-select v-model:value="groupForm.privacy_policy_id" allow-clear :placeholder="$t('legacy.lvqpcd')">
            <a-select-option v-for="item in unboundOrCurrentPolicies" :key="item.id" :value="item.id">{{ policyDisplayName(item) }}</a-select-option>
          </a-select>
          <div class="muted policy-binding-hint">{{ $t("legacy.1xj70s1") }}</div>
        </a-form-item>
        <a-form-item><a-checkbox v-model:checked="groupForm.is_active">{{ $t("legacy.5pm2ma") }}</a-checkbox></a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="groupPolicyVisible" :title="$t('legacy.1ofxouc')" @ok="saveGroupPolicy" :confirm-loading="submitting">
      <a-form layout="vertical">
        <a-form-item :label="$t('legacy.19kaip8')">
          <a-input :value="selectedGroup?.name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.jt33j7')">
          <a-select v-model:value="groupPolicyForm.privacy_policy_id" allow-clear :placeholder="$t('legacy.lvqpcd')">
            <a-select-option v-for="item in unboundOrCurrentBindingPolicies" :key="item.id" :value="item.id">{{ policyDisplayName(item) }}</a-select-option>
          </a-select>
          <div class="muted policy-binding-hint">{{ $t("legacy.1xj70s1") }}</div>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="policyVisible" :title="$t('legacy.jt33j7')" @ok="savePolicy" :confirm-loading="submitting" width="860px">
      <a-form layout="vertical" :model="policyForm">
        <a-form-item :label="$t('legacy.12aoush')"><a-input v-model:value="policyForm.name" /></a-form-item>
        <a-form-item :label="$t('legacy.13cneuc')">
          <a-switch v-model:checked="policyForm.enabled" :checked-children="$t('legacy.z2u55c')" :un-checked-children="$t('legacy.g0fanx')" />
          <span class="muted" style="margin-left: 12px">{{ $t("legacy.12yxjw7") }}</span>
        </a-form-item>
        <a-form-item>
          <template #label>
            <a-tooltip :title="$t('legacy.12zgrwo')">
              <span>{{ $t("legacy.19kaip8") }}</span>
            </a-tooltip>
          </template>
          <a-select v-model:value="policyForm.group_id" allow-clear :disabled="policyForm.is_default" :placeholder="$t('legacy.1794y90')">
            <a-select-option v-for="item in groups" :key="item.id" :value="item.id">{{ item.name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <template #label>
            <a-tooltip :title="$t('legacy.yqs1lm')">
              <span>{{ $t("legacy.rzxot4") }}</span>
            </a-tooltip>
          </template>
          <a-select v-model:value="policyForm.entity_types" mode="tags" @change="syncPolicyRuleRows">
            <a-select-option v-for="item in defaultEntities" :key="item" :value="item">{{ entityLabel(item) }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <template #label>
            <a-tooltip :title="$t('legacy.18qjpjt')">
              <span>{{ $t("legacy.1qq6oyl") }}</span>
            </a-tooltip>
          </template>
          <div class="rule-list">
            <a-row v-for="row in policyRuleRows" :key="row.key" :gutter="12" class="rule-row">
              <a-col :span="7">
                <a-input :value="entityLabel(row.key)" readonly />
              </a-col>
              <a-col :span="17">
                <a-input v-model:value="row.pattern" :placeholder="$t('legacy.1v07tq7')" />
              </a-col>
            </a-row>
            <a-empty v-if="!policyRuleRows.length" :description="$t('legacy.1o1fr4n')" />
          </div>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item>
              <template #label>
                <a-tooltip :title="$t('legacy.1suq9gf')">
                  <span>{{ $t("legacy.f2d0q2") }}</span>
                </a-tooltip>
              </template>
              <a-input-number v-model:value="policyForm.mapping_ttl_days" :min="1" :max="365" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item>
              <template #label>
                <a-tooltip :title="$t('legacy.1t1h2go')">
                  <span>DP epsilon</span>
                </a-tooltip>
              </template>
              <a-input-number v-model:value="policyForm.dp_epsilon" :min="0.1" :step="0.1" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item>
              <template #label>
                <a-tooltip :title="$t('legacy.s7q0q1')">
                  <span>{{ $t("legacy.4iza5t") }}</span>
                </a-tooltip>
              </template>
              <a-input-number v-model:value="policyForm.dp_min_count" :min="1" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-space>
          <a-tooltip :title="$t('legacy.kvxa6o')">
            <a-checkbox v-model:checked="policyForm.detect_system_messages">{{ $t("legacy.1kwl8fa") }}</a-checkbox>
          </a-tooltip>
          <a-tooltip :title="$t('legacy.9sja0p')">
            <a-checkbox v-model:checked="policyForm.allow_bypass">{{ $t("legacy.umul6c") }}</a-checkbox>
          </a-tooltip>
          <a-tooltip :title="$t('legacy.3bn42k')">
            <a-checkbox v-model:checked="policyForm.dp_enabled">{{ $t("legacy.1q9p7ed") }}</a-checkbox>
          </a-tooltip>
        </a-space>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { ApiOutlined, DeleteOutlined, DownOutlined, PlayCircleOutlined, PlusOutlined, ReloadOutlined, RightOutlined, StarFilled } from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { useLocaleText } from '../i18n/useLocaleText'
import { copyText, promptManualCopy } from '../utils/clipboard'
import { formatBeijingDateTime } from '../utils/format'

import {
  createGroup,
  createLlmApiKey,
  createManagedUser,
  createModelEndpoint,
  createModelProvider,
  deleteLlmApiKey,
  deleteModelEndpoint,
  deleteModelProvider,
  deletePrivacyPolicy,
  deletePrivacyMapping,
  getPrivacyStats,
  listPrivacyMappings,
  listGroups,
  listLlmApiKeys,
  listManagedUsers,
  listModelEndpoints,
  listModelProviders,
  discoverModelProviderModels,
  listPrivacyPolicies,
  revokeLlmApiKey,
  savePrivacyPolicy,
  testPromptGuard,
  testModelProvider,
  updateGroup,
  updateLlmApiKey,
  updateManagedUser,
  updateModelEndpoint,
  updateModelProvider,
} from '../api'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { isEnglish, text } = useLocaleText()
const activeTab = ref(route.meta.gatewayTab || 'providers')
const loading = ref(false)
const submitting = ref(false)
const mappingLoading = ref(false)
const providers = ref([])
const expandedProviders = reactive(new Set())
const updatingModelIds = reactive(new Set())
const discoveryVisible = ref(false)
const discoveryProvider = ref(null)
const discoveredModels = ref([])
const discoveringProviderId = ref(null)
const discoveryError = ref('')
const addingDiscovered = ref(false)
const selectedDiscoveredNames = ref([])
const failedDiscoveredNames = ref([])
const discoveryRowSelection = computed(() => ({
  selectedRowKeys: selectedDiscoveredNames.value,
  onChange: keys => { selectedDiscoveredNames.value = keys },
  getCheckboxProps: record => ({ disabled: addingDiscovered.value || models.value.some(item => item.name === record.name) }),
}))
const discoveryColumns = computed(() => [
  { title: t('modelGateway.catalog.modelName'), dataIndex: 'name' },
  { title: t('modelGateway.catalog.actions'), key: 'action', width: 240 },
])
const models = ref([])
const providerGroups = computed(() => providers.value.map(provider => ({
  ...provider,
  defaultModel: models.value.find(model => model.provider_id === provider.id && model.is_default),
  models: models.value.filter(model => model.provider_id === provider.id),
})))
const toggleProviderModels = (id) => {
  if (expandedProviders.has(id)) expandedProviders.delete(id)
  else expandedProviders.add(id)
}
const formatContextWindow = (count) => count >= 1000 ? `${Number((count / 1000).toFixed(1))}K` : String(count)
const toggleModelEnabled = async (model, enabled) => {
  if (updatingModelIds.has(model.id)) return
  updatingModelIds.add(model.id)
  try {
    const updated = await updateModelEndpoint(model.id, { enabled })
    models.value = models.value.map(item => item.id === model.id ? updated : item)
  } catch {
    message.error(t('modelGateway.catalog.updateFailed'))
  } finally {
    updatingModelIds.delete(model.id)
  }
}
const apiKeys = ref([])
const users = ref([])
const groups = ref([])
const policies = ref([])
const stats = ref({})
const mappings = ref([])
const mappingTotal = ref(0)
const defaultEntities = ['PERSON', 'CN_ID_CARD', 'CN_MOBILE', 'CN_LANDLINE', 'CN_BANK_CARD', 'EMAIL_ADDRESS', 'IP_ADDRESS', 'CN_LICENSE_PLATE', 'CN_USCC', 'CN_ADDRESS', 'EMPLOYEE_ID', 'CUSTOMER_ID', 'ACCOUNT_ID']
const entityLabels = {
  PERSON: phrase('legacy.7upuyd'),
  CN_PERSON: phrase('legacy.7upuyd'),
  CN_ID_CARD: phrase('legacy.1dd20k4'),
  CN_MOBILE: phrase('legacy.irjcno'),
  CN_LANDLINE: phrase('legacy.1gjtfqr'),
  CN_BANK_CARD: phrase('legacy.1nzxonr'),
  EMAIL_ADDRESS: phrase('legacy.6o7cg1'),
  IP_ADDRESS: phrase('legacy.p7it7o'),
  CN_LICENSE_PLATE: phrase('legacy.xxe53a'),
  CN_USCC: phrase('legacy.blhm03'),
  CN_ADDRESS: phrase('legacy.rj1wnb'),
  EMPLOYEE_ID: phrase('legacy.aueuat'),
  CUSTOMER_ID: phrase('legacy.67sadx'),
  ACCOUNT_ID: phrase('legacy.yuxvje'),
}
const entityLabelsEn = {
  PERSON: 'Chinese Name',
  CN_PERSON: 'Chinese Name',
  CN_ID_CARD: 'Chinese Resident ID',
  CN_MOBILE: 'Mainland China Mobile Number',
  CN_LANDLINE: 'Chinese Landline Number',
  CN_BANK_CARD: 'Bank Card Number',
  EMAIL_ADDRESS: 'Email Address',
  IP_ADDRESS: 'IP Address',
  CN_LICENSE_PLATE: 'Chinese License Plate',
  CN_USCC: 'Unified Social Credit Code',
  CN_ADDRESS: 'Chinese Address',
  EMPLOYEE_ID: 'Employee ID',
  CUSTOMER_ID: 'Customer ID',
  ACCOUNT_ID: 'Account ID',
}
const entityLabel = (name) => {
  const label = isEnglish.value ? entityLabelsEn[name] : entityLabels[name]
  return label ? `${label} (${name})` : name
}
const defaultRules = {
  PERSON: '',
  CN_ID_CARD: '(?<!\\d)[1-9]\\d{5}(?:18|19|20)\\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\\d|3[01])\\d{3}[\\dXx](?!\\d)',
  CN_MOBILE: '(?<!\\d)(?:\\+?86[- ]?)?1[3-9]\\d{9}(?!\\d)',
  CN_LANDLINE: '',
  CN_BANK_CARD: '(?<!\\d)(?:\\d[ -]?){15,18}\\d(?!\\d)',
  EMAIL_ADDRESS: '\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b',
  IP_ADDRESS: '(?<![\\w.])(?:\\d{1,3}\\.){3}\\d{1,3}(?![\\w.])|(?<![\\w:])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\\w:])',
  CN_LICENSE_PLATE: '(?<![A-Z0-9\\u4e00-\\u9fff])[\\u4eac\\u6d25\\u6caa\\u6e1d\\u5180\\u8c6b\\u4e91\\u8fbd\\u9ed1\\u6e58\\u7696\\u9c81\\u65b0\\u82cf\\u6d59\\u8d63\\u9102\\u6842\\u7518\\u664b\\u8499\\u9655\\u5409\\u95fd\\u8d35\\u7ca4\\u9752\\u85cf\\u5ddd\\u5b81\\u743c][A-HJ-NP-Z](?:[DF][A-HJ-NP-Z0-9]\\d{4}|\\d{5}[DF]|[A-HJ-NP-Z0-9]{5})(?![A-Z0-9])',
  CN_USCC: '(?<![0-9A-Z])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-Z])',
  CN_ADDRESS: '',
  EMPLOYEE_ID: '\\b(?:EMP|Employee|\\u5458\\u5de5)[-_:# ]?[A-Za-z0-9]{4,}\\b',
  CUSTOMER_ID: '\\b(?:CUST|Customer|\\u5ba2\\u6237)[-_:# ]?[A-Za-z0-9]{4,}\\b',
  ACCOUNT_ID: '\\b(?:ACCT|Account|\\u8d26\\u53f7)[-_:# ]?[A-Za-z0-9]{4,}\\b',
}

const keyColumns = [
  { title: phrase('legacy.hzx914'), dataIndex: 'name' },
  { title: phrase('legacy.z7wyiw'), dataIndex: 'key_prefix', width: 110 },
  { title: phrase('legacy.1ow6qt'), key: 'models' },
  { title: phrase('legacy.1x027h5'), key: 'compression', width: 80 },
  { title: phrase('legacy.5h548n'), key: 'promptGuard', width: 120 },
  { title: phrase('legacy.1oc35yx'), key: 'expires_at', width: 170 },
  { title: phrase('legacy.1ccx4t4'), key: 'status', width: 120 },
  { title: phrase('legacy.501w24'), key: 'action', width: 100 },
]
const mappingColumns = [
  { title: 'Tenant ID', key: 'tenant_id', width: 180 },
  { title: 'Conversation ID', key: 'conversation_id', width: 240 },
  { title: 'Token', key: 'token', width: 220 },
  { title: phrase('legacy.anh4cj'), dataIndex: 'entity_type', key: 'entity_type', width: 220 },
  { title: phrase('legacy.r1iigp'), key: 'original', width: 180 },
  { title: phrase('legacy.1m1p1i9'), key: 'created_at', width: 170 },
  { title: phrase('legacy.1oc35yx'), key: 'expires_at', width: 170 },
  { title: phrase('legacy.501w24'), key: 'action', width: 90, fixed: 'right' },
]
const userColumns = [
  { title: phrase('legacy.u9jq8n'), dataIndex: 'username' },
  { title: phrase('legacy.185tvls'), dataIndex: 'email' },
  { title: phrase('legacy.1x858ed'), dataIndex: 'role', width: 130 },
  { title: phrase('legacy.2qkjxx'), key: 'groups', width: 180 },
  { title: phrase('legacy.1ccx4t4'), key: 'active', width: 90 },
  { title: phrase('legacy.501w24'), key: 'action', width: 90 },
]
const groupColumns = [
  { title: phrase('legacy.hzx914'), dataIndex: 'name' },
  { title: phrase('legacy.ceyxit'), key: 'members', width: 90 },
  { title: phrase('legacy.jt33j7'), key: 'policy', width: 150 },
  { title: phrase('legacy.1kxyax6'), dataIndex: 'description' },
  { title: phrase('legacy.501w24'), key: 'action', width: 130 },
]
const groupPolicyColumns = [
  { title: phrase('legacy.19kaip8'), dataIndex: 'name' },
  { title: phrase('legacy.ceyxit'), key: 'members', width: 100 },
  { title: phrase('legacy.51c0aj'), key: 'policy', width: 180 },
  { title: phrase('legacy.1mi4vdj'), dataIndex: 'description' },
  { title: phrase('legacy.501w24'), key: 'action', width: 180 },
]
const policyColumns = computed(() => [
  { title: text('名称', 'Name'), dataIndex: 'name', key: 'name', width: 260 },
  { title: 'Group ID', dataIndex: 'group_id', width: 100 },
  { title: text('实体类型', 'Entity Types'), key: 'entity_types' },
  { title: text('开关', 'Enabled'), key: 'flags', width: 280 },
  { title: text('操作', 'Actions'), key: 'action', width: 90 },
])

const providerVisible = ref(false)
const providerTestVisible = ref(false)
const testingProvider = ref(false)
const providerUnderTest = ref(null)
const modelVisible = ref(false)
const keyVisible = ref(false)
const createdKeyVisible = ref(false)
const userVisible = ref(false)
const groupVisible = ref(false)
const groupPolicyVisible = ref(false)
const policyVisible = ref(false)
const createdKey = ref('')
const editingProviderId = ref(null)
const editingModelId = ref(null)
const editingKeyId = ref(null)
const editingUserId = ref(null)
const editingGroupId = ref(null)
const selectedGroup = ref(null)
const policyRuleRows = ref([])

const providerForm = reactive({ name: '', base_url: '', api_format: 'openai', api_key: '', clear_api_key: false, enabled: true, timeout_seconds: 60, enable_compression: false })
const providerTestForm = reactive({ model: '' })
const providerTestModelOptions = computed(() => models.value
  .filter(item => item.provider_id === providerUnderTest.value?.id && item.enabled)
  .map(item => ({ value: item.name })))
const modelForm = reactive({ provider_id: null, name: '', display_name: '', enabled: true, context_window: null, max_output_tokens: null, is_default: false })
const keyForm = reactive({
  name: '',
  allowed_models: [],
  max_body_kb: 1024,
  max_concurrent_requests: 5,
  expires_at: null,
  never_expires: true,
  status: 'active',
  enable_compression: false,
  compression_level: 'auto',
  prompt_guard_mode: 'off',
  prompt_guard_llm_review: false,
})
const userForm = reactive({ username: '', email: '', role: 'admin', password: '', is_active: true, group_ids: [] })
const groupForm = reactive({ name: '', description: '', user_ids: [], privacy_policy_id: null, is_active: true })
const groupPolicyForm = reactive({ privacy_policy_id: null })
const policyForm = reactive({ id: null, name: phrase('legacy.1t3snxj'), is_default: false, enabled: true, group_id: null, entity_types: [...defaultEntities], entity_rules: { ...defaultRules }, detect_system_messages: false, allow_bypass: false, mapping_ttl_days: 7, dp_enabled: true, dp_epsilon: 1.0, dp_min_count: 5 })
const mappingQuery = reactive({ q: '', page: 1, page_size: 10 })
const promptGuardForm = reactive({
  mode: 'block',
  content: '',
})
const promptGuardResult = ref(null)
const testingPromptGuard = ref(false)
const mappingPagination = computed(() => ({
  current: mappingQuery.page,
  pageSize: mappingQuery.page_size,
  total: mappingTotal.value,
  showSizeChanger: true,
  showTotal: total => text(`共 ${total} 条`, `${total} total`),
}))

const unboundOrCurrentPolicies = computed(() =>
  policies.value.filter(item => !item.is_default && (!item.group_id || item.id === groupForm.privacy_policy_id)),
)
const unboundOrCurrentBindingPolicies = computed(() =>
  policies.value.filter(item => !item.is_default && (!item.group_id || item.id === groupPolicyForm.privacy_policy_id)),
)
const pageTitle = computed(() => activeTab.value === 'providers' ? t('modelGateway.catalog.title') : activeTab.value === 'users-groups' ? phrase('legacy.1wqfb8q') : phrase('legacy.15en1a5'))
const pageSubtitle = computed(() =>
  activeTab.value === 'providers'
    ? t('modelGateway.catalog.subtitle')
    : activeTab.value === 'users-groups'
    ? phrase('legacy.btrjcn')
    : phrase('legacy.1tdfp6x'),
)
const showGatewayStats = computed(() => !['providers', 'users-groups', 'prompt-guard'].includes(activeTab.value))
const groupNameMap = computed(() => new Map(groups.value.map(item => [item.id, item.name])))
const policyDisplayName = (policy) => {
  if (policy?.is_default && policy?.name === '默认隐私策略') return text('默认隐私策略', 'Default Privacy Policy')
  if (policy?.name !== '默认隐私策略') return policy?.name || '-'
  return `${groupNameMap.value.get(policy.group_id) || text('用户组', 'Group')} ${text('隐私策略', 'Privacy Policy')}`
}
const groupPolicyName = (group) => {
  if (!group?.privacy_policy_id) return text('系统默认策略', 'System Default Policy')
  return policyDisplayName(policies.value.find(item => item.id === group.privacy_policy_id) || {
    name: group.privacy_policy_name,
    group_id: group.id,
  })
}

const formatDateTime = (value) => value ? formatBeijingDateTime(value) : ''
const statusLabel = (s) => ({ active: phrase('legacy.5pm2ma'), disabled: phrase('legacy.1dcdrxo'), revoked: phrase('legacy.1ouf8s7') }[s] || s)
const statusColor = (s) => ({ active: 'green', disabled: 'orange', revoked: 'red' }[s] || 'default')
const promptGuardLabel = (value) => ({ off: phrase('legacy.g0fanx'), log: phrase('legacy.4drpun'), warn: phrase('legacy.gjwe4z'), block: phrase('legacy.enaw4e') }[value] || phrase('legacy.g0fanx'))
const promptGuardColor = (value) => ({ off: 'default', log: 'blue', warn: 'orange', block: 'red' }[value] || 'default')
const promptRiskLabel = (value) => ({ none: phrase('legacy.41lnsu'), LOW: phrase('legacy.qy3yng'), MEDIUM: phrase('legacy.pakbe9'), HIGH: phrase('legacy.197bn2e') }[value] || value || '-')
const promptRiskColor = (value) => ({ none: 'green', LOW: 'blue', MEDIUM: 'orange', HIGH: 'red' }[value] || 'default')
const promptActionLabel = (value) => ({ off: phrase('legacy.1tylsuy'), record: phrase('legacy.4drpun'), warn: phrase('legacy.gjwe4z'), block: phrase('legacy.1fsazit'), pass: phrase('legacy.iivj4n') }[value] || value || '-')
const promptActionColor = (value) => ({ off: 'default', record: 'blue', warn: 'orange', block: 'red', pass: 'green' }[value] || 'default')
const promptRuleLabel = (value) => ({
  prompt_injection: phrase('legacy.v4iti5'),
  system_prompt_leak: phrase('legacy.1y1bb3m'),
  secret_exfiltration: phrase('legacy.1dcgbzo'),
  tool_abuse: phrase('legacy.y5ph62'),
  encoded_instruction: phrase('legacy.1cwubjq'),
  safety_bypass: phrase('legacy.171ciix'),
  role_override: phrase('legacy.1g7b5m'),
  tool_output_instruction: phrase('legacy.rq72tw'),
}[value] || value)
const compactId = (value, head = 10, tail = 8) => {
  if (!value || value.length <= head + tail + 3) return value || ''
  return `${value.slice(0, head)}...${value.slice(-tail)}`
}

const syncPolicyRuleRows = () => {
  const existing = new Map(policyRuleRows.value.map(item => [item.key, item.pattern]))
  policyRuleRows.value = (policyForm.entity_types || []).map(key => ({
    key,
    pattern: existing.has(key) ? existing.get(key) : (policyForm.entity_rules?.[key] ?? defaultRules[key] ?? ''),
  }))
}

const runPromptGuardTest = async () => {
  const content = promptGuardForm.content.trim()
  if (!content) {
    message.warning(phrase('legacy.1rxbcfo'))
    return
  }
  testingPromptGuard.value = true
  try {
    promptGuardResult.value = await testPromptGuard({
      mode: promptGuardForm.mode,
      messages: [{ role: 'user', content }],
    })
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.tz7iqk'))
  } finally {
    testingPromptGuard.value = false
  }
}

const fillPromptGuardSample = () => {
  promptGuardForm.content = phrase('legacy.e12uf')
  promptGuardForm.mode = 'block'
  promptGuardResult.value = null
}

const clearPromptGuardTest = () => {
  promptGuardForm.content = ''
  promptGuardResult.value = null
}

watch(
  () => route.meta.gatewayTab,
  (tab) => {
    activeTab.value = tab || 'providers'
  },
  { immediate: true },
)

const loadAll = async () => {
  loading.value = true
  try {
    const [providerRes, modelRes, keyRes, userRes, groupRes, policyRes, statRes, mappingRes] = await Promise.all([
      listModelProviders(),
      listModelEndpoints(),
      listLlmApiKeys(),
      listManagedUsers(),
      listGroups(),
      listPrivacyPolicies(),
      getPrivacyStats(),
      listPrivacyMappings({ page: mappingQuery.page, page_size: mappingQuery.page_size, q: mappingQuery.q || undefined }),
    ])
    providers.value = providerRes
    models.value = modelRes
    apiKeys.value = keyRes
    users.value = userRes
    groups.value = groupRes
    policies.value = policyRes
    stats.value = statRes
    mappings.value = mappingRes.mappings || []
    mappingTotal.value = mappingRes.total || 0
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1fqwvn2'))
  } finally {
    loading.value = false
  }
}

const openProvider = (record = null) => {
  editingProviderId.value = record?.id || null
  Object.assign(providerForm, {
    name: record?.name || '',
    base_url: record?.base_url || '',
    api_format: record?.api_format || 'openai',
    api_key: '',
    clear_api_key: false,
    enabled: record?.enabled ?? true,
    timeout_seconds: record?.timeout_seconds || 60,
    enable_compression: record?.enable_compression ?? false,
  })
  providerVisible.value = true
}

const saveProvider = async () => {
  if (submitting.value) return
  submitting.value = true
  try {
    const payload = { ...providerForm }
    if (!payload.api_key) delete payload.api_key
    const isNew = !editingProviderId.value
    const saved = isNew ? await createModelProvider(payload) : await updateModelProvider(editingProviderId.value, payload)
    providerVisible.value = false
    await loadAll()
    if (isNew) await fetchProviderModels(saved)
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.8ujjnl'))
  } finally {
    submitting.value = false
  }
}

const fetchProviderModels = async (provider) => {
  if (discoveringProviderId.value !== null || addingDiscovered.value || !provider) return
  discoveringProviderId.value = provider.id
  discoveryProvider.value = provider
  discoveredModels.value = []
  selectedDiscoveredNames.value = []
  failedDiscoveredNames.value = []
  discoveryError.value = ''
  discoveryVisible.value = true
  try {
    const result = await discoverModelProviderModels(provider.id)
    discoveredModels.value = result.models
  } catch (error) {
    const code = error.response?.data?.error_code
    const key = {
      'model_discovery.connection_failed': 'connectionFailed',
      'model_discovery.upstream_http_error': 'upstreamFailed',
      'model_discovery.invalid_response': 'invalidResponse',
    }[code] || 'fetchFailed'
    discoveryError.value = t(`modelGateway.catalog.${key}`)
  } finally {
    discoveringProviderId.value = null
  }
}

const addSelectedModels = async () => {
  if (addingDiscovered.value || submitting.value || !discoveryProvider.value) return
  const providerId = discoveryProvider.value.id
  const selected = discoveredModels.value.filter(item => selectedDiscoveredNames.value.includes(item.name)
    && !models.value.some(model => model.name === item.name))
  if (!selected.length) return
  addingDiscovered.value = true
  failedDiscoveredNames.value = []
  let added = 0
  try {
    for (const item of selected) {
      try {
        const model = await createModelEndpoint({ provider_id: providerId, name: item.name, display_name: item.display_name })
        models.value.push(model)
        added += 1
      } catch {
        failedDiscoveredNames.value.push(item.name)
      }
    }
    selectedDiscoveredNames.value = [...failedDiscoveredNames.value]
    if (added) message.success(t('modelGateway.catalog.batchAdded', { count: added }))
  } finally {
    addingDiscovered.value = false
  }
}

const openDiscoveredModel = (record = null) => {
  openModel(null, discoveryProvider.value.id)
  modelForm.name = record?.name || ''
  modelForm.display_name = record?.display_name || ''
}

const openModelTest = (record) => {
  const provider = providers.value.find(item => item.id === record.provider_id)
  if (!provider || testingProvider.value) return
  openProviderTest(provider)
  providerTestForm.model = record.name
}

const openProviderTest = (record) => {
  if (testingProvider.value) return
  providerUnderTest.value = record
  providerTestForm.model = models.value.find(item => item.provider_id === record.id && item.enabled)?.name || ''
  providerTestVisible.value = true
}

const providerTestFailureMessage = (result) => {
  const key = {
    'model_provider_test.connection_failed': 'modelGateway.providerTest.errors.connectionFailed',
    'model_provider_test.upstream_http_error': 'modelGateway.providerTest.errors.upstreamHttp',
    'model_provider_test.invalid_response': 'modelGateway.providerTest.errors.invalidResponse',
  }[result.error_code] || 'modelGateway.providerTest.errors.unknown'
  const summary = t(key, { status: result.status_code ?? '-' })
  return result.error ? `${summary}: ${result.error}` : summary
}

const runProviderTest = async () => {
  if (testingProvider.value || !providerUnderTest.value) return
  const model = providerTestForm.model.trim()
  if (!model) {
    message.warning(t('modelGateway.providerTest.modelRequired'))
    return
  }
  testingProvider.value = true
  try {
    const result = await testModelProvider(providerUnderTest.value.id, { model })
    if (result.ok) {
      message.success(t('modelGateway.providerTest.success', {
        model: result.model,
        status: result.status_code,
        duration: result.duration_ms,
      }))
      providerTestVisible.value = false
      return
    }
    message.warning(providerTestFailureMessage(result))
  } catch (error) {
    message.error(error.response?.data?.detail || t('modelGateway.providerTest.errors.requestFailed'))
  } finally {
    testingProvider.value = false
  }
}

const handleDeleteProvider = async (record) => {
  await deleteModelProvider(record.id)
  await loadAll()
}

const openModel = (record = null, providerId = null) => {
  editingModelId.value = record?.id || null
  Object.assign(modelForm, {
    provider_id: record?.provider_id || providerId || providers.value[0]?.id || null,
    name: record?.name || '',
    display_name: record?.display_name || '',
    enabled: record?.enabled ?? true,
    context_window: record?.context_window || null,
    max_output_tokens: record?.max_output_tokens || null,
    is_default: record?.is_default || false,
  })
  modelVisible.value = true
}

const saveModel = async () => {
  if (submitting.value) return
  submitting.value = true
  try {
    if (editingModelId.value) await updateModelEndpoint(editingModelId.value, { ...modelForm })
    else await createModelEndpoint({ ...modelForm })
    selectedDiscoveredNames.value = selectedDiscoveredNames.value.filter(name => name !== modelForm.name)
    modelVisible.value = false
    await loadAll()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.13g8wbu'))
  } finally {
    submitting.value = false
  }
}

const handleDeleteModel = async (record) => {
  await deleteModelEndpoint(record.id)
  await loadAll()
}

const openKey = (record = null) => {
  editingKeyId.value = record?.id || null
  Object.assign(keyForm, {
    name: record?.name || '',
    allowed_models: record?.allowed_models || [],
    max_body_kb: record?.max_body_kb || 1024,
    max_concurrent_requests: record?.max_concurrent_requests || 5,
    expires_at: record?.expires_at ? dayjs(record.expires_at).format('YYYY-MM-DDTHH:mm:ss') : null,
    never_expires: !record?.expires_at,
    status: record?.status || 'active',
    enable_compression: record?.enable_compression ?? false,
    compression_level: record?.compression_level || 'auto',
    prompt_guard_mode: record?.prompt_guard_mode || 'off',
    prompt_guard_llm_review: record?.prompt_guard_llm_review ?? false,
  })
  keyVisible.value = true
}

const saveKey = async () => {
  if (submitting.value) return
  submitting.value = true
  try {
    const payload = {
      ...keyForm,
      expires_at: keyForm.never_expires ? null : (keyForm.expires_at || null),
      prompt_guard_llm_review: false,
    }
    delete payload.never_expires
    let res = null
    if (editingKeyId.value) await updateLlmApiKey(editingKeyId.value, payload)
    else res = await createLlmApiKey(payload)
    createdKey.value = res?.token || ''
    keyVisible.value = false
    if (createdKey.value) createdKeyVisible.value = true
    await loadAll()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.18n1e47'))
  } finally {
    submitting.value = false
  }
}

const handleRevokeKey = async (record) => {
  await revokeLlmApiKey(record.id)
  await loadAll()
}

const handleDeleteKey = async (record) => {
  await deleteLlmApiKey(record.id)
  await loadAll()
}

const openUser = (record = null) => {
  editingUserId.value = record?.id || null
  Object.assign(userForm, {
    username: record?.username || '',
    email: record?.email || '',
    role: record?.role || 'admin',
    password: '',
    is_active: record?.is_active ?? true,
    group_ids: [...(record?.group_ids || [])],
  })
  userVisible.value = true
}

const saveUser = async () => {
  if (submitting.value) return
  if (!userForm.username.trim()) {
    message.warning(phrase('legacy.pwpq3a'))
    return
  }
  if (!userForm.email.trim()) {
    message.warning(phrase('legacy.u69mlf'))
    return
  }
  if (!editingUserId.value && !userForm.password) {
    message.warning(phrase('legacy.f478sb'))
    return
  }
  submitting.value = true
  try {
    const payload = { ...userForm }
    if (!payload.password) delete payload.password
    if (editingUserId.value) await updateManagedUser(editingUserId.value, payload)
    else await createManagedUser(payload)
    userVisible.value = false
    await loadAll()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1a1txb7'))
  } finally {
    submitting.value = false
  }
}

const openGroup = (record = null) => {
  editingGroupId.value = record?.id || null
  Object.assign(groupForm, {
    name: record?.name || '',
    description: record?.description || '',
    user_ids: record?.user_ids || [],
    privacy_policy_id: record?.privacy_policy_id || null,
    is_active: record?.is_active ?? true,
  })
  groupVisible.value = true
}

const saveGroup = async () => {
  if (submitting.value) return
  submitting.value = true
  try {
    if (editingGroupId.value) await updateGroup(editingGroupId.value, { ...groupForm })
    else await createGroup({ ...groupForm })
    groupVisible.value = false
    await loadAll()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.zixdkh'))
  } finally {
    submitting.value = false
  }
}

const openGroupPolicy = (record) => {
  selectedGroup.value = record
  Object.assign(groupPolicyForm, {
    privacy_policy_id: record?.privacy_policy_id || null,
  })
  groupPolicyVisible.value = true
}

const saveGroupPolicy = async () => {
  if (submitting.value || !selectedGroup.value) return
  submitting.value = true
  try {
    await updateGroup(selectedGroup.value.id, { privacy_policy_id: groupPolicyForm.privacy_policy_id })
    groupPolicyVisible.value = false
    await loadAll()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.m3e5xa'))
  } finally {
    submitting.value = false
  }
}

const openPolicy = (record = null) => {
  const next = record ? { ...record } : { id: null, name: '', is_default: false, enabled: true, group_id: null, entity_types: [...defaultEntities], entity_rules: { ...defaultRules }, detect_system_messages: false, allow_bypass: false, mapping_ttl_days: 7, dp_enabled: true, dp_epsilon: 1.0, dp_min_count: 5 }
  Object.assign(policyForm, next)
  syncPolicyRuleRows()
  policyVisible.value = true
}

const savePolicy = async () => {
  if (submitting.value) return
  submitting.value = true
  try {
    const entityRules = Object.fromEntries(policyRuleRows.value.map(row => [row.key, row.pattern || '']))
    await savePrivacyPolicy({ ...policyForm, entity_rules: entityRules })
    policyVisible.value = false
    await loadAll()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.89mw1k'))
  } finally {
    submitting.value = false
  }
}

const handleDeletePolicy = async (record) => {
  try {
    await deletePrivacyPolicy(record.id)
    message.success(phrase('legacy.1age6o7'))
    await loadAll()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.ptdvkd'))
  }
}

const loadMappings = async () => {
  mappingLoading.value = true
  try {
    const res = await listPrivacyMappings({
      page: mappingQuery.page,
      page_size: mappingQuery.page_size,
      q: mappingQuery.q || undefined,
    })
    mappings.value = res.mappings || []
    mappingTotal.value = res.total || 0
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.f94fgk'))
  } finally {
    mappingLoading.value = false
  }
}

const searchMappings = async () => {
  mappingQuery.page = 1
  await loadMappings()
}

const handleMappingTableChange = async (pagination) => {
  mappingQuery.page = pagination.current || 1
  mappingQuery.page_size = pagination.pageSize || 10
  await loadMappings()
}

const removeMapping = async (record) => {
  mappingLoading.value = true
  try {
    await deletePrivacyMapping(record.id)
    if (mappings.value.length === 1 && mappingQuery.page > 1) {
      mappingQuery.page -= 1
    }
    await loadMappings()
    await loadAll()
    message.success(phrase('legacy.1qwsnvh'))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.ln41rf'))
  } finally {
    mappingLoading.value = false
  }
}

watch(
  () => activeTab.value,
  (tab) => {
    if (tab === 'audit') loadMappings()
  },
)

const copy = async (text) => {
  try {
    await copyText(text)
    message.success(phrase('legacy.alyyje'))
  } catch {
    message.warning(t('clipboard.copyFailed'))
    promptManualCopy(text, t('clipboard.manualCopyPrompt'))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.provider-catalog {
  --catalog-border: #e5e7eb;
  --catalog-muted: #64748b;
  --catalog-ink: #1e293b;
  --catalog-blue: #2563eb;
  color: var(--catalog-ink);
}
.catalog-toolbar, .provider-heading, .provider-model-toolbar, .provider-model-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.catalog-toolbar { margin-bottom: 18px; flex-wrap: wrap; }
.catalog-summary { color: var(--catalog-muted); font-size: 13px; }
.provider-groups { display: grid; gap: 16px; }
.provider-group { border: 1px solid var(--catalog-border); border-radius: 14px; overflow: hidden; background: #f8fafc; }
.provider-group-default { border-color: #b9cdf9; }
.provider-group :deep(.default-badge) { display: inline-flex; align-items: center; gap: 4px; color: #2457be; background: #edf3ff; border-color: #cddcff; font-weight: 500; }
.provider-group :deep(.default-badge .anticon) { font-size: 10px; }
.provider-heading { padding: 22px 24px 18px; align-items: flex-start; }
.provider-identity { display: flex; gap: 14px; min-width: 0; }
.provider-avatar { display: grid; place-items: center; flex-shrink: 0; width: 40px; height: 40px; border-radius: 11px; background: #e8efff; color: var(--catalog-blue); font-size: 21px; font-weight: 650; }
.provider-details { min-width: 0; }
.provider-name-line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.provider-name-line h2 { font-size: 17px; font-weight: 650; margin: 0; overflow-wrap: anywhere; }
.provider-url { margin: 5px 0 10px; font-size: 12px; color: var(--catalog-muted); overflow-wrap: anywhere; }
.provider-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.provider-group :deep(.ant-tag) { margin: 0; font-size: 11px; border-radius: 5px; line-height: 20px; }
.provider-actions { flex-shrink: 0; margin-left: auto; }
.provider-catalog :deep(.ant-btn) { border-radius: 7px; box-shadow: none; font-size: 13px; }
.provider-actions :deep(.ant-btn), .model-management-actions :deep(.ant-btn) { height: 32px; }
.provider-actions :deep(.configure-button) { padding-inline: 15px; border-color: #dce2eb; color: #475569; background: #fff; }
.provider-catalog :deep(.delete-button) { width: 30px; padding: 0; color: #94a3b8; }
.provider-catalog :deep(.delete-button:hover) { color: #dc2626; background: #fff1f0; }
.provider-actions :deep(.delete-button) { margin-left: 4px; }
.model-management-actions :deep(.fetch-models-button) { color: #475569; border-color: #dce2eb; background: #fff; }
.model-management-actions :deep(.add-model-button) { background: #edf3ff; border-color: #cddcff; color: #2457be; }
.model-management-actions :deep(.add-model-button:hover) { background: #e1ebff; border-color: #8eadef; }
.provider-model-toolbar { padding: 10px 24px; border-top: 1px solid var(--catalog-border); flex-wrap: wrap; }
.model-overview { display: flex; align-items: center; flex-wrap: wrap; gap: 10px 16px; min-width: 0; flex: 1; }
.default-model-summary { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: #5270a8; font-size: 12px; }
.default-model-summary > span:last-child { overflow-wrap: anywhere; }
.default-model-summary :deep(.anticon) { font-size: 10px; flex-shrink: 0; }
.model-expander { display: inline-flex; align-items: center; gap: 8px; border: 0; padding: 6px 0; background: transparent; color: var(--catalog-muted); font: inherit; font-size: 13px; cursor: pointer; }
.model-expander:focus-visible { outline: 2px solid var(--catalog-blue); outline-offset: 4px; border-radius: 3px; }
.provider-models { margin: 0 12px 12px; border-radius: 9px; background: #fff; }
.provider-model-empty { padding: 18px 12px; margin: 0; font-size: 13px; color: var(--catalog-muted); }
.provider-model-row { padding: 14px 12px; }
.provider-model-row + .provider-model-row { border-top: 1px solid #f1f5f9; }
.model-description { display: flex; align-items: center; gap: 12px; min-width: 0; }
.model-symbol { color: var(--catalog-blue); font-size: 18px; }
.model-labels { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; min-width: 0; }
.model-name { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; overflow-wrap: anywhere; }
.model-display-name { color: var(--catalog-muted); font-size: 12px; overflow-wrap: anywhere; }
.model-actions { display: flex; align-items: center; flex-shrink: 0; gap: 8px; }
.model-actions :deep(.ant-btn) { height: 28px; }
.model-actions :deep(.test-model-button) { color: #2457be; border-color: #dce6f8; background: #f8faff; padding-inline: 10px; }
.model-actions :deep(.edit-model-button) { color: #64748b; padding-inline: 6px; }
.model-actions :deep(.ant-switch) { margin-left: 10px; }
@media (max-width: 768px) {
  .provider-heading { padding: 16px; flex-wrap: wrap; }
  .provider-model-toolbar { padding: 10px 16px; gap: 8px; }
  .model-overview { flex-basis: 100%; }
  .model-management-actions { margin-left: auto; }
  .provider-model-row { flex-wrap: wrap; gap: 10px; }
  .model-actions { margin-left: auto; }
}

.muted {
  color: #8c8c8c;
}

.policy-binding-hint {
  margin-top: 6px;
  line-height: 1.5;
}

.rule-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 280px;
  overflow: auto;
  padding-right: 4px;
}

.rule-row {
  align-items: center;
}
</style>

<template>
  <section class="scan-page">
    <header class="ops-header">
      <div>
        <div class="eyebrow">{{ t('agentSecurityScans.eyebrow') }}</div>
        <h1>{{ t('agentSecurityScans.title') }}</h1>
        <p>{{ t('agentSecurityScans.subtitle') }}</p>
      </div>
      <a-space wrap>
        <a-button :loading="refreshing" @click="refreshAll">
          <template #icon><ReloadOutlined /></template>
          {{ t('agentSecurityScans.refresh') }}
        </a-button>
        <a-button type="primary" :disabled="!canStartScan" @click="openTaskModal">
          <template #icon><PlayCircleOutlined /></template>
          {{ t('agentSecurityScans.newTask') }}
        </a-button>
      </a-space>
    </header>

    <nav class="scan-pipeline" :aria-label="t('agentSecurityScans.pipelineLabel')">
      <button
        v-for="(stage, index) in stageItems"
        :key="stage.key"
        type="button"
        class="pipeline-stage"
        :class="{ active: activeStage === stage.key }"
        @click="activeStage = stage.key"
      >
        <span class="stage-index">{{ String(index + 1).padStart(2, '0') }}</span>
        <span class="stage-copy">
          <strong>{{ stage.label }}</strong>
          <small>{{ stage.description }}</small>
        </span>
        <span class="stage-count">{{ stage.count }}</span>
      </button>
    </nav>

    <a-alert
      v-if="loadError"
      class="page-alert"
      type="error"
      show-icon
      :message="t('agentSecurityScans.loadFailed')"
      :description="loadError"
    />

    <a-spin :spinning="loading">
      <div class="stage-panel">
        <template v-if="activeStage === 'targets'">
          <div class="panel-heading">
            <div>
              <h2>{{ t('agentSecurityScans.targets.title') }}</h2>
              <p>{{ t('agentSecurityScans.targets.description') }}</p>
            </div>
            <a-space wrap>
              <a-input-search
                v-model:value="targetSearch"
                allow-clear
                class="search-control"
                :placeholder="t('agentSecurityScans.targets.search')"
              />
              <a-button v-if="canAdmin" type="primary" @click="openTargetModal()">
                <template #icon><PlusOutlined /></template>
                {{ t('agentSecurityScans.targets.create') }}
              </a-button>
            </a-space>
          </div>

          <a-table
            :columns="targetColumns"
            :data-source="filteredTargets"
            :pagination="tablePagination"
            row-key="target_id"
            table-layout="fixed"
            :scroll="{ x: 1080 }"
            :locale="{ emptyText: t('agentSecurityScans.targets.empty') }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <div class="primary-cell" :title="`${record.name}\n${record.target_id}`">
                  <strong>{{ record.name }}</strong>
                  <code>{{ record.target_id }}</code>
                </div>
              </template>
              <template v-else-if="column.key === 'target_type'">
                <div class="target-classification">
                  <a-tag color="blue">{{ assetTypeLabel(record.asset_type) }}</a-tag>
                  <span>{{ connectorTypeLabel(record.connector_type) }}</span>
                </div>
              </template>
              <template v-else-if="column.key === 'environment'">
                <a-tag :color="environmentColor(record.environment)">{{ environmentLabel(record.environment) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'allowed_capabilities'">
                <span class="muted">{{ t('agentSecurityScans.capabilityCount', { value: record.allowed_capabilities?.length || 0 }) }}</span>
              </template>
              <template v-else-if="column.key === 'production_controls'">
                <div v-if="record.environment === 'production' && record.execution_mode === 'active_safe'" class="budget-stack">
                  <span>{{ t('agentSecurityScans.policies.productionTargetCount', { value: record.production_target_ids?.length || 0 }) }}</span>
                  <span>{{ formatUtcDateTime(record.maintenance_window_start) }} – {{ formatUtcDateTime(record.maintenance_window_end) }}</span>
                  <span>{{ record.dedicated_identity_ref || '—' }}</span>
                </div>
                <span v-else class="muted">{{ t('agentSecurityScans.policies.notApplicable') }}</span>
              </template>
              <template v-else-if="column.key === 'endpoint_url'">
                <a-typography-text class="endpoint-text" :ellipsis="{ tooltip: record.endpoint_url }">
                  {{ record.endpoint_url }}
                </a-typography-text>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-badge :status="record.status === 'active' ? 'success' : 'default'" :text="statusLabel(record.status)" />
              </template>
              <template v-else-if="column.key === 'credential'">
                <a-tag
                  class="credential-tag"
                  :color="record.credential_configured ? 'green' : 'default'"
                  :title="targetCredentialLabel(record)"
                >
                  <span class="credential-tag__text">{{ targetCredentialLabel(record) }}</span>
                </a-tag>
              </template>
              <template v-else-if="column.key === 'updated_at'">
                {{ formatDateTime(record.updated_at) }}
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space v-if="canAdmin" wrap>
                  <a-button type="link" size="small" @click="openTargetModal(record)">{{ t('agentSecurityScans.edit') }}</a-button>
                  <a-button
                    v-if="record.target_type !== 'mcp_gateway'"
                    type="link"
                    size="small"
                    @click="openCredentialModal(record)"
                  >{{ t('agentSecurityScans.targets.credential') }}</a-button>
                  <a-popconfirm
                    :title="record.status === 'active' ? t('agentSecurityScans.targets.disableConfirm') : t('agentSecurityScans.targets.enableConfirm')"
                    @confirm="toggleTarget(record)"
                  >
                    <a-button type="link" size="small" :danger="record.status === 'active'">
                      {{ record.status === 'active' ? t('agentSecurityScans.disable') : t('agentSecurityScans.enable') }}
                    </a-button>
                  </a-popconfirm>
                </a-space>
                <span v-else class="muted">{{ t('agentSecurityScans.readOnly') }}</span>
              </template>
            </template>
          </a-table>
        </template>

        <template v-else-if="activeStage === 'policies'">
          <div class="panel-heading">
            <div>
              <h2>{{ t('agentSecurityScans.policies.title') }}</h2>
              <p>{{ t('agentSecurityScans.policies.description') }}</p>
            </div>
            <a-button v-if="canAdmin" type="primary" @click="openPolicyModal()">
              <template #icon><PlusOutlined /></template>
              {{ t('agentSecurityScans.policies.create') }}
            </a-button>
          </div>

          <a-table
            :columns="policyColumns"
            :data-source="policies"
            :pagination="tablePagination"
            row-key="policy_id"
            table-layout="fixed"
            :scroll="{ x: 1180 }"
            :locale="{ emptyText: t('agentSecurityScans.policies.empty') }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <div class="primary-cell" :title="`${record.name}\n${record.policy_id}`"><strong>{{ record.name }}</strong><code>{{ record.policy_id }}</code></div>
              </template>
              <template v-else-if="column.key === 'execution_mode'">
                <a-tag :color="executionModeColor(record.execution_mode)">{{ executionModeLabel(record.execution_mode) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'environment'">
                <a-tag :color="environmentColor(record.environment)">{{ environmentLabel(record.environment) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'allowed_capabilities'">
                <span class="muted">{{ t('agentSecurityScans.capabilityCount', { value: record.allowed_capabilities?.length || 0 }) }}</span>
              </template>
              <template v-else-if="column.key === 'budget'">
                <div class="budget-stack">
                  <span>{{ t('agentSecurityScans.policies.rounds', { value: record.max_rounds }) }}</span>
                  <span>{{ t('agentSecurityScans.policies.tokens', { value: formatNumber(record.max_tokens) }) }}</span>
                  <span>{{ t('agentSecurityScans.policies.duration', { value: formatDuration(record.max_duration_seconds) }) }}</span>
                </div>
              </template>
              <template v-else-if="column.key === 'network'">
                <span v-if="record.outbound_allowlist?.length">{{ record.outbound_allowlist.join(', ') }}</span>
                <span v-else class="muted">{{ t('agentSecurityScans.policies.publicOnly') }}</span>
              </template>
              <template v-else-if="column.key === 'enabled'">
                <a-badge :status="record.enabled ? 'success' : 'default'" :text="record.enabled ? t('agentSecurityScans.enabled') : t('agentSecurityScans.disabled')" />
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space v-if="canAdmin">
                  <a-button type="link" size="small" @click="openPolicyModal(record)">{{ t('agentSecurityScans.edit') }}</a-button>
                  <a-popconfirm :title="record.enabled ? t('agentSecurityScans.policies.disableConfirm') : t('agentSecurityScans.policies.enableConfirm')" @confirm="togglePolicy(record)">
                    <a-button type="link" size="small" :danger="record.enabled">
                      {{ record.enabled ? t('agentSecurityScans.disable') : t('agentSecurityScans.enable') }}
                    </a-button>
                  </a-popconfirm>
                </a-space>
                <span v-else class="muted">{{ t('agentSecurityScans.readOnly') }}</span>
              </template>
            </template>
          </a-table>
        </template>

        <template v-else-if="activeStage === 'tasks'">
          <div class="panel-heading">
            <div>
              <h2>{{ t('agentSecurityScans.tasks.title') }}</h2>
              <p>{{ t('agentSecurityScans.tasks.description') }}</p>
            </div>
            <a-button type="primary" :disabled="!canStartScan" @click="openTaskModal">
              <template #icon><PlayCircleOutlined /></template>
              {{ t('agentSecurityScans.tasks.create') }}
            </a-button>
          </div>
          <div class="filter-row">
            <a-select v-model:value="taskStatusFilter" class="filter-control" :placeholder="t('agentSecurityScans.tasks.status')">
              <a-select-option value="all">{{ t('agentSecurityScans.allStatuses') }}</a-select-option>
              <a-select-option v-for="value in taskStatuses" :key="value" :value="value">{{ statusLabel(value) }}</a-select-option>
            </a-select>
            <a-select v-model:value="taskTargetFilter" allow-clear class="filter-control" :placeholder="t('agentSecurityScans.tasks.target')">
              <a-select-option v-for="target in targets" :key="target.target_id" :value="target.target_id">{{ target.name }}</a-select-option>
            </a-select>
            <a-select v-model:value="taskKindFilter" allow-clear class="filter-control" :placeholder="t('agentSecurityScans.tasks.kind')">
              <a-select-option v-for="kind in scanKinds" :key="kind" :value="kind">{{ scanKindLabel(kind) }}</a-select-option>
            </a-select>
          </div>
          <a-table
            :columns="taskColumns"
            :data-source="filteredTasks"
            :pagination="tablePagination"
            row-key="task_id"
            table-layout="fixed"
            :scroll="{ x: 1220 }"
            :locale="{ emptyText: t('agentSecurityScans.tasks.empty') }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'task_id'">
                <button class="id-link" type="button" :title="record.task_id" @click="openTaskDetail(record.task_id)">{{ record.task_id }}</button>
              </template>
              <template v-else-if="column.key === 'target_id'">{{ targetName(record.target_id) }}</template>
              <template v-else-if="column.key === 'scan_kind'"><a-tag color="geekblue">{{ scanKindLabel(record.scan_kind) }}</a-tag></template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'progress'">
                <div class="usage-cell">
                  <span>{{ t('agentSecurityScans.tasks.roundUsage', { value: record.usage?.rounds || 0 }) }}</span>
                  <span>{{ t('agentSecurityScans.tasks.tokenUsage', { value: formatNumber(record.usage?.tokens || 0) }) }}</span>
                </div>
              </template>
              <template v-else-if="column.key === 'created_at'">{{ formatDateTime(record.created_at) }}</template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" size="small" @click="openTaskDetail(record.task_id)">{{ t('agentSecurityScans.view') }}</a-button>
                  <a-popconfirm v-if="canCancel(record)" :title="t('agentSecurityScans.tasks.cancelConfirm')" @confirm="cancelTask(record)">
                    <a-button type="link" size="small" danger>{{ t('agentSecurityScans.tasks.cancel') }}</a-button>
                  </a-popconfirm>
                  <a-button v-if="canKill(record)" type="link" size="small" danger @click="openKillSwitchModal(record)">{{ t('agentSecurityScans.tasks.killSwitch') }}</a-button>
                </a-space>
              </template>
            </template>
          </a-table>
        </template>

        <template v-else-if="activeStage === 'findings'">
          <div class="panel-heading">
            <div>
              <h2>{{ t('agentSecurityScans.findings.title') }}</h2>
              <p>{{ t('agentSecurityScans.findings.description') }}</p>
            </div>
            <a-select
              v-model:value="findingTaskId"
              show-search
              class="task-picker"
              option-filter-prop="label"
              :placeholder="t('agentSecurityScans.findings.selectTask')"
              @change="loadFindings"
            >
              <a-select-option v-for="task in tasks" :key="task.task_id" :value="task.task_id" :label="`${targetName(task.target_id)} ${task.task_id}`">
                {{ targetName(task.target_id) }} · {{ task.task_id }}
              </a-select-option>
            </a-select>
          </div>

          <div v-if="findingTaskId" class="severity-strip">
            <div v-for="severity in severityOrder" :key="severity" class="severity-item">
              <span class="severity-dot" :class="`severity-${severity}`"></span>
              <span>{{ severityLabel(severity) }}</span>
              <strong>{{ severityCounts[severity] || 0 }}</strong>
            </div>
          </div>

          <a-table
            :columns="findingColumns"
            :data-source="findings"
            :loading="findingsLoading"
            :pagination="tablePagination"
            row-key="finding_id"
            :scroll="{ x: 1180 }"
            :locale="{ emptyText: findingTaskId ? t('agentSecurityScans.findings.empty') : t('agentSecurityScans.findings.chooseTask') }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'severity'"><a-tag :color="severityColor(record.severity)">{{ severityLabel(record.severity) }}</a-tag></template>
              <template v-else-if="column.key === 'title'">
                <div class="finding-title">
                  <strong>{{ findingTitle(record) }}</strong>
                  <code>{{ record.finding_code }}</code>
                  <a-space v-if="record.risk_codes?.length" wrap><a-tag v-for="code in record.risk_codes" :key="code" color="blue">{{ agenticRiskLabel(code, t, te) }}</a-tag></a-space>
                  <span v-else class="muted">{{ t('agentSecurityScans.findings.unmappedRisk') }}</span>
                </div>
              </template>
              <template v-else-if="column.key === 'status'"><a-tag :color="findingStatusColor(record.status)">{{ findingStatusLabel(record.status) }}</a-tag></template>
              <template v-else-if="column.key === 'confidence'">{{ Math.round((record.confidence || 0) * 100) }}%</template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" size="small" @click="openFindingDetail(record)">{{ t('agentSecurityScans.view') }}</a-button>
                  <a-button v-if="canAdmin" type="link" size="small" @click="openDispositionModal(record)">{{ t('agentSecurityScans.findings.dispose') }}</a-button>
                </a-space>
              </template>
            </template>
          </a-table>
        </template>

        <template v-else>
          <div class="panel-heading">
            <div>
              <h2>{{ t('agentSecurityScans.reports.title') }}</h2>
              <p>{{ t('agentSecurityScans.reports.description') }}</p>
            </div>
          </div>
          <a-table
            :columns="reportColumns"
            :data-source="reportTasks"
            :pagination="tablePagination"
            row-key="task_id"
            :scroll="{ x: 1080 }"
            :locale="{ emptyText: t('agentSecurityScans.reports.empty') }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'target_id'">{{ targetName(record.target_id) }}</template>
              <template v-else-if="column.key === 'scan_kind'">{{ scanKindLabel(record.scan_kind) }}</template>
              <template v-else-if="column.key === 'status'"><a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag></template>
              <template v-else-if="column.key === 'engine'">{{ record.engine?.name || record.engine?.engine_name || '—' }}</template>
              <template v-else-if="column.key === 'completed_at'">{{ formatDateTime(record.completed_at || record.updated_at) }}</template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" size="small" @click="openTaskDetail(record.task_id)">{{ t('agentSecurityScans.reports.open') }}</a-button>
                  <a-button type="link" size="small" @click="openComparison(record)">{{ t('agentSecurityScans.reports.compare') }}</a-button>
                  <a-button type="link" size="small" @click="downloadReport(record)">{{ t('agentSecurityScans.reports.exportJson') }}</a-button>
                </a-space>
              </template>
            </template>
          </a-table>
        </template>
      </div>
    </a-spin>

    <a-modal v-model:open="comparisonModalOpen" :title="t('agentSecurityScans.comparison.title')" width="920px" :footer="null">
      <a-alert class="modal-alert" type="info" show-icon :message="t('agentSecurityScans.comparison.boundary')" />
      <div class="comparison-controls">
        <a-select v-model:value="comparisonBaselineId" :placeholder="t('agentSecurityScans.comparison.selectBaseline')" show-search option-filter-prop="label">
          <a-select-option v-for="item in comparisonBaselines" :key="item.task_id" :value="item.task_id" :label="`${item.task_id} ${formatDateTime(item.completed_at)}`">
            {{ formatDateTime(item.completed_at) }} · {{ item.task_id }}
          </a-select-option>
        </a-select>
        <a-button type="primary" :loading="comparisonLoading" :disabled="!comparisonBaselineId" @click="loadComparison">{{ t('agentSecurityScans.comparison.run') }}</a-button>
      </div>
      <a-empty v-if="!comparisonBaselines.length" :description="t('agentSecurityScans.comparison.noBaseline')" />
      <a-spin v-else :spinning="comparisonLoading">
        <template v-if="comparisonResult">
          <a-alert
            class="modal-alert"
            :type="comparisonResult.comparison_status === 'complete' ? 'success' : 'warning'"
            show-icon
            :message="comparisonResult.comparison_status === 'complete' ? t('agentSecurityScans.comparison.complete') : t('agentSecurityScans.comparison.partial')"
            :description="t('agentSecurityScans.comparison.statusDetail', { coverage: comparisonResult.coverage_match ? t('agentSecurityScans.comparison.matched') : t('agentSecurityScans.comparison.changed'), engine: comparisonResult.engine_match ? t('agentSecurityScans.comparison.matched') : t('agentSecurityScans.comparison.changed') })"
          />
          <div class="comparison-grid">
            <section v-for="bucket in comparisonBuckets" :key="bucket.key" class="comparison-bucket">
              <header><span>{{ bucket.label }}</span><strong>{{ comparisonResult.summary?.[bucket.key] || 0 }}</strong></header>
              <a-list :data-source="comparisonResult[bucket.key] || []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta :title="comparisonFinding(item, bucket.key).title" :description="comparisonFinding(item, bucket.key).finding_code" />
                    <a-tag v-if="bucket.key === 'unable_to_retest'" color="orange">{{ comparisonReasonLabel(item.reason_code) }}</a-tag>
                    <a-tag v-else :color="comparisonBucketColor(bucket.key)">{{ severityLabel(comparisonFinding(item, bucket.key).severity) }}</a-tag>
                  </a-list-item>
                </template>
              </a-list>
              <p v-if="!(comparisonResult[bucket.key] || []).length" class="muted comparison-empty">{{ t('agentSecurityScans.comparison.emptyBucket') }}</p>
            </section>
          </div>
          <p class="comparison-limit">{{ t('agentSecurityScans.comparison.dynamicLimit') }}</p>
        </template>
      </a-spin>
    </a-modal>

    <a-modal
      v-model:open="targetModalOpen"
      :title="editingTarget ? t('agentSecurityScans.targets.editTitle') : t('agentSecurityScans.targets.createTitle')"
      :confirm-loading="submittingTarget"
      width="min(920px, 94vw)"
      @ok="saveTarget"
    >
      <a-form layout="vertical">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.targets.name')" required><a-input v-model:value="targetForm.name" :maxlength="128" /></a-form-item></a-col>
          <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.targets.assetType')" required>
            <a-select v-model:value="targetForm.asset_type" :disabled="Boolean(editingTarget)" @change="handleAssetTypeChange">
              <a-select-option v-for="type in assetTypes" :key="type" :value="type">{{ assetTypeLabel(type) }}</a-select-option>
            </a-select>
          </a-form-item></a-col>
        </a-row>
        <a-form-item :label="t('agentSecurityScans.targets.connectorType')" required>
          <a-select v-model:value="targetForm.connector_type" show-search :disabled="Boolean(editingTarget)" @change="handleConnectorTypeChange">
            <a-select-option v-for="type in availableConnectorTypes" :key="type" :value="type">{{ connectorTypeLabel(type) }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :xs="24" :md="8"><a-form-item :label="t('agentSecurityScans.environment')" required><a-select v-model:value="targetForm.environment"><a-select-option v-for="environment in securityEnvironments" :key="environment" :value="environment">{{ environmentLabel(environment) }}</a-select-option></a-select></a-form-item></a-col>
          <a-col :xs="24" :md="16"><a-form-item :label="t('agentSecurityScans.allowedCapabilities')" :extra="t('agentSecurityScans.targets.capabilitiesHelp')"><a-select v-model:value="targetForm.allowed_capabilities" mode="multiple" :max-tag-count="3"><a-select-option v-for="capability in securityCapabilities" :key="capability" :value="capability">{{ capabilityLabel(capability) }}</a-select-option></a-select></a-form-item></a-col>
        </a-row>
        <a-form-item v-if="targetForm.connector_type === 'mcp_gateway'" :label="t('agentSecurityScans.targets.gateway')" required>
          <a-select v-model:value="targetForm.gateway_id" show-search option-filter-prop="label" @change="handleGatewayChange">
            <a-select-option v-for="gateway in mcpGateways" :key="gateway.id" :value="gateway.id" :label="gateway.name || gateway.slug">{{ gateway.name || gateway.slug }} · {{ gateway.slug }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item v-else :label="t('agentSecurityScans.targets.endpoint')" required><a-input v-model:value="targetForm.endpoint_url" :placeholder="t('agentSecurityScans.targets.endpointPlaceholder')" /></a-form-item>
        <template v-if="targetForm.connector_type === 'dify'">
          <a-alert class="modal-alert" type="info" show-icon :message="t('agentSecurityScans.inventory.targetConfigBoundary')" />
          <a-row :gutter="16">
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.inventory.consoleBaseUrl')" required><a-input v-model:value="targetForm.dify_console_base_url" placeholder="https://dify.example.com" /></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.inventory.workspaceId')" required><a-input v-model:value="targetForm.dify_workspace_id" /></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.inventory.appId')" required><a-input v-model:value="targetForm.dify_app_id" /></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.inventory.workflowId')"><a-input v-model:value="targetForm.dify_workflow_id" /></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.inventory.owner')"><a-input v-model:value="targetForm.dify_owner" /></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.inventory.ownerGroup')"><a-input v-model:value="targetForm.dify_owner_group" /></a-form-item></a-col>
          </a-row>
          <a-form-item :label="t('agentSecurityScans.inventory.declaredIntent')" :extra="t('agentSecurityScans.inventory.declaredIntentHelp')"><a-textarea v-model:value="targetForm.dify_declared_intent" :rows="2" /></a-form-item>
          <a-form-item :label="t('agentSecurityScans.inventory.redirectHosts')" :extra="t('agentSecurityScans.inventory.redirectHostsHelp')"><a-textarea v-model:value="targetForm.dify_redirect_hosts" :rows="2" /></a-form-item>
          <a-form-item :label="t('agentSecurityScans.inventory.mcpBindings')" :extra="t('agentSecurityScans.inventory.mcpBindingsHelp')">
            <a-spin :spinning="difyMcpBindingsLoading">
              <div class="mcp-binding-editor">
                <div class="mcp-binding-summary">
                  <span>{{ t('agentSecurityScans.inventory.mcpBindingVerified') }} <strong>{{ difyMcpBindingSummary.verified }}</strong></span>
                  <span>{{ t('agentSecurityScans.inventory.mcpBindingUnbound') }} <strong>{{ difyMcpBindingSummary.unbound }}</strong></span>
                  <span>{{ t('agentSecurityScans.inventory.mcpBindingToolMissing') }} <strong>{{ difyMcpBindingSummary.configured_tool_not_discovered }}</strong></span>
                </div>
                <a-alert
                  v-if="!editingTarget"
                  type="info"
                  show-icon
                  :message="t('agentSecurityScans.inventory.mcpBindingsRequireSnapshot')"
                />
                <a-empty
                  v-else-if="!difyMcpBindingsLoading && !targetForm.dify_mcp_bindings.length"
                  :description="t('agentSecurityScans.inventory.mcpBindingsEmpty')"
                />
                <div v-else class="mcp-binding-list">
                  <div v-for="binding in targetForm.dify_mcp_bindings" :key="binding.provider_id" class="mcp-binding-row">
                    <div class="mcp-binding-provider">
                      <code :title="binding.provider_id">{{ binding.provider_id }}</code>
                      <div>
                        <a-tag v-for="toolName in binding.tool_names" :key="toolName">{{ toolName }}</a-tag>
                        <small v-if="!binding.tool_names.length">{{ t('agentSecurityScans.inventory.mcpBindingNoSnapshotTools') }}</small>
                      </div>
                    </div>
                    <a-select
                      v-model:value="binding.server_id"
                      allow-clear
                      show-search
                      option-filter-prop="label"
                      :placeholder="t('agentSecurityScans.inventory.mcpServerPlaceholder')"
                    >
                      <a-select-option
                        v-for="server in difyMcpBindingOptions.servers"
                        :key="server.server_id"
                        :value="server.server_id"
                        :label="mcpServerOptionLabel(server)"
                      >
                        <div class="mcp-server-option">
                          <strong>{{ server.name }} · {{ server.slug }}</strong>
                          <small>{{ mcpServerMetaLabel(server) }}</small>
                        </div>
                      </a-select-option>
                    </a-select>
                    <a-tag :color="mcpBindingStatusColor(mcpBindingStatus(binding))">
                      {{ mcpBindingStatusLabel(mcpBindingStatus(binding)) }}
                    </a-tag>
                  </div>
                </div>
              </div>
            </a-spin>
          </a-form-item>
          <a-form-item :label="t('agentSecurityScans.inventory.knowledgeBindings')" :extra="t('agentSecurityScans.inventory.knowledgeBindingsHelp')"><a-textarea v-model:value="targetForm.dify_knowledge_bindings_json" class="code-input" :rows="3" /></a-form-item>
        </template>
        <a-form-item :label="t('agentSecurityScans.targets.cidrs')" :extra="t('agentSecurityScans.targets.cidrsHelp')"><a-textarea v-model:value="targetForm.allowed_cidrs" :rows="2" /></a-form-item>
        <a-form-item v-if="targetForm.connector_type !== 'mcp_gateway'" :label="targetForm.connector_type === 'dify' ? t('agentSecurityScans.inventory.advancedConfig') : t('agentSecurityScans.targets.config')" :extra="targetConfigHelp"><a-textarea v-model:value="targetForm.config_json" class="code-input" :rows="6" /></a-form-item>
        <a-alert v-if="targetForm.asset_type === 'llm'" class="modal-alert" type="info" show-icon :message="t('agentSecurityScans.targets.llmConfigBoundary')" />
        <a-alert v-if="targetForm.asset_type === 'ai_infrastructure'" class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.targets.infrastructureConfigBoundary')" />
        <a-form-item v-if="targetForm.connector_type !== 'mcp_gateway'">
          <a-checkbox v-model:checked="targetForm.allow_insecure_transport">{{ t('agentSecurityScans.targets.allowInsecure') }}</a-checkbox>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="credentialModalOpen" :title="t('agentSecurityScans.targets.credentialTitle')" :confirm-loading="submittingCredential" @ok="saveCredential">
      <a-alert class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.targets.credentialWarning')" />
      <a-form layout="vertical">
        <a-form-item :label="t('agentSecurityScans.inventory.credentialPurpose')" required>
          <a-select v-model:value="credentialForm.purpose">
            <a-select-option v-for="purpose in availableCredentialPurposes" :key="purpose" :value="purpose">{{ t(`agentSecurityScans.inventory.credentialPurposes.${purpose}`) }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('agentSecurityScans.targets.credentialType')" required>
          <a-select v-model:value="credentialForm.credential_type">
            <a-select-option v-for="type in credentialTypes" :key="type" :value="type">{{ t(`agentSecurityScans.targets.credentialTypes.${type}`) }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('agentSecurityScans.targets.secret')" required><a-input-password v-model:value="credentialForm.secret" /></a-form-item>
        <div v-if="credentialTarget?.credentials?.length" class="credential-inventory">
          <strong>{{ t('agentSecurityScans.inventory.configuredCredentials') }}</strong>
          <div v-for="item in credentialTarget.credentials" :key="item.credential_id">
            <span>{{ t(`agentSecurityScans.inventory.credentialPurposes.${item.purpose}`, item.purpose) }}</span>
            <code :title="item.secret_masked">{{ item.secret_masked }}</code>
            <a-tag :color="item.status === 'active' ? 'green' : 'default'">{{ t(`agentSecurityScans.inventory.credentialStatuses.${item.status}`, item.status) }}</a-tag>
            <a-popconfirm
              v-if="item.status !== 'revoked'"
              :title="item.status === 'active' ? t('agentSecurityScans.inventory.disableCredentialConfirm') : t('agentSecurityScans.inventory.enableCredentialConfirm')"
              @confirm="toggleCredentialStatus(item)"
            >
              <a-button type="link" size="small" :loading="credentialStatusUpdating === item.credential_id">
                {{ item.status === 'active' ? t('agentSecurityScans.disable') : t('agentSecurityScans.enable') }}
              </a-button>
            </a-popconfirm>
          </div>
        </div>
      </a-form>
    </a-modal>

    <a-modal v-model:open="policyModalOpen" :title="editingPolicy ? t('agentSecurityScans.policies.editTitle') : t('agentSecurityScans.policies.createTitle')" :confirm-loading="submittingPolicy" width="760px" @ok="savePolicy">
      <a-form layout="vertical">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.policies.name')" required><a-input v-model:value="policyForm.name" :disabled="Boolean(editingPolicy)" /></a-form-item></a-col>
          <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.policies.mode')" required><a-select v-model:value="policyForm.execution_mode"><a-select-option v-for="mode in executionModes" :key="mode" :value="mode" :disabled="policyForm.environment === 'production' && mode === 'active_full'">{{ executionModeLabel(mode) }}</a-select-option></a-select></a-form-item></a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :md="8"><a-form-item :label="t('agentSecurityScans.environment')" required><a-select v-model:value="policyForm.environment" @change="handlePolicyEnvironmentChange"><a-select-option v-for="environment in securityEnvironments" :key="environment" :value="environment">{{ environmentLabel(environment) }}</a-select-option></a-select></a-form-item></a-col>
          <a-col :xs="24" :md="16"><a-form-item :label="t('agentSecurityScans.allowedCapabilities')" :extra="t('agentSecurityScans.policies.capabilitiesHelp')"><a-select v-model:value="policyForm.allowed_capabilities" mode="multiple" :max-tag-count="3"><a-select-option v-for="capability in securityCapabilities" :key="capability" :value="capability">{{ capabilityLabel(capability) }}</a-select-option></a-select></a-form-item></a-col>
        </a-row>
        <a-alert v-if="policyForm.environment === 'production'" class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.policies.productionModeBoundary')" />
        <template v-if="policyForm.environment === 'production' && policyForm.execution_mode === 'active_safe'">
          <a-alert class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.policies.productionControlsRequired')" :description="t('agentSecurityScans.policies.productionControlsHelp')" />
          <a-form-item :label="t('agentSecurityScans.policies.productionTargets')" :extra="t('agentSecurityScans.policies.productionTargetsHelp')" required>
            <a-select v-model:value="policyForm.production_target_ids" mode="multiple" show-search option-filter-prop="label">
              <a-select-option v-for="target in targets.filter(item => item.environment === 'production')" :key="target.target_id" :value="target.target_id" :label="`${target.name} ${target.target_id}`">{{ target.name }} · {{ target.target_id }}</a-select-option>
            </a-select>
          </a-form-item>
          <a-row :gutter="16">
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.policies.maintenanceStartUtc')" required><a-input v-model:value="policyForm.maintenance_window_start" type="datetime-local" /></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.policies.maintenanceEndUtc')" required><a-input v-model:value="policyForm.maintenance_window_end" type="datetime-local" /></a-form-item></a-col>
          </a-row>
          <a-form-item :label="t('agentSecurityScans.policies.dedicatedIdentity')" :extra="t('agentSecurityScans.policies.dedicatedIdentityHelp')" required><a-input v-model:value="policyForm.dedicated_identity_ref" :maxlength="255" /></a-form-item>
        </template>
        <a-row :gutter="16">
          <a-col v-for="field in policyBudgetFields" :key="field.key" :xs="24" :md="8"><a-form-item :label="t(field.label)"><a-input-number v-model:value="policyForm[field.key]" :min="field.min" :max="field.max" class="number-input" /></a-form-item></a-col>
        </a-row>
        <a-form-item :label="t('agentSecurityScans.policies.allowlist')" :extra="t('agentSecurityScans.policies.allowlistHelp')"><a-textarea v-model:value="policyForm.outbound_allowlist" :rows="2" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="taskModalOpen" :title="t('agentSecurityScans.tasks.createTitle')" width="820px">
      <template #footer>
        <a-button @click="taskModalOpen = false">{{ t('agentSecurityScans.tasks.close') }}</a-button>
        <a-button :loading="previewingTask" :disabled="submittingTask" @click="loadTaskPreview">{{ t('agentSecurityScans.tasks.preview') }}</a-button>
        <a-button type="primary" :loading="submittingTask" :disabled="!taskPreview || previewingTask" @click="saveTask">{{ t('agentSecurityScans.tasks.createConfirmed') }}</a-button>
      </template>
      <a-form layout="vertical">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.tasks.target')" required><a-select v-model:value="taskForm.target_id" @change="handleTaskTargetChange"><a-select-option v-for="target in activeTargets" :key="target.target_id" :value="target.target_id">{{ target.name }}</a-select-option></a-select></a-form-item></a-col>
          <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.tasks.policy')" required><a-select v-model:value="taskForm.policy_id" @change="handleTaskPolicyChange"><a-select-option v-for="policy in availablePolicies" :key="policy.policy_id" :value="policy.policy_id">{{ policy.name }}</a-select-option></a-select></a-form-item></a-col>
        </a-row>
        <template v-if="requiresProductionApproval">
          <a-alert class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.tasks.productionApprovalRequired')" :description="t('agentSecurityScans.tasks.productionApprovalHelp')" />
          <a-form-item :label="t('agentSecurityScans.tasks.productionApproval')" required>
            <a-space-compact block>
              <a-select v-model:value="taskForm.approval_id" class="approval-select" :placeholder="t('agentSecurityScans.tasks.approvalPlaceholder')">
                <a-select-option v-for="approval in availableApprovals" :key="approval.approval_id" :value="approval.approval_id">{{ approval.approval_id }} · {{ formatUtcDateTime(approval.maintenance_window_end) }}</a-select-option>
              </a-select>
              <a-button v-if="canAdmin" :loading="submittingApproval" :disabled="!selectedTaskTarget?.credential_configured" @click="approveProductionScan">{{ t('agentSecurityScans.tasks.approveProductionScan') }}</a-button>
            </a-space-compact>
            <div v-if="!selectedTaskTarget?.credential_configured" class="field-help-error">{{ t('agentSecurityScans.tasks.dedicatedCredentialRequired') }}</div>
          </a-form-item>
        </template>
        <a-form-item :label="t('agentSecurityScans.tasks.kind')" required><a-select v-model:value="taskForm.scan_kind" :disabled="availableScanKinds.length === 1"><a-select-option v-for="kind in availableScanKinds" :key="kind" :value="kind">{{ scanKindLabel(kind) }}</a-select-option></a-select></a-form-item>
        <template v-if="taskForm.scan_kind === 'agent_risk_scan'">
          <a-form-item :label="t('agentSecurityScans.tasks.skills')"><a-select v-model:value="taskForm.skills" mode="multiple" :max-tag-count="3"><a-select-option v-for="skill in agentScanSkills" :key="skill" :value="skill">{{ skill }}</a-select-option></a-select></a-form-item>
          <a-form-item :label="t('agentSecurityScans.tasks.prompt')"><a-textarea v-model:value="taskForm.prompt" :rows="3" :maxlength="4096" /></a-form-item>
          <a-row :gutter="16">
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.tasks.conversationMode')"><a-select v-model:value="taskForm.conversation_mode"><a-select-option value="single_turn">{{ t('agentSecurityScans.tasks.singleTurn') }}</a-select-option><a-select-option value="multi_turn">{{ t('agentSecurityScans.tasks.multiTurn') }}</a-select-option></a-select></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.tasks.continueFrom')"><a-select v-model:value="taskForm.continue_from_task_id" allow-clear><a-select-option v-for="task in resumableTasks" :key="task.task_id" :value="task.task_id">{{ task.task_id }}</a-select-option></a-select></a-form-item></a-col>
          </a-row>
        </template>
        <template v-else-if="taskForm.scan_kind === 'llm_redteam_scan'">
          <a-alert class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.tasks.llmRedteamBoundary')" />
          <a-form-item :label="t('agentSecurityScans.tasks.redteamInputMode')">
            <a-radio-group v-model:value="taskForm.llm_input_mode" @change="handleLlmInputModeChange">
              <a-radio-button value="dataset">{{ t('agentSecurityScans.tasks.datasetMode') }}</a-radio-button>
              <a-radio-button value="prompt">{{ t('agentSecurityScans.tasks.customPromptMode') }}</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <a-form-item v-if="taskForm.llm_input_mode === 'dataset'" :label="t('agentSecurityScans.tasks.datasets')" required>
            <RedteamDatasetPicker v-model="taskForm.datasets" :datasets="llmDatasets" :loading="redteamOptionsLoading" />
          </a-form-item>
          <a-form-item v-else :label="t('agentSecurityScans.tasks.redteamPrompt')" required><a-textarea v-model:value="taskForm.prompt" :rows="4" :maxlength="4096" /></a-form-item>
          <a-row :gutter="16">
            <a-col v-if="taskForm.llm_input_mode === 'dataset'" :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.tasks.numPrompts')"><a-input-number v-model:value="taskForm.num_prompts" :min="1" :max="100" class="number-input" /></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.tasks.randomSeed')"><a-input-number v-model:value="taskForm.random_seed" :min="0" :max="2147483647" class="number-input" /></a-form-item></a-col>
            <a-col :xs="24" :md="24">
              <a-form-item :label="t('agentSecurityScans.tasks.evaluationModel')">
                <a-select v-model:value="taskForm.evaluation_model" allow-clear show-search option-filter-prop="label" :loading="redteamOptionsLoading" :disabled="redteamOptionsLoading" :placeholder="t('agentSecurityScans.tasks.defaultEvaluationModel')" :not-found-content="t('agentSecurityScans.tasks.noEvaluationModels')">
                  <a-select-option v-for="model in evaluationModels" :key="model.id" :value="model.name" :label="`${model.display_name || model.name} (${model.name}) · ${model.provider_name}`">
                    {{ model.display_name || model.name }} ({{ model.name }}) · {{ model.provider_name }}
                  </a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
          </a-row>
          <a-form-item :label="t('agentSecurityScans.tasks.techniques')"><a-select v-model:value="taskForm.techniques" mode="multiple" :max-tag-count="3"><a-select-option v-for="technique in llmTechniques" :key="technique" :value="technique">{{ technique }}</a-select-option></a-select></a-form-item>
        </template>
        <template v-else-if="taskForm.scan_kind === 'ai_infrastructure_vulnerability_scan'">
          <a-alert class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.tasks.infrastructureBoundary')" />
          <a-row :gutter="16">
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.tasks.scanTimeout')"><a-input-number v-model:value="taskForm.scan_timeout_seconds" :min="1" :max="120" class="number-input" /></a-form-item></a-col>
            <a-col :xs="24" :md="12"><a-form-item :label="t('agentSecurityScans.tasks.scanConcurrency')"><a-input-number v-model:value="taskForm.scan_concurrency" :min="1" :max="16" class="number-input" /></a-form-item></a-col>
          </a-row>
          <a-form-item><a-checkbox v-model:checked="taskForm.http_authorized">{{ t('agentSecurityScans.tasks.httpAuthorized') }}</a-checkbox></a-form-item>
          <a-form-item><a-checkbox v-model:checked="taskForm.private_network_authorized">{{ t('agentSecurityScans.tasks.privateNetworkAuthorized') }}</a-checkbox></a-form-item>
        </template>
        <template v-else-if="taskForm.scan_kind === 'dify_asset_inventory'">
          <a-alert class="modal-alert" type="info" show-icon :message="t('agentSecurityScans.inventory.taskBoundary')" />
          <a-form-item :label="t('agentSecurityScans.inventory.collectionMode')">
            <a-radio-group v-model:value="taskForm.inventory_source">
              <a-radio-button value="console_api">{{ t('agentSecurityScans.inventory.consoleMode') }}</a-radio-button>
              <a-radio-button value="manual_dsl">{{ t('agentSecurityScans.inventory.manualMode') }}</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <template v-if="taskForm.inventory_source === 'manual_dsl'">
            <a-upload :before-upload="loadManualDsl" :show-upload-list="false" accept=".yml,.yaml,.json,text/yaml,application/json"><a-button>{{ t('agentSecurityScans.inventory.chooseDsl') }}</a-button></a-upload>
            <a-form-item class="manual-dsl" :label="t('agentSecurityScans.inventory.dslDocument')" required><a-textarea v-model:value="taskForm.manual_dsl" class="code-input" :rows="7" /></a-form-item>
          </template>
          <a-form-item><a-checkbox v-model:checked="taskForm.include_prompt_text" :disabled="!canAdmin">{{ t('agentSecurityScans.inventory.includePromptText') }}</a-checkbox><div class="muted">{{ t('agentSecurityScans.inventory.promptDefaultBoundary') }}</div></a-form-item>
          <a-form-item :extra="canAdmin ? t('agentSecurityScans.inventory.intentInferencePrivacy') : t('agentSecurityScans.inventory.intentInferenceAdminOnly')">
            <a-checkbox v-model:checked="taskForm.infer_agent_intent" :disabled="!canAdmin">
              {{ t('agentSecurityScans.inventory.inferAgentIntent') }}
            </a-checkbox>
          </a-form-item>
          <a-form-item v-if="taskForm.infer_agent_intent" :label="t('agentSecurityScans.inventory.intentInferenceModel')">
            <a-select v-model:value="taskForm.intent_inference_model" allow-clear :placeholder="t('agentSecurityScans.inventory.defaultIntentModel')">
              <a-select-option v-for="model in intentInferenceModels" :key="model.id" :value="model.name">
                {{ model.display_name || model.name }} · {{ model.provider_name || t('agentSecurityScans.inventory.unknownProvider') }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item><a-checkbox v-model:checked="taskForm.knowledge_content_authorized">{{ t('agentSecurityScans.inventory.knowledgeAuthorized') }}</a-checkbox></a-form-item>
          <a-row v-if="taskForm.knowledge_content_authorized" :gutter="16">
            <a-col :xs="24" :md="8"><a-form-item :label="t('agentSecurityScans.inventory.maxDocuments')"><a-input-number v-model:value="taskForm.max_knowledge_documents" :min="1" :max="1000" class="number-input" /></a-form-item></a-col>
            <a-col :xs="24" :md="8"><a-form-item :label="t('agentSecurityScans.inventory.maxSegments')"><a-input-number v-model:value="taskForm.max_knowledge_segments" :min="1" :max="10000" class="number-input" /></a-form-item></a-col>
            <a-col :xs="24" :md="8"><a-form-item :label="t('agentSecurityScans.inventory.maxKnowledgeBytes')"><a-input-number v-model:value="taskForm.max_knowledge_bytes" :min="1" :max="104857600" class="number-input" /></a-form-item></a-col>
          </a-row>
        </template>
        <a-alert type="info" show-icon :message="taskSafetyMessage" />
        <a-spin :spinning="previewingTask">
          <section v-if="taskPreview" class="task-preview">
            <div class="preview-heading">
              <div><strong>{{ t('agentSecurityScans.tasks.previewTitle') }}</strong><span>{{ t('agentSecurityScans.tasks.previewBound') }}</span></div>
              <a-tag color="green">{{ t('agentSecurityScans.tasks.previewReady') }}</a-tag>
            </div>
            <a-descriptions bordered size="small" :column="{ xs: 1, sm: 2 }">
              <a-descriptions-item :label="t('agentSecurityScans.tasks.target')">{{ taskPreview.target.name }}</a-descriptions-item>
              <a-descriptions-item :label="t('agentSecurityScans.environment')">{{ environmentLabel(taskPreview.target.environment) }}</a-descriptions-item>
              <a-descriptions-item :label="t('agentSecurityScans.tasks.policy')">{{ taskPreview.policy.name }}</a-descriptions-item>
              <a-descriptions-item :label="t('agentSecurityScans.policies.mode')">{{ executionModeLabel(taskPreview.policy.execution_mode) }}</a-descriptions-item>
              <a-descriptions-item :label="t('agentSecurityScans.tasks.plannedCases')">{{ taskPreview.cases.length }}</a-descriptions-item>
              <a-descriptions-item :label="t('agentSecurityScans.tasks.plannedTools')">{{ taskPreview.tool_plan.tools.length }}</a-descriptions-item>
            </a-descriptions>
            <div v-if="taskPreview.tool_plan.dify_mcp_bindings" class="preview-binding-summary">
              <span>{{ t('agentSecurityScans.inventory.mcpBindingVerified') }}<strong>{{ taskPreview.tool_plan.dify_mcp_bindings.verified }}</strong></span>
              <span>{{ t('agentSecurityScans.inventory.mcpBindingUnbound') }}<strong>{{ taskPreview.tool_plan.dify_mcp_bindings.unbound }}</strong></span>
              <span>{{ t('agentSecurityScans.inventory.mcpBindingToolMissing') }}<strong>{{ taskPreview.tool_plan.dify_mcp_bindings.configured_tool_not_discovered }}</strong></span>
            </div>
            <h4>{{ t('agentSecurityScans.tasks.casePlan') }}</h4>
            <div class="preview-list">
              <div v-for="item in taskPreview.cases" :key="item.case_key" class="preview-row">
                <span>{{ previewCaseLabel(item) }}</span>
                <a-tag :color="item.dynamic ? 'orange' : 'blue'">{{ item.dynamic ? t('agentSecurityScans.tasks.runtimeDynamic') : t('agentSecurityScans.tasks.deterministic') }}</a-tag>
              </div>
            </div>
            <h4>{{ t('agentSecurityScans.tasks.toolPlan') }}</h4>
            <div v-if="taskPreview.tool_plan.tools.length" class="preview-list">
              <div v-for="tool in taskPreview.tool_plan.tools" :key="tool.name" class="preview-row">
                <code>{{ tool.name }}</code>
                <span>{{ tool.will_call ? t('agentSecurityScans.tasks.mayCall') : t('agentSecurityScans.tasks.willNotCall') }}</span>
              </div>
            </div>
            <span v-else class="muted">{{ t('agentSecurityScans.tasks.noTools') }}</span>
            <h4>{{ t('agentSecurityScans.tasks.budgetPlan') }}</h4>
            <div class="preview-budget">
              <span>{{ t('agentSecurityScans.policies.maxRounds') }}<strong>{{ formatNumber(taskPreview.budget.max_rounds) }}</strong></span>
              <span>{{ t('agentSecurityScans.policies.maxTokens') }}<strong>{{ formatNumber(taskPreview.budget.max_tokens) }}</strong></span>
              <span>{{ t('agentSecurityScans.policies.maxCost') }}<strong>{{ formatNumber(taskPreview.budget.max_cost_microunits) }}</strong></span>
              <span>{{ t('agentSecurityScans.policies.maxConcurrency') }}<strong>{{ formatNumber(taskPreview.budget.max_concurrent_requests) }}</strong></span>
              <span>{{ t('agentSecurityScans.policies.maxDuration') }}<strong>{{ formatDuration(taskPreview.budget.max_duration_seconds) }}</strong></span>
              <span>{{ t('agentSecurityScans.policies.maxBytes') }}<strong>{{ formatBytes(taskPreview.budget.max_response_bytes) }}</strong></span>
            </div>
            <a-alert v-if="taskPreview.limitations.length" class="preview-limit" type="warning" show-icon :message="t('agentSecurityScans.tasks.previewLimitations')" :description="taskPreview.limitations.map(previewLimitationLabel).join('；')" />
          </section>
          <a-empty v-else class="preview-empty" :description="t('agentSecurityScans.tasks.previewRequired')" />
        </a-spin>
      </a-form>
    </a-modal>

    <a-modal v-model:open="killSwitchModalOpen" :title="t('agentSecurityScans.tasks.killSwitchTitle')" :confirm-loading="submittingKillSwitch" :ok-button-props="{ danger: true, disabled: !killSwitchReason.trim() }" @ok="activateKillSwitch">
      <a-alert type="error" show-icon :message="t('agentSecurityScans.tasks.killSwitchWarning')" :description="t('agentSecurityScans.tasks.killSwitchBoundary')" />
      <a-form layout="vertical" class="kill-switch-form">
        <a-form-item :label="t('agentSecurityScans.tasks.killSwitchReason')" required>
          <a-textarea v-model:value="killSwitchReason" :rows="4" :maxlength="1000" :placeholder="t('agentSecurityScans.tasks.killSwitchReasonPlaceholder')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="dispositionModalOpen" :title="t('agentSecurityScans.findings.disposeTitle')" :confirm-loading="submittingDisposition" @ok="saveDisposition">
      <a-form layout="vertical"><a-form-item :label="t('agentSecurityScans.findings.status')"><a-select v-model:value="dispositionForm.status"><a-select-option v-for="status in findingStatuses" :key="status" :value="status">{{ findingStatusLabel(status) }}</a-select-option></a-select></a-form-item><a-form-item :label="t('agentSecurityScans.findings.comment')"><a-textarea v-model:value="dispositionForm.comment" :rows="4" :maxlength="4096" /></a-form-item></a-form>
    </a-modal>

    <a-drawer v-model:open="detailDrawerOpen" width="min(1440px, 96vw)" :title="t('agentSecurityScans.detail.title')">
      <a-spin :spinning="taskDetailLoading">
        <template v-if="taskDetail">
          <div class="detail-identity"><div><span>{{ t('agentSecurityScans.detail.task') }}</span><code>{{ taskDetail.task.task_id }}</code></div><a-tag :color="statusColor(taskDetail.task.status)">{{ statusLabel(taskDetail.task.status) }}</a-tag></div>
          <a-alert v-if="taskDetail.task.error_code" class="modal-alert" type="error" show-icon
            :message="taskErrorExplanation(taskDetail.task)" :description="taskDetail.task.error_code" />
          <a-alert
            v-if="taskHasNoFinalReport"
            class="modal-alert"
            type="warning"
            show-icon
            :message="t('agentSecurityScans.detail.noFinalReportTitle')"
            :description="t('agentSecurityScans.detail.noFinalReportDescription', { rounds: formatNumber(taskDetail.task.usage?.rounds), tokens: formatNumber(taskDetail.task.usage?.tokens) })"
          />
          <a-alert
            v-else-if="successfulTaskHasNoFindings"
            class="modal-alert"
            type="info"
            show-icon
            :message="t('agentSecurityScans.detail.noFindingsTitle')"
            :description="t('agentSecurityScans.detail.noFindingsDescription')"
          />
          <a-tabs>
            <a-tab-pane key="summary" :tab="t('agentSecurityScans.detail.summary')">
              <section v-if="llmReportMetadata" class="report-overview" :aria-label="t('agentSecurityScans.detail.resultsOverview')">
                <h3>{{ t('agentSecurityScans.detail.resultsOverview') }}</h3>
                <dl class="report-metrics">
                  <div><dt>{{ t('agentSecurityScans.detail.evaluatedCount') }}</dt><dd>{{ formatNumber(llmReportMetadata.completed_evaluations) }}</dd></div>
                  <div><dt>{{ t('agentSecurityScans.detail.resistedCount') }}</dt><dd>{{ formatNumber(llmReportMetadata.attack_resisted) }}</dd></div>
                  <div><dt>{{ t('agentSecurityScans.detail.riskCount') }}</dt><dd class="risk-number">{{ formatNumber(llmReportMetadata.jailbreak_signals) }}</dd></div>
                  <div><dt>{{ t('agentSecurityScans.detail.riskRate') }}</dt><dd>{{ llmReportMetadata.completed_evaluations > 0 ? `${Math.round(llmReportMetadata.jailbreak_signals / llmReportMetadata.completed_evaluations * 100)}%` : '—' }}</dd><small>{{ t('agentSecurityScans.detail.rateBasis') }}</small></div>
                </dl>
              </section>
              <a-descriptions class="report-summary" bordered :column="{ xs: 1, sm: 1, md: 2 }" size="small">
                <a-descriptions-item :label="t('agentSecurityScans.tasks.target')">{{ targetName(taskDetail.task.target_id) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.tasks.kind')">{{ scanKindLabel(taskDetail.task.scan_kind) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.status')">{{ taskDetail.task.status === 'succeeded' ? t('agentSecurityScans.detail.completedExecution') : statusLabel(taskDetail.task.status) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.tasks.policy')">{{ policyName(taskDetail.task.policy_id) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.started')">{{ formatDateTime(taskDetail.task.started_at) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.completed')">{{ formatDateTime(taskDetail.task.completed_at) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.roundsUsed')">{{ formatNumber(taskDetail.task.usage?.rounds) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.tokensUsed')">{{ llmReportMetadata?.token_accounting === 'unavailable_from_upstream' ? t('agentSecurityScans.detail.tokensNotReported') : formatNumber(taskDetail.task.usage?.tokens) }}</a-descriptions-item>
              </a-descriptions>
              <a-collapse class="report-technical" ghost><a-collapse-panel key="technical" :header="t('agentSecurityScans.detail.technicalDetails')">
              <a-descriptions bordered :column="{ xs: 1, sm: 1, md: 2 }" size="small">
                <a-descriptions-item :label="t('agentSecurityScans.tasks.target')">{{ targetName(taskDetail.task.target_id) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.tasks.kind')">{{ scanKindLabel(taskDetail.task.scan_kind) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.tasks.policy')">{{ policyName(taskDetail.task.policy_id) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.approval')"><code>{{ taskDetail.task.approval_id || '—' }}</code></a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.worker')">{{ taskDetail.task.worker_id || '—' }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.status')">{{ statusLabel(taskDetail.task.status) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.errorCode')"><code>{{ taskDetail.task.error_code || '—' }}</code></a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.errorMessage')" :span="2">{{ taskErrorExplanation(taskDetail.task) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.stopReason')">{{ taskReasonLabel(taskDetail.task.stop_reason) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.attempt')">{{ formatNumber(taskDetail.task.attempt) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.maxAttempts')">{{ formatNumber(taskDetail.task.max_attempts) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.roundsUsed')">{{ formatNumber(taskDetail.task.usage?.rounds) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.tokensUsed')">{{ llmReportMetadata?.token_accounting === 'unavailable_from_upstream' ? t('agentSecurityScans.detail.tokensNotReported') : formatNumber(taskDetail.task.usage?.tokens) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.lastHeartbeat')">{{ formatDateTime(taskDetail.task.heartbeat_at) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.leaseExpiresAt')">{{ formatDateTime(taskDetail.task.lease_expires_at) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.started')">{{ formatDateTime(taskDetail.task.started_at) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.completed')">{{ formatDateTime(taskDetail.task.completed_at) }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.tasks.killSwitch')">{{ taskDetail.task.kill_switch_activated ? t('agentSecurityScans.tasks.killSwitchActivated') : '—' }}</a-descriptions-item>
                <a-descriptions-item v-if="taskDetail.task.kill_switch_activated" :label="t('agentSecurityScans.tasks.killSwitchOperator')">{{ taskDetail.task.kill_switch_activated_by }} · {{ formatDateTime(taskDetail.task.kill_switch_activated_at) }}</a-descriptions-item>
                <a-descriptions-item v-if="taskDetail.task.kill_switch_activated" :label="t('agentSecurityScans.tasks.killSwitchReason')" :span="2">{{ taskDetail.task.kill_switch_reason }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.reportTemplateVersion')"><code>{{ taskDetail.task.report_template_version || t('agentSecurityScans.detail.legacyUnversioned') }}</code></a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.decisionCriteriaVersion')"><code>{{ taskDetail.task.decision_criteria_version || t('agentSecurityScans.detail.legacyUnversioned') }}</code></a-descriptions-item>
              </a-descriptions>
              </a-collapse-panel></a-collapse>
            </a-tab-pane>
            <a-tab-pane key="criteria" :tab="t('agentSecurityScans.detail.decisionCriteria')">
              <a-alert
                class="modal-alert"
                show-icon
                :type="taskDetail.report_contract?.snapshot_status === 'frozen' ? 'info' : 'warning'"
                :message="taskDetail.report_contract?.snapshot_status === 'frozen' ? t('agentSecurityScans.detail.frozenCriteriaHint') : t('agentSecurityScans.detail.legacyCriteriaHint')"
              />
              <a-list :data-source="taskDetail.report_contract?.decision_criteria || []" bordered>
                <template #renderItem="{ item }"><a-list-item><div><strong>{{ criteriaRuleLabel(item.rule_id) }}</strong><div class="muted"><code>{{ item.rule_id }}</code> · {{ item.outcome }}</div></div></a-list-item></template>
                <template #empty><a-empty :description="t('agentSecurityScans.detail.noCriteriaSnapshot')" /></template>
              </a-list>
            </a-tab-pane>
            <a-tab-pane key="tc260" :tab="t('agentSecurityScans.tc260.title')">
              <template v-if="tc260Profile">
                <a-alert class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.tc260.boundary')" />
                <a-descriptions bordered :column="2" size="small">
                  <a-descriptions-item :label="t('agentSecurityScans.tc260.profileVersion')"><code>{{ tc260Profile.profile_version }}</code></a-descriptions-item>
                  <a-descriptions-item :label="t('agentSecurityScans.tc260.sourceType')">{{ t('agentSecurityScans.tc260.technicalDocument') }}</a-descriptions-item>
                  <a-descriptions-item :label="t('agentSecurityScans.tc260.platformCoverage')" :span="2">
                    <a-space wrap><a-tag color="green">{{ t('agentSecurityScans.tc260.statuses.verified') }} {{ tc260Profile.summary.verified }}</a-tag><a-tag color="orange">{{ t('agentSecurityScans.tc260.statuses.partial') }} {{ tc260Profile.summary.partial }}</a-tag><a-tag>{{ t('agentSecurityScans.tc260.statuses.uncovered') }} {{ tc260Profile.summary.uncovered }}</a-tag></a-space>
                  </a-descriptions-item>
                  <a-descriptions-item :label="t('agentSecurityScans.tc260.catalog')" :span="2">{{ t('agentSecurityScans.tc260.catalogSummary', { categories: tc260Profile.catalog.category_count, controls: tc260Profile.catalog.control_count }) }}</a-descriptions-item>
                </a-descriptions>
                <a-table class="tc260-table" :columns="tc260Columns" :data-source="tc260Profile.controls" :pagination="false" row-key="control_id" size="small" :scroll="{ x: 900 }">
                  <template #bodyCell="{ column, record }">
                    <template v-if="column.key === 'category'">{{ tc260CategoryLabel(record.category) }}</template>
                    <template v-else-if="column.key === 'title'">{{ tc260ControlLabel(record.title_code) }}</template>
                    <template v-else-if="column.key === 'coverage'"> <a-tag :color="tc260CoverageColor(record.coverage_status)">{{ tc260CoverageLabel(record.coverage_status) }}</a-tag></template>
                    <template v-else-if="column.key === 'assessment'"><a-tag>{{ t(`agentSecurityScans.tc260.assessmentStatuses.${record.target_assessment_status}`, record.target_assessment_status) }}</a-tag></template>
                    <template v-else-if="column.key === 'basis'"><span>{{ tc260BasisLabel(record) }}</span></template>
                  </template>
                </a-table>
              </template>
              <a-empty v-else :description="t('agentSecurityScans.tc260.legacyMissing')" />
            </a-tab-pane>
            <a-tab-pane key="cases" :tab="`${t('agentSecurityScans.detail.cases')} (${taskDetail.cases.length})`">
              <a-alert
                v-if="isMcpTaskDetail"
                class="modal-alert"
                type="info"
                show-icon
                :message="t('agentSecurityScans.detail.mcpMetadataBoundary')"
              />
              <a-alert v-else-if="isLlmTaskDetail" class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.detail.llmRedteamBoundary')" />
              <a-alert v-else-if="isInfrastructureTaskDetail" class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.detail.infrastructureBoundary')" />
              <a-descriptions v-if="isMcpTaskDetail" class="case-coverage-summary" bordered size="small" :column="{ xs: 2, sm: 3, md: 4 }">
                <a-descriptions-item :label="t('agentSecurityScans.detail.mcpCaseSummary.planned')">{{ mcpCaseSummary.planned }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.mcpCaseSummary.noRiskObserved')">{{ mcpCaseSummary.no_risk_observed }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.mcpCaseSummary.riskSignals')">{{ mcpCaseSummary.risk_signal_detected }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.mcpCaseSummary.falsePositive')">{{ mcpCaseSummary.false_positive }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.mcpCaseSummary.riskAccepted')">{{ mcpCaseSummary.risk_accepted }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.mcpCaseSummary.resolved')">{{ mcpCaseSummary.resolved }}</a-descriptions-item>
                <a-descriptions-item :label="t('agentSecurityScans.detail.mcpCaseSummary.unverified')">{{ mcpCaseSummary.unverified }}</a-descriptions-item>
              </a-descriptions>
              <dl v-else class="case-coverage-summary case-statistics">
                <div><dt>{{ t(taskDetail.task.scan_kind === 'agent_risk_scan' ? 'agentSecurityScans.detail.caseSummary.planned' : 'agentSecurityScans.detail.caseSummary.plannedCases') }}</dt><dd>{{ caseCoverage.planned_cases }}</dd></div>
                <div><dt>{{ t('agentSecurityScans.detail.caseSummary.passed') }}</dt><dd>{{ caseCoverage.passed_cases }}</dd></div>
                <div><dt>{{ t('agentSecurityScans.detail.caseSummary.failed') }}</dt><dd>{{ caseCoverage.failed_cases }}</dd></div>
                <div><dt>{{ t('agentSecurityScans.detail.caseSummary.error') }}</dt><dd>{{ caseCoverage.error_cases }}</dd></div>
                <div><dt>{{ t('agentSecurityScans.detail.caseSummary.blocked') }}</dt><dd>{{ caseCoverage.blocked_cases }}</dd></div>
                <div><dt>{{ t('agentSecurityScans.detail.caseSummary.unverified') }}</dt><dd>{{ caseCoverage.unverified_cases }}</dd></div>
              </dl>
              <a-alert v-if="!isMcpTaskDetail && !isLlmTaskDetail && !isInfrastructureTaskDetail" class="modal-alert" type="info" show-icon :message="t('agentSecurityScans.detail.casePassedBoundary')" />
              <a-list :data-source="taskDetail.cases" item-layout="horizontal" class="case-list" :pagination="taskDetail.cases.length > 10 ? { pageSize: 10, showSizeChanger: false } : false">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta>
                      <template #title>
                        <div class="case-title-row"><strong>{{ caseTitle(item) }}</strong><a-tag :color="isMcpTaskDetail ? caseAssessmentColor(item.assessment_status) : caseStatusColor(item.status)">{{ isMcpTaskDetail ? caseAssessmentLabel(item.assessment_status) : caseLegacyStatusLabel(item.status) }}</a-tag></div>
                      </template>
                      <template #description>
                        <template v-if="isMcpTaskDetail">
                          <div>{{ t('agentSecurityScans.detail.mcpToolName') }}：{{ item.request_summary?.asset?.exposed_name || item.request_summary?.asset?.tool_name || item.title }}</div>
                          <div>{{ t('agentSecurityScans.detail.caseFindingCount', { value: item.finding_count ?? 0 }) }} · {{ t('agentSecurityScans.detail.activeFindingCount', { value: item.active_finding_count ?? 0 }) }}</div>
                          <div>{{ t('agentSecurityScans.detail.scanMode') }}：{{ scanModeLabel(item.scan_mode) }} · {{ t('agentSecurityScans.detail.mcpToolCalls', { value: item.tool_calls_performed ?? 0 }) }}</div>
                          <div class="muted">{{ t('agentSecurityScans.detail.mcpCaseBoundary') }}</div>
                        </template>
                        <template v-else>
                          <div v-if="item.request_summary?.stage_id" class="case-meta-line">{{ t('agentSecurityScans.detail.caseStage', { value: item.request_summary.stage_id }) }}</div>
                          <div>{{ t('agentSecurityScans.detail.caseCalls', { value: item.response_summary?.dialogue_calls ?? item.round_count ?? 0 }) }} · {{ t('agentSecurityScans.detail.caseFindingCount', { value: item.finding_count ?? item.response_summary?.finding_count ?? 0 }) }}</div>
                          <a-collapse v-if="caseHasDetails(item)" class="case-details" ghost>
                            <a-collapse-panel key="details" :header="t('agentSecurityScans.detail.caseDetails')">
                              <dl class="case-detail-grid">
                                <template v-if="item.request_summary?.prompt"><dt>{{ t('agentSecurityScans.detail.casePrompt') }}</dt><dd class="source-text">{{ item.request_summary.prompt }}</dd></template>
                                <template v-if="item.response_summary?.response"><dt>{{ t('agentSecurityScans.detail.caseResponse') }}</dt><dd class="source-text">{{ item.response_summary.response }}</dd></template>
                                <template v-if="item.response_summary?.evaluator_reason"><dt>{{ t('agentSecurityScans.detail.caseReason') }}</dt><dd>{{ item.response_summary.evaluator_reason }}</dd></template>
                              </dl>
                            </a-collapse-panel>
                          </a-collapse>
                        </template>
                        <div v-if="item.response_summary?.error_type || item.response_summary?.error_message" class="case-error">{{ t('agentSecurityScans.detail.caseError', { type: item.response_summary?.error_type || '—', message: item.response_summary?.error_message || '—' }) }}</div>
                      </template>
                    </a-list-item-meta>
                    <a-space v-if="isMcpTaskDetail" direction="vertical" align="end">
                      <a-tag :color="caseExecutionColor(item.execution_status)">{{ t('agentSecurityScans.detail.caseExecution', { value: caseExecutionLabel(item.execution_status) }) }}</a-tag>
                    </a-space>
                  </a-list-item>
                </template>
              </a-list>
            </a-tab-pane>
            <a-tab-pane key="findings" :tab="`${t('agentSecurityScans.detail.findings')} (${taskDetail.findings.length})`">
              <a-empty v-if="!taskDetail.findings.length" :description="t('agentSecurityScans.detail.noFindingsTitle')" />
              <a-collapse v-else class="report-findings">
                <a-collapse-panel v-for="item in taskDetail.findings" :key="item.finding_id">
                  <template #header><a-space wrap><a-tag :color="severityColor(item.severity)">{{ severityLabel(item.severity) }}</a-tag><span>{{ findingTitle(item) }}</span><a-tag v-for="code in item.risk_codes" :key="code" color="blue">{{ agenticRiskLabel(code, t, te) }}</a-tag></a-space></template>
                  <p>{{ findingDescription(item) }}</p>
                  <dl v-if="item.finding_code === 'llm_redteam.jailbreak_signal'" class="case-detail-grid">
                    <dt>{{ t('agentSecurityScans.detail.case') }}</dt><dd>{{ findingCase(item) ? caseTitle(findingCase(item)) : '—' }}</dd>
                    <dt>{{ t('agentSecurityScans.detail.testContext') }}</dt><dd>{{ item.evidence?.vulnerability || '—' }}</dd>
                    <template v-if="findingCase(item)?.response_summary?.evaluator_reason"><dt>{{ t('agentSecurityScans.detail.caseReason') }}</dt><dd class="source-text">{{ findingCase(item).response_summary.evaluator_reason }}</dd></template>
                  </dl>
                  <details class="report-evidence"><summary>{{ t('agentSecurityScans.detail.evidenceDetails') }}</summary>
                    <p class="mapping-version">{{ t('agentSecurityScans.findings.mappingVersion') }}: {{ item.risk_mapping?.mapping_version || t('agentSecurityScans.findings.legacyUnmapped') }}</p>
                    <p class="mapping-version">{{ t('agentSecurityScans.detail.decisionCriteriaVersion') }}: {{ item.decision_criteria_version || t('agentSecurityScans.detail.legacyUnversioned') }}</p>
                    <pre class="evidence-block">{{ prettyJson(item.evidence) }}</pre>
                  </details>
                </a-collapse-panel>
              </a-collapse>
            </a-tab-pane>
            <a-tab-pane key="artifacts" :tab="`${t('agentSecurityScans.detail.artifacts')} (${taskDetail.artifacts.length})`">
              <a-list :data-source="taskDetail.artifacts" class="artifact-list"><template #renderItem="{ item }"><a-list-item><template #actions><a-button v-if="item.content_available && canViewRaw" type="link" @click="viewArtifact(taskDetail.task.task_id, item)">{{ t('agentSecurityScans.detail.viewReport') }}</a-button></template><a-list-item-meta :title="artifactTitle(item)" :description="artifactSummary(item)" /></a-list-item></template></a-list>
            </a-tab-pane>
            <a-tab-pane v-if="taskDetail.task.scan_kind === 'dify_asset_inventory'" key="inventory" :tab="t('agentSecurityScans.inventory.tab')">
              <DifyAssetInventory :task-id="taskDetail.task.task_id" :can-admin="canAdmin" />
            </a-tab-pane>
          </a-tabs>
        </template>
      </a-spin>
    </a-drawer>

    <a-modal v-model:open="findingDetailOpen" :title="selectedFinding && findingTitle(selectedFinding)" width="760px" :footer="null">
      <a-descriptions v-if="selectedFinding" bordered :column="1" size="small">
        <a-descriptions-item :label="t('agentSecurityScans.findings.severity')"><a-tag :color="severityColor(selectedFinding.severity)">{{ severityLabel(selectedFinding.severity) }}</a-tag></a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.findings.status')">{{ findingStatusLabel(selectedFinding.status) }}</a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.findings.agenticRisks')"><a-space v-if="selectedFinding.risk_codes?.length" wrap><a-tag v-for="code in selectedFinding.risk_codes" :key="code" color="blue">{{ agenticRiskLabel(code, t, te) }}</a-tag></a-space><span v-else class="muted">{{ t('agentSecurityScans.findings.unmappedRisk') }}</span></a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.findings.mappingVersion')">{{ selectedFinding.risk_mapping?.mapping_version || t('agentSecurityScans.findings.legacyUnmapped') }}</a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.findings.traceability')">
          <div class="traceability-summary">
            <a-tag :color="selectedFindingTraceability.status === 'complete' ? 'green' : 'orange'">{{ t(`agentSecurityScans.findings.traceabilityStatuses.${selectedFindingTraceability.status}`) }}</a-tag>
            <span v-if="selectedFindingTraceability.status === 'incomplete'" class="muted">{{ t('agentSecurityScans.findings.missingParts') }}：{{ selectedFindingTraceability.missing.map(part => t(`agentSecurityScans.findings.traceabilityParts.${part}`)).join('、') }}</span>
          </div>
        </a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.findings.linkedCase')"><code v-if="selectedFindingTraceability.caseId">{{ selectedFindingTraceability.caseId }}</code><span v-else class="muted">—</span></a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.detail.decisionCriteriaVersion')"><code v-if="selectedFindingTraceability.decisionCriteriaVersion">{{ selectedFindingTraceability.decisionCriteriaVersion }}</code><span v-else class="muted">{{ t('agentSecurityScans.detail.legacyUnversioned') }}</span></a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.findings.evidenceSha256')"><code v-if="selectedFindingTraceability.evidenceSha256">{{ selectedFindingTraceability.evidenceSha256 }}</code><span v-else class="muted">—</span></a-descriptions-item>
        <a-descriptions-item v-if="selectedFindingTraceability.traceId && selectedFindingTraceability.eventId" :label="t('agentSecurityScans.findings.runtimeEvidence')">
          <div class="trace-evidence-link">
            <div><span>{{ t('agentSecurityScans.findings.exactEvent') }}</span><code>{{ selectedFindingTraceability.traceId }}</code><code>{{ selectedFindingTraceability.eventId }}</code></div>
            <a-button type="link" size="small" @click="openFindingTrace(selectedFinding)">{{ t('agentSecurityScans.findings.openTrace') }}</a-button>
          </div>
        </a-descriptions-item>
        <a-descriptions-item v-else :label="t('agentSecurityScans.findings.runtimeEvidence')"><span class="muted">{{ t('agentSecurityScans.findings.noRuntimeEvidence') }}</span></a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.findings.descriptionLabel')">{{ findingDescription(selectedFinding) }}</a-descriptions-item>
        <a-descriptions-item :label="t('agentSecurityScans.findings.evidence')"><pre class="evidence-block">{{ prettyJson(selectedFinding.evidence) }}</pre></a-descriptions-item>
      </a-descriptions>
    </a-modal>

    <a-modal v-model:open="artifactModalOpen" :title="t('agentSecurityScans.detail.artifactReport')" width="min(980px, 96vw)" :footer="null">
      <a-alert class="modal-alert" type="warning" show-icon :message="t('agentSecurityScans.detail.rawWarning')" />
      <a-alert v-if="artifactError" class="modal-alert" type="error" show-icon :message="artifactError">
        <template #action><a-button size="small" :disabled="artifactLoading" @click="retryArtifact">{{ t('agentSecurityScans.detail.retryArtifact') }}</a-button></template>
      </a-alert>
      <a-spin :spinning="artifactLoading">
        <a-tabs v-model:activeKey="artifactTab">
          <a-tab-pane key="summary" :tab="t('agentSecurityScans.detail.readableReport')">
            <div v-if="artifactRows.length" class="artifact-overview">
              <span>{{ t('agentSecurityScans.detail.artifactRecorded', { value: artifactOverview.recorded }) }}</span>
              <span>{{ t('agentSecurityScans.detail.artifactSafe', { value: artifactOverview.safe }) }}</span>
              <span>{{ t('agentSecurityScans.detail.artifactRisk', { value: artifactOverview.risk }) }}</span>
              <span v-if="artifactOverview.evaluated">{{ t('agentSecurityScans.detail.artifactRiskRate', { value: artifactOverview.rate }) }}</span>
            </div>
            <a-empty v-if="!artifactRows.length && !artifactError && !artifactLoading" :description="t('agentSecurityScans.detail.noReadableReport')" />
            <a-list v-else-if="artifactRows.length" class="artifact-report-list" :data-source="artifactRows" :pagination="{ pageSize: 10, showSizeChanger: false }">
              <template #renderItem="{ item }">
                <a-list-item>
                  <a-list-item-meta :title="artifactRowTitle(item)">
                    <template #description>
                      <div class="artifact-row-meta"><a-tag :color="artifactStatusColor(item.status)">{{ artifactStatusLabel(item.status) }}</a-tag></div>
                      <a-collapse ghost>
                        <a-collapse-panel key="source" :header="t('agentSecurityScans.detail.caseDetails')">
                          <dl class="case-detail-grid">
                            <template v-if="item.originalInput && item.originalInput !== item.input"><dt>{{ t('agentSecurityScans.detail.originalPrompt') }}</dt><dd class="source-text">{{ item.originalInput }}</dd></template>
                            <template v-if="item.input"><dt>{{ t('agentSecurityScans.detail.casePrompt') }}</dt><dd class="source-text">{{ item.input }}</dd></template>
                            <template v-if="item.output"><dt>{{ t('agentSecurityScans.detail.caseResponse') }}</dt><dd class="source-text">{{ item.output }}</dd></template>
                            <template v-if="item.reason"><dt>{{ t('agentSecurityScans.detail.caseReason') }}</dt><dd class="source-text">{{ item.reason }}</dd></template>
                          </dl>
                        </a-collapse-panel>
                      </a-collapse>
                    </template>
                  </a-list-item-meta>
                </a-list-item>
              </template>
            </a-list>
          </a-tab-pane>
          <a-tab-pane key="raw" :tab="t('agentSecurityScans.detail.rawArtifact')"><pre class="raw-block">{{ artifactContent }}</pre></a-tab-pane>
        </a-tabs>
      </a-spin>
    </a-modal>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { agenticRiskLabel } from '../agenticRiskTaxonomy'
import { normalizeFindingTraceability } from '../securityFindingTraceability'
import { parseRedteamArtifact, summarizeCaseCoverage, summarizeRedteamRows } from '../securityScanReport'
import DifyAssetInventory from './components/DifyAssetInventory.vue'
import RedteamDatasetPicker from './components/RedteamDatasetPicker.vue'
import {
  activateSecurityTaskKillSwitch,
  cancelSecurityTask,
  compareSecurityTasks,
  createSecurityPolicy,
  createSecurityScanApproval,
  createSecurityTarget,
  createSecurityTask,
  exportSecurityTask,
  getDifyMcpBindingOptions,
  getMe,
  getSecurityArtifactContent,
  getSecurityFinding,
  getSecurityTask,
  listMcpGateways,
  listModelEndpoints,
  getSecurityRedteamOptions,
  listSecurityPolicies,
  listSecurityScanApprovals,
  listSecurityTargets,
  listSecurityTaskFindings,
  listSecurityTasks,
  previewSecurityTask,
  setSecurityTargetCredential,
  updateSecurityTargetCredentialStatus,
  updateSecurityFinding,
  updateSecurityPolicy,
  updateSecurityTarget,
} from '../api'
import { formatDateTime } from '../utils/format'

const { t, te, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const loading = ref(true)
const refreshing = ref(false)
const loadError = ref('')
const activeStage = ref('targets')
const currentUser = ref(null)
const targets = ref([])
const policies = ref([])
const scanApprovals = ref([])
const tasks = ref([])
const findings = ref([])
const mcpGateways = ref([])
const modelEndpoints = ref([])
const difyMcpBindingsLoading = ref(false)
const difyMcpBindingOptions = ref({ snapshot_id: null, providers: [], servers: [], summary: {} })
const targetSearch = ref('')
const taskStatusFilter = ref('all')
const taskTargetFilter = ref(undefined)
const taskKindFilter = ref(undefined)
const findingTaskId = ref(undefined)
const findingsLoading = ref(false)

const assetTypes = ['agent', 'mcp', 'llm', 'ai_infrastructure']
const connectorTypesByAsset = {
  agent: ['dify', 'coze', 'openai_compatible', 'custom_http', 'websocket'],
  mcp: ['mcp_gateway'],
  llm: ['openai_compatible'],
  ai_infrastructure: ['network_endpoint'],
}
const credentialTypes = ['bearer', 'api_key', 'basic', 'custom']
const scanKinds = ['control_plane_validation', 'agent_risk_scan', 'dify_asset_inventory', 'mcp_risk_scan', 'llm_redteam_scan', 'ai_infrastructure_vulnerability_scan']
const taskStatuses = ['pending', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out', 'blocked']
const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled', 'timed_out', 'blocked'])
const executionModes = ['passive', 'read_only', 'active_safe', 'active_full']
const securityEnvironments = ['sandbox', 'test', 'staging', 'production']
const securityCapabilities = ['conversation', 'multi_turn', 'tool_read', 'tool_write', 'network_egress', 'file_read', 'file_write', 'code_execution', 'persistent_memory']
const severityOrder = ['critical', 'high', 'medium', 'low', 'info']
const findingStatuses = ['open', 'accepted', 'resolved', 'false_positive']
const agentScanSkills = ['data-leakage-detection', 'tool-abuse-detection', 'indirect-injection-detection', 'authorization-bypass-detection', 'web-exfiltration-detection', 'agentic-supply-chain-detection', 'unexpected-code-execution-detection', 'inter-agent-comm-security-detection', 'cascading-failure-detection', 'human-agent-trust-exploit-detection']
const llmDatasets = ref([])
const evaluationModels = ref([])
const redteamOptionsLoading = ref(false)
const llmTechniques = ['Raw', 'BaseEncoding', 'Leetspeak', 'PromptInjection', 'Roleplay', 'ROTEncoding', 'SystemOverride']
const tablePagination = { pageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] }

const canAdmin = computed(() => ['admin', 'super_admin'].includes(currentUser.value?.role))
const intentInferenceModels = computed(() => modelEndpoints.value.filter(item => item.enabled))
const canViewRaw = computed(() => ['admin', 'super_admin', 'security_auditor'].includes(currentUser.value?.role))
const activeTargets = computed(() => targets.value.filter(item => item.status === 'active'))
const enabledPolicies = computed(() => policies.value.filter(item => item.enabled))
const policyCompatibleWithTarget = (policy, target) => policy.environment === target?.environment && (policy.allowed_capabilities || []).every(capability => (target.allowed_capabilities || []).includes(capability))
const canStartScan = computed(() => activeTargets.value.some(target => enabledPolicies.value.some(policy => policyCompatibleWithTarget(policy, target))))
const reportTasks = computed(() => tasks.value.filter(item => terminalStatuses.has(item.status)))
const tc260Profile = computed(() => taskDetail.value?.report_contract?.standards?.tc260 || null)
const filteredTargets = computed(() => {
  const query = targetSearch.value.trim().toLowerCase()
  if (!query) return targets.value
  return targets.value.filter(item => [item.name, item.target_id, item.target_type, item.environment, item.endpoint_url].some(value => String(value || '').toLowerCase().includes(query)))
})
const filteredTasks = computed(() => tasks.value.filter(item =>
  (taskStatusFilter.value === 'all' || item.status === taskStatusFilter.value)
  && (!taskTargetFilter.value || item.target_id === taskTargetFilter.value)
  && (!taskKindFilter.value || item.scan_kind === taskKindFilter.value)))
const severityCounts = computed(() => findings.value.reduce((counts, item) => ({ ...counts, [item.severity]: (counts[item.severity] || 0) + 1 }), {}))
const stageItems = computed(() => [
  { key: 'targets', label: t('agentSecurityScans.pipeline.targets'), description: t('agentSecurityScans.pipeline.targetsHint'), count: targets.value.length },
  { key: 'policies', label: t('agentSecurityScans.pipeline.policies'), description: t('agentSecurityScans.pipeline.policiesHint'), count: enabledPolicies.value.length },
  { key: 'tasks', label: t('agentSecurityScans.pipeline.tasks'), description: t('agentSecurityScans.pipeline.tasksHint'), count: tasks.value.length },
  { key: 'findings', label: t('agentSecurityScans.pipeline.findings'), description: t('agentSecurityScans.pipeline.findingsHint'), count: findingTaskId.value ? findings.value.length : '—' },
  { key: 'reports', label: t('agentSecurityScans.pipeline.reports'), description: t('agentSecurityScans.pipeline.reportsHint'), count: reportTasks.value.length },
])

const targetColumns = computed(() => [
  { title: t('agentSecurityScans.targets.name'), key: 'name', width: 160, ellipsis: true }, { title: t('agentSecurityScans.targets.assetType'), key: 'target_type', width: 180 }, { title: t('agentSecurityScans.environment'), key: 'environment', width: 120 }, { title: t('agentSecurityScans.allowedCapabilities'), key: 'allowed_capabilities', width: 120 }, { title: t('agentSecurityScans.targets.endpoint'), key: 'endpoint_url', width: 250 }, { title: t('agentSecurityScans.status'), key: 'status', width: 120 }, { title: t('agentSecurityScans.targets.credential'), key: 'credential', width: 150, ellipsis: true }, { title: t('agentSecurityScans.updatedAt'), key: 'updated_at', width: 180 }, { title: t('agentSecurityScans.actions'), key: 'actions', width: 210, fixed: 'right' },
])
const policyColumns = computed(() => [
  { title: t('agentSecurityScans.policies.name'), key: 'name', width: 160, ellipsis: true }, { title: t('agentSecurityScans.environment'), key: 'environment', width: 120 }, { title: t('agentSecurityScans.policies.mode'), key: 'execution_mode', width: 140 }, { title: t('agentSecurityScans.allowedCapabilities'), key: 'allowed_capabilities', width: 120 }, { title: t('agentSecurityScans.policies.productionControls'), key: 'production_controls', width: 250 }, { title: t('agentSecurityScans.policies.budget'), key: 'budget', width: 220 }, { title: t('agentSecurityScans.policies.network'), key: 'network', width: 250 }, { title: t('agentSecurityScans.status'), key: 'enabled', width: 110 }, { title: t('agentSecurityScans.actions'), key: 'actions', width: 160, fixed: 'right' },
])
const taskColumns = computed(() => [
  { title: t('agentSecurityScans.detail.task'), key: 'task_id', width: 160, ellipsis: true }, { title: t('agentSecurityScans.tasks.target'), key: 'target_id', width: 170 }, { title: t('agentSecurityScans.tasks.kind'), key: 'scan_kind', width: 210 }, { title: t('agentSecurityScans.status'), key: 'status', width: 120 }, { title: t('agentSecurityScans.tasks.usage'), key: 'progress', width: 150 }, { title: t('agentSecurityScans.createdAt'), key: 'created_at', width: 180 }, { title: t('agentSecurityScans.actions'), key: 'actions', width: 240, fixed: 'right' },
])
const findingColumns = computed(() => [
  { title: t('agentSecurityScans.findings.severity'), key: 'severity', width: 110 }, { title: t('agentSecurityScans.findings.finding'), key: 'title', width: 300 }, { title: t('agentSecurityScans.findings.status'), key: 'status', width: 130 }, { title: t('agentSecurityScans.findings.source'), dataIndex: 'source', key: 'source', width: 160 }, { title: t('agentSecurityScans.findings.confidence'), key: 'confidence', width: 100 }, { title: t('agentSecurityScans.actions'), key: 'actions', width: 140, fixed: 'right' },
])
const reportColumns = computed(() => [
  { title: t('agentSecurityScans.tasks.target'), key: 'target_id', width: 200 }, { title: t('agentSecurityScans.tasks.kind'), key: 'scan_kind', width: 190 }, { title: t('agentSecurityScans.status'), key: 'status', width: 120 }, { title: t('agentSecurityScans.reports.engine'), key: 'engine', width: 220 }, { title: t('agentSecurityScans.reports.completedAt'), key: 'completed_at', width: 190 }, { title: t('agentSecurityScans.actions'), key: 'actions', width: 260, fixed: 'right' },
])
const tc260Columns = computed(() => [
  { title: t('agentSecurityScans.tc260.controlId'), dataIndex: 'control_id', key: 'control_id', width: 90 },
  { title: t('agentSecurityScans.tc260.category'), key: 'category', width: 170 },
  { title: t('agentSecurityScans.tc260.control'), key: 'title', width: 220 },
  { title: t('agentSecurityScans.tc260.platformCoverage'), key: 'coverage', width: 130 },
  { title: t('agentSecurityScans.tc260.targetAssessment'), key: 'assessment', width: 120 },
  { title: t('agentSecurityScans.tc260.basis'), key: 'basis', width: 300 },
])

const comparisonModalOpen = ref(false)
const comparisonTask = ref(null)
const comparisonBaselineId = ref(undefined)
const comparisonResult = ref(null)
const comparisonLoading = ref(false)
const comparisonBaselines = computed(() => {
  if (!comparisonTask.value) return []
  const currentTime = parseUtc(comparisonTask.value.completed_at || comparisonTask.value.created_at)
  return reportTasks.value
    .filter(item => item.task_id !== comparisonTask.value.task_id && item.target_id === comparisonTask.value.target_id && item.scan_kind === comparisonTask.value.scan_kind && item.status === 'succeeded' && parseUtc(item.completed_at || item.created_at) <= currentTime)
    .sort((a, b) => parseUtc(b.completed_at || b.created_at) - parseUtc(a.completed_at || a.created_at))
})
const comparisonBuckets = computed(() => [
  { key: 'new', label: t('agentSecurityScans.comparison.new') },
  { key: 'unchanged', label: t('agentSecurityScans.comparison.unchanged') },
  { key: 'resolved', label: t('agentSecurityScans.comparison.resolved') },
  { key: 'unable_to_retest', label: t('agentSecurityScans.comparison.unable') },
])

const targetModalOpen = ref(false)
const editingTarget = ref(null)
const submittingTarget = ref(false)
const emptyDifyTargetFields = () => ({ dify_console_base_url: '', dify_workspace_id: '', dify_app_id: '', dify_workflow_id: '', dify_declared_intent: '', dify_owner: '', dify_owner_group: '', dify_redirect_hosts: '', dify_mcp_bindings: [], dify_knowledge_bindings_json: '[]' })
const targetForm = reactive({ name: '', asset_type: 'agent', connector_type: 'openai_compatible', environment: 'test', allowed_capabilities: [...securityCapabilities], endpoint_url: '', gateway_id: undefined, allowed_cidrs: '', config_json: '{}', allow_insecure_transport: false, ...emptyDifyTargetFields() })
const availableConnectorTypes = computed(() => connectorTypesByAsset[targetForm.asset_type] || [])
const mcpBindingStatus = binding => {
  if (!binding.server_id) return 'unbound'
  const server = difyMcpBindingOptions.value.servers.find(item => item.server_id === binding.server_id)
  if (!server || !binding.tool_names.every(toolName => server.tool_names.includes(toolName))) return 'configured_tool_not_discovered'
  return 'verified'
}
const difyMcpBindingSummary = computed(() => targetForm.dify_mcp_bindings.reduce(
  (summary, binding) => ({ ...summary, [mcpBindingStatus(binding)]: summary[mcpBindingStatus(binding)] + 1 }),
  { verified: 0, unbound: 0, configured_tool_not_discovered: 0 },
))
const mcpBindingStatusLabel = value => t(`agentSecurityScans.inventory.mcpBindingStatuses.${value}`)
const mcpBindingStatusColor = value => ({ verified: 'green', unbound: 'default', configured_tool_not_discovered: 'orange' }[value] || 'default')
const mcpServerMetaLabel = server => [
  t(`agentSecurityScans.inventory.mcpServerHealth.${server.health_status || 'unknown'}`, server.health_status),
  t('agentSecurityScans.inventory.mcpServerToolsListAt', { value: server.tools_list_at ? formatDateTime(server.tools_list_at) : t('agentSecurityScans.inventory.notCollected') }),
  t('agentSecurityScans.inventory.mcpServerToolCount', { value: server.tool_count }),
].join(' · ')
const mcpServerOptionLabel = server => `${server.name} ${server.slug} ${mcpServerMetaLabel(server)}`
const targetConfigHelp = computed(() => targetForm.asset_type === 'llm'
  ? t('agentSecurityScans.targets.llmConfigHelp')
  : targetForm.asset_type === 'ai_infrastructure'
    ? t('agentSecurityScans.targets.infrastructureConfigHelp')
    : t('agentSecurityScans.targets.configHelp'))
const credentialModalOpen = ref(false)
const credentialTarget = ref(null)
const submittingCredential = ref(false)
const credentialStatusUpdating = ref('')
const credentialForm = reactive({ credential_type: 'bearer', purpose: 'agent_runtime', secret: '' })
const availableCredentialPurposes = computed(() => credentialTarget.value?.connector_type === 'dify'
  ? ['dify_app_api', 'dify_console_api', 'dify_knowledge_api', 'mcp_discovery']
  : ['agent_runtime'])
const policyModalOpen = ref(false)
const editingPolicy = ref(null)
const submittingPolicy = ref(false)
const policyForm = reactive({ name: '', environment: 'test', execution_mode: 'read_only', allowed_capabilities: [...securityCapabilities], production_target_ids: [], maintenance_window_start: '', maintenance_window_end: '', dedicated_identity_ref: '', outbound_allowlist: '', max_rounds: 50, max_tokens: 200000, max_cost_microunits: 5000000, max_concurrent_requests: 2, max_duration_seconds: 1800, max_response_bytes: 10485760, max_retries: 2, task_timeout_seconds: 3600, lease_seconds: 60, retry_backoff_seconds: 5 })
const policyBudgetFields = [
  { key: 'max_rounds', label: 'agentSecurityScans.policies.maxRounds', min: 1, max: 10000 }, { key: 'max_tokens', label: 'agentSecurityScans.policies.maxTokens', min: 1, max: 100000000 }, { key: 'max_cost_microunits', label: 'agentSecurityScans.policies.maxCost', min: 0, max: 10000000000 }, { key: 'max_concurrent_requests', label: 'agentSecurityScans.policies.maxConcurrency', min: 1, max: 128 }, { key: 'max_duration_seconds', label: 'agentSecurityScans.policies.maxDuration', min: 1, max: 86400 }, { key: 'max_response_bytes', label: 'agentSecurityScans.policies.maxBytes', min: 1, max: 1073741824 }, { key: 'max_retries', label: 'agentSecurityScans.policies.maxRetries', min: 0, max: 10 }, { key: 'task_timeout_seconds', label: 'agentSecurityScans.policies.taskTimeout', min: 1, max: 604800 }, { key: 'lease_seconds', label: 'agentSecurityScans.policies.lease', min: 10, max: 600 }, { key: 'retry_backoff_seconds', label: 'agentSecurityScans.policies.retryBackoff', min: 0, max: 3600 },
]
const taskModalOpen = ref(false)
const submittingTask = ref(false)
const previewingTask = ref(false)
const taskPreview = ref(null)
const submittingApproval = ref(false)
const taskForm = reactive({ target_id: undefined, policy_id: undefined, approval_id: undefined, scan_kind: 'control_plane_validation', skills: [], prompt: '', conversation_mode: 'single_turn', continue_from_task_id: undefined, llm_input_mode: 'dataset', datasets: ['JailBench-Tiny'], num_prompts: 10, random_seed: 42, techniques: [], evaluation_model: undefined, http_authorized: false, private_network_authorized: false, scan_timeout_seconds: 30, scan_concurrency: 2, inventory_source: 'console_api', manual_dsl: '', include_prompt_text: false, infer_agent_intent: false, intent_inference_model: undefined, knowledge_content_authorized: false, max_knowledge_documents: 100, max_knowledge_segments: 1000, max_knowledge_bytes: 10485760 })
const killSwitchModalOpen = ref(false)
const killSwitchTask = ref(null)
const killSwitchReason = ref('')
const submittingKillSwitch = ref(false)
const selectedTaskTarget = computed(() => targets.value.find(item => item.target_id === taskForm.target_id))
const selectedTaskPolicy = computed(() => policies.value.find(item => item.policy_id === taskForm.policy_id))
const requiresProductionApproval = computed(() => selectedTaskTarget.value?.environment === 'production' && selectedTaskPolicy.value?.execution_mode === 'active_safe')
const availableApprovals = computed(() => scanApprovals.value.filter(item => item.target_id === taskForm.target_id && item.policy_id === taskForm.policy_id && item.status === 'approved' && parseUtc(item.maintenance_window_start) <= Date.now() && parseUtc(item.maintenance_window_end) > Date.now()))
const availablePolicies = computed(() => enabledPolicies.value.filter(policy => policyCompatibleWithTarget(policy, selectedTaskTarget.value)))
const scanKindsByAsset = { agent: ['control_plane_validation', 'agent_risk_scan'], mcp: ['mcp_risk_scan'], llm: ['llm_redteam_scan'], ai_infrastructure: ['ai_infrastructure_vulnerability_scan'] }
const availableScanKinds = computed(() => {
  const kinds = [...(scanKindsByAsset[selectedTaskTarget.value?.asset_type] || [])]
  if (selectedTaskTarget.value?.connector_type === 'dify') kinds.push('dify_asset_inventory')
  return kinds
})
const resumableTasks = computed(() => tasks.value.filter(item => item.target_id === taskForm.target_id && item.scan_kind === 'agent_risk_scan' && item.session_continuation_available))
const taskSafetyMessage = computed(() => ({
  mcp_risk_scan: t('agentSecurityScans.tasks.mcpSafety'),
  agent_risk_scan: t('agentSecurityScans.tasks.agentSafety'),
  llm_redteam_scan: t('agentSecurityScans.tasks.llmSafety'),
  ai_infrastructure_vulnerability_scan: t('agentSecurityScans.tasks.infrastructureSafety'),
  dify_asset_inventory: t('agentSecurityScans.inventory.taskSafety'),
}[taskForm.scan_kind] || t('agentSecurityScans.tasks.controlSafety')))
const previewCaseLabel = item => {
  const key = `agentSecurityScans.tasks.previewCases.${item.case_key}`
  if (te(key)) return t(key)
  if (String(item.case_key).startsWith('mcp_tool:')) return t('agentSecurityScans.tasks.mcpToolCase', { value: String(item.case_key).slice(9) })
  if (String(item.case_key).startsWith('llm-attack:')) return t('agentSecurityScans.tasks.llmAttackCase', { value: String(item.case_key).slice(11) })
  if (String(item.case_key).startsWith('infra-endpoint:')) return t('agentSecurityScans.tasks.infrastructureEndpointCase', { value: item.endpoint || String(item.case_key).slice(15) })
  return item.case_key
}
const previewLimitationLabel = value => t(`agentSecurityScans.tasks.previewLimitationsMap.${value}`, value)
const dispositionModalOpen = ref(false)
const dispositionFinding = ref(null)
const submittingDisposition = ref(false)
const dispositionForm = reactive({ status: 'open', comment: '' })
const detailDrawerOpen = ref(false)
const taskDetailLoading = ref(false)
const taskDetail = ref(null)
const taskHasNoFinalReport = computed(() => Boolean(
  taskDetail.value
  && taskDetail.value.task.status !== 'succeeded'
  && taskDetail.value.cases.length === 0
  && taskDetail.value.findings.length === 0
  && taskDetail.value.artifacts.length === 0))
const successfulTaskHasNoFindings = computed(() => Boolean(
  taskDetail.value
  && taskDetail.value.task.status === 'succeeded'
  && taskDetail.value.cases.length > 0
  && taskDetail.value.artifacts.length > 0
  && taskDetail.value.findings.length === 0))
const isMcpTaskDetail = computed(() => taskDetail.value?.task?.scan_kind === 'mcp_risk_scan')
const isLlmTaskDetail = computed(() => taskDetail.value?.task?.scan_kind === 'llm_redteam_scan')
const llmReportMetadata = computed(() => taskDetail.value?.artifacts?.find(item => item.artifact_type === 'aig-llm-redteam-report')?.metadata)
const isInfrastructureTaskDetail = computed(() => taskDetail.value?.task?.scan_kind === 'ai_infrastructure_vulnerability_scan')
const mcpCaseSummary = computed(() => {
  const cases = taskDetail.value?.cases || []
  const count = status => cases.filter(item => item.assessment_status === status).length
  return {
    planned: cases.length,
    no_risk_observed: count('no_risk_observed'),
    risk_signal_detected: count('risk_signal_detected'),
    false_positive: count('false_positive'),
    risk_accepted: count('risk_accepted'),
    resolved: count('resolved'),
    unverified: count('unverified'),
  }
})
const caseCoverage = computed(() => {
  return summarizeCaseCoverage({ task: taskDetail.value?.task, cases: taskDetail.value?.cases, artifacts: taskDetail.value?.artifacts })
})
const findingDetailOpen = ref(false)
const selectedFinding = ref(null)
const selectedFindingTraceability = computed(() => normalizeFindingTraceability(selectedFinding.value))
const artifactModalOpen = ref(false)
const artifactLoading = ref(false)
const artifactContent = ref('')
const artifactRows = ref([])
const artifactError = ref('')
const artifactTab = ref('summary')
const selectedArtifact = ref(null)
const artifactOverview = computed(() => summarizeRedteamRows(artifactRows.value))
const errorText = error => error.response?.data?.detail || error.message || t('agentSecurityScans.operationFailed')
const splitList = value => String(value || '').split(/[\n,]/).map(item => item.trim()).filter(Boolean)
const prettyJson = value => JSON.stringify(value ?? {}, null, 2)
const formatNumber = value => Number(value || 0).toLocaleString(locale.value)
const formatDuration = value => value >= 3600 ? `${Math.round(value / 360) / 10}h` : value >= 60 ? `${Math.round(value / 6) / 10}m` : `${value}s`
const formatBytes = value => { const size = Number(value || 0); if (size < 1024) return `${size} B`; if (size < 1048576) return `${(size / 1024).toFixed(1)} KiB`; return `${(size / 1048576).toFixed(1)} MiB` }
const parseUtc = value => Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(String(value || '')) ? value : `${value}Z`)
const toDateTimeLocal = value => value ? String(value).replace(/Z$/, '').slice(0, 16) : ''
const formatUtcDateTime = value => value ? `${new Intl.DateTimeFormat(locale.value, { timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(parseUtc(value)))} UTC` : '—'
const taskReasonKeys = {
  'agent_security.aig_model_not_found': 'aigModelNotFound',
  'agent_security.aig_model_auth_failed': 'aigModelAuthFailed',
  'agent_security.aig_model_rate_limited': 'aigModelRateLimited',
  'agent_security.aig_model_timeout': 'aigModelTimeout',
  'agent_security.aig_model_connection_failed': 'aigModelConnectionFailed',
  'agent_security.aig_model_initialization_failed': 'aigModelInitializationFailed',
  'agent_security.aig_scan_timeout': 'aigScanTimeout',
  'agent_security.aig_task_failed': 'aigTaskFailed',
  'agent_security.usage_not_monotonic': 'usageNotMonotonic',
  'agent_security.worker_lease_lost': 'workerLeaseLost',
  lease_expired_retry: 'leaseExpiredRetry',
  lease_expired_attempts_exhausted: 'leaseExpiredAttemptsExhausted',
  worker_requested_retry: 'workerRequestedRetry',
  'budget.max_tokens_exceeded': 'maxTokensExceeded',
  'dify_inventory.console_auth_failed': 'difyConsoleAuthFailed',
  'dify_inventory.console_forbidden': 'difyConsoleForbidden',
  'dify_inventory.app_not_found': 'difyAppNotFound',
  'dify_inventory.export_not_supported': 'difyExportNotSupported',
  'dify_inventory.response_too_large': 'difyResponseTooLarge',
  'dify_inventory.response_invalid': 'difyResponseInvalid',
  'dify_inventory.dsl_invalid': 'difyDslInvalid',
  'dify_inventory.upstream_unavailable': 'difyUpstreamUnavailable',
  'dify_inventory.console_credential_required': 'difyConsoleCredentialRequired',
  'dify_inventory.knowledge_credential_required': 'difyKnowledgeCredentialRequired',
  'dify_inventory.dataset_not_found': 'difyDatasetNotFound',
  'dify_inventory.dataset_forbidden': 'difyDatasetForbidden',
  'dify_inventory.dataset_reference_unmapped': 'difyDatasetReferenceUnmapped',
  'dify_inventory.dataset_reference_ambiguous': 'difyDatasetReferenceAmbiguous',
  'dify_inventory.draft_workflow_unavailable': 'difyDraftWorkflowUnavailable',
  'dify_inventory.draft_workflow_invalid': 'difyDraftWorkflowInvalid',
}
const taskReasonLabel = value => {
  if (!value) return '—'
  const key = taskReasonKeys[value]
  return key ? t(`agentSecurityScans.detail.reasons.${key}`) : value
}
const taskErrorExplanation = task => {
  const key = taskReasonKeys[task.error_code]
  return key ? t(`agentSecurityScans.detail.reasons.${key}`) : task.error_message || '—'
}
const findingTitle = finding => {
  if (finding?.finding_code === 'llm_redteam.jailbreak_signal') return t('agentSecurityScans.detail.findingTitles.jailbreakSignal')
  return finding?.title || finding?.finding_code || '—'
}
const findingCase = finding => taskDetail.value?.cases?.find(item => item.case_id === finding.case_id)
const findingDescription = finding => {
  if (finding?.finding_code === 'llm_redteam.jailbreak_signal') return t('agentSecurityScans.detail.findingDescriptions.jailbreakSignal')
  return finding?.description || '—'
}
const caseHasDetails = item => Boolean(item?.request_summary?.prompt || item?.response_summary?.response || item?.response_summary?.evaluator_reason)
const caseTitle = item => {
  if (item?.category !== 'llm_redteam_prompt') return item?.title || t('agentSecurityScans.detail.case')
  const match = String(item?.external_case_id || '').match(/:(\d+)$/)
  const number = match ? match[1] : (taskDetail.value?.cases.indexOf(item) ?? -1) + 1
  return [t('agentSecurityScans.detail.caseTitle', { value: number }), item?.request_summary?.vulnerability].filter(Boolean).join(' · ')
}
const artifactStatusLabel = value => ({ Safe: t('agentSecurityScans.detail.artifactStatuses.safe'), Jailbreak: t('agentSecurityScans.detail.artifactStatuses.jailbreak'), Exception: t('agentSecurityScans.detail.artifactStatuses.exception'), SimulationFailed: t('agentSecurityScans.detail.artifactStatuses.simulationFailed') }[value] || value || '—')
const artifactStatusColor = value => ({ Safe: 'green', Jailbreak: 'red', Exception: 'orange', SimulationFailed: 'default' }[value] || 'default')
const artifactRowTitle = item => `${t('agentSecurityScans.detail.artifactCase')} #${item._index} · ${item.vulnerability || '—'}`
const artifactTitle = item => t(`agentSecurityScans.detail.artifactTypes.${item.artifact_type}`, item.artifact_type || t('agentSecurityScans.detail.artifact'))
const artifactSummary = item => {
  const metadata = item.metadata || {}
  const parts = []
  if (metadata.planned_cases != null) parts.push(t('agentSecurityScans.detail.artifactPlanned', { value: metadata.planned_cases }))
  if (metadata.completed_evaluations != null) parts.push(t('agentSecurityScans.detail.artifactEvaluated', { value: metadata.completed_evaluations }))
  if (metadata.jailbreak_signals != null) parts.push(t('agentSecurityScans.detail.artifactRisks', { value: metadata.jailbreak_signals }))
  if (metadata.confirmed_vulnerabilities != null) parts.push(t('agentSecurityScans.detail.artifactVulnerabilities', { value: metadata.confirmed_vulnerabilities }))
  return parts.length ? parts.join(' · ') : `${formatBytes(item.size_bytes)} · ${t('agentSecurityScans.detail.sha256')} ${item.sha256}`
}
const targetName = id => targets.value.find(item => item.target_id === id)?.name || id
const policyName = id => policies.value.find(item => item.policy_id === id)?.name || id
const targetTypeLabel = (value) => {
  const key = `agentSecurityScans.targets.targetTypes.${value}`
  return te(key) ? t(key) : value
}
const assetTypeLabel = value => t(`agentSecurityScans.targets.assetTypes.${value}`, value)
const connectorTypeLabel = value => t(`agentSecurityScans.targets.connectorTypes.${value}`, value)
const targetCredentialLabel = record => record.target_type === 'mcp_gateway'
  ? t('agentSecurityScans.targets.notRequired')
  : record.credential_configured
    ? record.credential_masked
    : t('agentSecurityScans.targets.notConfigured')
const scanKindLabel = value => t(`agentSecurityScans.scanKinds.${value}`)
const statusLabel = value => t(`agentSecurityScans.statuses.${value}`, value)
const caseLegacyStatusLabel = value => t(`agentSecurityScans.detail.caseLegacyStatuses.${value}`, value)
const caseExecutionLabel = value => t(`agentSecurityScans.detail.caseExecutionStatuses.${value}`, value)
const caseAssessmentLabel = value => t(`agentSecurityScans.detail.caseAssessmentStatuses.${value}`, value)
const scanModeLabel = value => t(`agentSecurityScans.detail.scanModes.${value}`, value || '—')
const criteriaRuleLabel = value => t(`agentSecurityScans.detail.criteriaRules.${value}`, value)
const tc260CategoryLabel = value => t(`agentSecurityScans.tc260.categories.${value}`, value)
const tc260ControlLabel = value => t(`agentSecurityScans.tc260.controls.${value}`, value)
const tc260CoverageLabel = value => t(`agentSecurityScans.tc260.statuses.${value}`, value)
const tc260CoverageColor = value => ({ verified: 'green', partial: 'orange', uncovered: 'default' }[value] || 'default')
const tc260BasisLabel = record => {
  if (record.coverage_status === 'verified') return t('agentSecurityScans.tc260.verifiedBasis', { count: record.evidence_refs.length })
  if (record.coverage_status === 'partial') return t(`agentSecurityScans.tc260.limitations.${record.limitations[0]}`, record.limitations[0])
  return t(`agentSecurityScans.tc260.gaps.${record.gap_code}`, record.gap_code)
}
const severityLabel = value => t(`agentSecurityScans.severities.${value}`, value)
const findingStatusLabel = value => t(`agentSecurityScans.findingStatuses.${value}`, value)
const executionModeLabel = value => t(`agentSecurityScans.executionModes.${value}`, value)
const environmentLabel = value => t(`agentSecurityScans.environments.${value}`, value)
const capabilityLabel = value => t(`agentSecurityScans.capabilities.${value}`, value)
const statusColor = value => ({ pending: 'default', running: 'processing', succeeded: 'success', failed: 'error', cancelled: 'default', timed_out: 'orange', blocked: 'volcano', passed: 'green', error: 'red', unverified: 'default' }[value] || 'default')
const severityColor = value => ({ critical: 'red', high: 'volcano', medium: 'orange', low: 'gold', info: 'blue' }[value] || 'default')
const findingStatusColor = value => ({ open: 'red', accepted: 'orange', resolved: 'green', false_positive: 'default' }[value] || 'default')
const executionModeColor = value => ({ passive: 'default', read_only: 'blue', active_safe: 'gold', active_full: 'volcano' }[value] || 'default')
const environmentColor = value => ({ sandbox: 'cyan', test: 'blue', staging: 'gold', production: 'volcano' }[value] || 'default')
const caseStatusColor = value => ({ passed: 'green', failed: 'red', blocked: 'orange', error: 'red', unverified: 'default' }[value] || 'default')
const caseExecutionColor = value => ({ completed: 'green', error: 'red', blocked: 'orange', unverified: 'default' }[value] || 'default')
const caseAssessmentColor = value => ({ no_risk_observed: 'green', risk_signal_detected: 'orange', false_positive: 'default', risk_accepted: 'gold', resolved: 'blue', unverified: 'default' }[value] || 'default')

const loadCoreData = async () => {
  const [targetRows, policyRows, taskRows, approvalRows] = await Promise.all([listSecurityTargets(), listSecurityPolicies(), listSecurityTasks({ limit: 500 }), listSecurityScanApprovals({ limit: 500 })])
  targets.value = targetRows
  policies.value = policyRows
  tasks.value = taskRows
  scanApprovals.value = approvalRows
  if (findingTaskId.value && !tasks.value.some(item => item.task_id === findingTaskId.value)) { findingTaskId.value = undefined; findings.value = [] }
}
const refreshAll = async () => {
  refreshing.value = true; loadError.value = ''
  try { await loadCoreData(); if (findingTaskId.value) await loadFindings(findingTaskId.value) } catch (error) { loadError.value = errorText(error) } finally { refreshing.value = false }
}

const loadDifyMcpBindings = async record => {
  difyMcpBindingOptions.value = { snapshot_id: null, providers: [], servers: [], summary: {} }
  if (!record?.target_id || record.connector_type !== 'dify') return
  difyMcpBindingsLoading.value = true
  try {
    const options = await getDifyMcpBindingOptions(record.target_id)
    difyMcpBindingOptions.value = options
    targetForm.dify_mcp_bindings = options.providers.map(provider => ({
      provider_id: provider.provider_id,
      tool_names: [...(provider.tool_names || [])],
      server_id: provider.server_id || undefined,
    }))
  } catch (error) {
    message.error(errorText(error))
  } finally {
    difyMcpBindingsLoading.value = false
  }
}
const openTargetModal = record => {
  editingTarget.value = record || null
  const config = record?.config || {}
  Object.assign(targetForm, record ? {
    name: record.name, asset_type: record.asset_type, connector_type: record.connector_type, environment: record.environment,
    allowed_capabilities: [...(record.allowed_capabilities || [])], endpoint_url: record.endpoint_url,
    gateway_id: config.gateway_id, allowed_cidrs: (record.allowed_cidrs || []).join('\n'), config_json: prettyJson(config),
    allow_insecure_transport: Boolean(record.allow_insecure_transport),
    dify_console_base_url: config.console_base_url || '', dify_workspace_id: config.workspace_id || '',
    dify_app_id: config.app_id || '', dify_workflow_id: config.workflow_id || '',
    dify_declared_intent: config.declared_intent || '', dify_owner: config.platform_owner || '',
    dify_owner_group: config.platform_owner_group || '', dify_redirect_hosts: (config.allowed_redirect_hosts || []).join('\n'),
    dify_mcp_bindings: (config.mcp_bindings || []).map(item => ({ ...item, tool_names: [] })),
    dify_knowledge_bindings_json: prettyJson(config.knowledge_bindings || []),
  } : { name: '', asset_type: 'agent', connector_type: 'openai_compatible', environment: 'test', allowed_capabilities: [...securityCapabilities], endpoint_url: '', gateway_id: undefined, allowed_cidrs: '', config_json: '{}', allow_insecure_transport: false, ...emptyDifyTargetFields() })
  targetModalOpen.value = true
  loadDifyMcpBindings(record)
}
const handleAssetTypeChange = () => { targetForm.connector_type = connectorTypesByAsset[targetForm.asset_type][0]; handleConnectorTypeChange() }
const handleConnectorTypeChange = () => { targetForm.endpoint_url = ''; targetForm.gateway_id = undefined; targetForm.config_json = targetForm.asset_type === 'llm' ? prettyJson({ model: '', chat_completions_path: '/v1/chat/completions' }) : '{}'; Object.assign(targetForm, emptyDifyTargetFields()) }
const handleGatewayChange = id => { const gateway = mcpGateways.value.find(item => item.id === id); targetForm.endpoint_url = gateway ? `mcp-gateway://${gateway.slug}` : '' }
const saveTarget = async () => {
  if (submittingTarget.value) return
  if (!targetForm.name.trim() || (!targetForm.endpoint_url.trim() && targetForm.connector_type !== 'mcp_gateway')) return message.warning(t('agentSecurityScans.requiredFields'))
  let config
  try { config = targetForm.connector_type === 'mcp_gateway' ? { gateway_id: targetForm.gateway_id } : JSON.parse(targetForm.config_json || '{}') } catch { return message.error(t('agentSecurityScans.targets.invalidJson')) }
  if (targetForm.connector_type === 'dify') {
    if (!targetForm.dify_console_base_url.trim() || !targetForm.dify_workspace_id.trim() || !targetForm.dify_app_id.trim()) return message.warning(t('agentSecurityScans.requiredFields'))
    let knowledgeBindings
    try { knowledgeBindings = JSON.parse(targetForm.dify_knowledge_bindings_json || '[]') } catch { return message.error(t('agentSecurityScans.inventory.invalidKnowledgeBindings')) }
    if (!Array.isArray(knowledgeBindings)) return message.error(t('agentSecurityScans.inventory.invalidKnowledgeBindings'))
    const bindings = targetForm.dify_mcp_bindings
      .filter(item => item.server_id)
      .map(item => ({ provider_id: item.provider_id, server_id: item.server_id }))
    Object.assign(config, {
      console_base_url: targetForm.dify_console_base_url.trim(), workspace_id: targetForm.dify_workspace_id.trim(), app_id: targetForm.dify_app_id.trim(),
      mcp_bindings: bindings, knowledge_bindings: knowledgeBindings, allowed_redirect_hosts: splitList(targetForm.dify_redirect_hosts),
    })
    const optionalDifyConfig = { workflow_id: targetForm.dify_workflow_id, declared_intent: targetForm.dify_declared_intent, platform_owner: targetForm.dify_owner, platform_owner_group: targetForm.dify_owner_group }
    Object.entries(optionalDifyConfig).forEach(([key, value]) => { if (value.trim()) config[key] = value.trim(); else delete config[key] })
  }
  if (targetForm.connector_type === 'mcp_gateway' && !targetForm.gateway_id) return message.warning(t('agentSecurityScans.requiredFields'))
  const payload = { name: targetForm.name.trim(), asset_type: targetForm.asset_type, connector_type: targetForm.connector_type, environment: targetForm.environment, allowed_capabilities: [...targetForm.allowed_capabilities], endpoint_url: targetForm.endpoint_url.trim(), allowed_cidrs: splitList(targetForm.allowed_cidrs), allow_insecure_transport: Boolean(targetForm.allow_insecure_transport), config }
  submittingTarget.value = true
  try { if (editingTarget.value) await updateSecurityTarget(editingTarget.value.target_id, payload); else await createSecurityTarget(payload); targetModalOpen.value = false; await loadCoreData(); message.success(t('agentSecurityScans.saved')) } catch (error) { message.error(errorText(error)) } finally { submittingTarget.value = false }
}
const toggleTarget = async record => { try { await updateSecurityTarget(record.target_id, { status: record.status === 'active' ? 'disabled' : 'active' }); await loadCoreData(); message.success(t('agentSecurityScans.saved')) } catch (error) { message.error(errorText(error)) } }
const openCredentialModal = record => { credentialTarget.value = record; Object.assign(credentialForm, { credential_type: 'bearer', purpose: record.connector_type === 'dify' ? 'dify_app_api' : 'agent_runtime', secret: '' }); credentialModalOpen.value = true }
const saveCredential = async () => { if (submittingCredential.value || !credentialForm.secret) return; submittingCredential.value = true; try { await setSecurityTargetCredential(credentialTarget.value.target_id, { ...credentialForm }); credentialModalOpen.value = false; credentialForm.secret = ''; await loadCoreData(); message.success(t('agentSecurityScans.targets.credentialSaved')) } catch (error) { message.error(errorText(error)) } finally { submittingCredential.value = false } }
const toggleCredentialStatus = async item => {
  if (credentialStatusUpdating.value) return
  credentialStatusUpdating.value = item.credential_id
  try {
    const updated = await updateSecurityTargetCredentialStatus(item.credential_id, item.status === 'active' ? 'disabled' : 'active')
    Object.assign(item, updated)
    await loadCoreData()
    const refreshed = targets.value.find(target => target.target_id === credentialTarget.value?.target_id)
    if (refreshed) credentialTarget.value = refreshed
    message.success(t('agentSecurityScans.saved'))
  } catch (error) { message.error(errorText(error)) }
  finally { credentialStatusUpdating.value = '' }
}

const openPolicyModal = record => { editingPolicy.value = record || null; Object.assign(policyForm, record ? { ...record, allowed_capabilities: [...(record.allowed_capabilities || [])], production_target_ids: [...(record.production_target_ids || [])], maintenance_window_start: toDateTimeLocal(record.maintenance_window_start), maintenance_window_end: toDateTimeLocal(record.maintenance_window_end), dedicated_identity_ref: record.dedicated_identity_ref || '', outbound_allowlist: (record.outbound_allowlist || []).join('\n') } : { name: '', environment: 'test', execution_mode: 'read_only', allowed_capabilities: [...securityCapabilities], production_target_ids: [], maintenance_window_start: '', maintenance_window_end: '', dedicated_identity_ref: '', outbound_allowlist: '', max_rounds: 50, max_tokens: 200000, max_cost_microunits: 5000000, max_concurrent_requests: 2, max_duration_seconds: 1800, max_response_bytes: 10485760, max_retries: 2, task_timeout_seconds: 3600, lease_seconds: 60, retry_backoff_seconds: 5 }); policyModalOpen.value = true }
const handlePolicyEnvironmentChange = environment => { if (environment === 'production' && policyForm.execution_mode === 'active_full') policyForm.execution_mode = 'read_only' }
const policyPayload = () => ({
  name: policyForm.name.trim(),
  environment: policyForm.environment,
  execution_mode: policyForm.execution_mode,
  allowed_capabilities: [...policyForm.allowed_capabilities],
  production_target_ids: [...policyForm.production_target_ids],
  maintenance_window_start: policyForm.maintenance_window_start || null,
  maintenance_window_end: policyForm.maintenance_window_end || null,
  dedicated_identity_ref: policyForm.dedicated_identity_ref.trim() || null,
  outbound_allowlist: splitList(policyForm.outbound_allowlist),
  max_rounds: policyForm.max_rounds,
  max_tokens: policyForm.max_tokens,
  max_cost_microunits: policyForm.max_cost_microunits,
  max_concurrent_requests: policyForm.max_concurrent_requests,
  max_duration_seconds: policyForm.max_duration_seconds,
  max_response_bytes: policyForm.max_response_bytes,
  max_retries: policyForm.max_retries,
  task_timeout_seconds: policyForm.task_timeout_seconds,
  lease_seconds: policyForm.lease_seconds,
  retry_backoff_seconds: policyForm.retry_backoff_seconds,
})
const savePolicy = async () => { if (submittingPolicy.value || !policyForm.name.trim()) return message.warning(t('agentSecurityScans.requiredFields')); if (policyForm.environment === 'production' && policyForm.execution_mode === 'active_safe' && (!policyForm.production_target_ids.length || !policyForm.maintenance_window_start || !policyForm.maintenance_window_end || !policyForm.dedicated_identity_ref.trim())) return message.warning(t('agentSecurityScans.policies.productionControlsRequired')); submittingPolicy.value = true; const payload = policyPayload(); try { if (editingPolicy.value) { delete payload.name; await updateSecurityPolicy(editingPolicy.value.policy_id, payload) } else await createSecurityPolicy(payload); policyModalOpen.value = false; await loadCoreData(); message.success(t('agentSecurityScans.saved')) } catch (error) { message.error(errorText(error)) } finally { submittingPolicy.value = false } }
const togglePolicy = async record => { try { await updateSecurityPolicy(record.policy_id, { enabled: !record.enabled }); await loadCoreData(); message.success(t('agentSecurityScans.saved')) } catch (error) { message.error(errorText(error)) } }

const resetTaskOptions = () => Object.assign(taskForm, { skills: [], prompt: '', conversation_mode: 'single_turn', continue_from_task_id: undefined, llm_input_mode: 'dataset', datasets: ['JailBench-Tiny'], num_prompts: 10, random_seed: 42, techniques: [], evaluation_model: undefined, http_authorized: false, private_network_authorized: false, scan_timeout_seconds: 30, scan_concurrency: 2, inventory_source: 'console_api', manual_dsl: '', include_prompt_text: false, infer_agent_intent: false, intent_inference_model: undefined, knowledge_content_authorized: false, max_knowledge_documents: 100, max_knowledge_segments: 1000, max_knowledge_bytes: 10485760 })
const openTaskModal = async () => {
  const target = activeTargets.value.find(item => enabledPolicies.value.some(policy => policyCompatibleWithTarget(policy, item)))
  const policy = enabledPolicies.value.find(item => policyCompatibleWithTarget(item, target))
  Object.assign(taskForm, { target_id: target?.target_id, policy_id: policy?.policy_id, approval_id: undefined })
  resetTaskOptions()
  taskForm.scan_kind = (scanKindsByAsset[target?.asset_type] || [])[0]
  taskPreview.value = null
  taskModalOpen.value = true
  redteamOptionsLoading.value = true
  try {
    const options = await getSecurityRedteamOptions()
    llmDatasets.value = options.dataset_details
    evaluationModels.value = options.evaluation_models
  } catch (error) { message.error(errorText(error)) } finally { redteamOptionsLoading.value = false }
}
const handleTaskTargetChange = () => { resetTaskOptions(); taskForm.scan_kind = availableScanKinds.value[0]; taskForm.policy_id = availablePolicies.value[0]?.policy_id; taskForm.approval_id = undefined }
const handleTaskPolicyChange = () => { taskForm.approval_id = undefined; taskForm.continue_from_task_id = undefined }
const handleLlmInputModeChange = () => { taskForm.prompt = ''; taskForm.datasets = taskForm.llm_input_mode === 'dataset' ? ['JailBench-Tiny'] : [] }
const loadManualDsl = file => { file.text().then(text => { taskForm.manual_dsl = text }).catch(error => message.error(errorText(error))); return false }
const approveProductionScan = async () => {
  if (submittingApproval.value || !taskForm.target_id || !taskForm.policy_id) return
  submittingApproval.value = true
  try {
    const approval = await createSecurityScanApproval({ target_id: taskForm.target_id, policy_id: taskForm.policy_id })
    await loadCoreData()
    taskForm.approval_id = approval.approval_id
    message.success(t('agentSecurityScans.tasks.approvalCreated'))
  } catch (error) { message.error(errorText(error)) } finally { submittingApproval.value = false }
}
const taskPlanPayload = () => ({
  target_id: taskForm.target_id,
  policy_id: taskForm.policy_id,
  approval_id: requiresProductionApproval.value ? taskForm.approval_id : null,
  scan_kind: taskForm.scan_kind,
  language: locale.value === 'en-US' ? 'en' : 'zh',
  skills: taskForm.scan_kind === 'agent_risk_scan' ? taskForm.skills : [],
  prompt: ['agent_risk_scan', 'llm_redteam_scan'].includes(taskForm.scan_kind) ? taskForm.prompt : '',
  conversation_mode: taskForm.scan_kind === 'agent_risk_scan' ? taskForm.conversation_mode : 'single_turn',
  continue_from_task_id: taskForm.scan_kind === 'agent_risk_scan' ? taskForm.continue_from_task_id || null : null,
  reset_session: !taskForm.continue_from_task_id,
  datasets: taskForm.scan_kind === 'llm_redteam_scan' && taskForm.llm_input_mode === 'dataset' ? taskForm.datasets : [],
  num_prompts: taskForm.num_prompts,
  random_seed: taskForm.random_seed,
  techniques: taskForm.scan_kind === 'llm_redteam_scan' ? taskForm.techniques : [],
  evaluation_model: taskForm.scan_kind === 'llm_redteam_scan' ? taskForm.evaluation_model || null : null,
  http_authorized: taskForm.scan_kind === 'ai_infrastructure_vulnerability_scan' && taskForm.http_authorized,
  private_network_authorized: taskForm.scan_kind === 'ai_infrastructure_vulnerability_scan' && taskForm.private_network_authorized,
  scan_timeout_seconds: taskForm.scan_kind === 'ai_infrastructure_vulnerability_scan' ? taskForm.scan_timeout_seconds : null,
  scan_concurrency: taskForm.scan_kind === 'ai_infrastructure_vulnerability_scan' ? taskForm.scan_concurrency : null,
  inventory_source: taskForm.scan_kind === 'dify_asset_inventory' ? taskForm.inventory_source : 'console_api',
  manual_dsl: taskForm.scan_kind === 'dify_asset_inventory' && taskForm.inventory_source === 'manual_dsl' ? taskForm.manual_dsl : null,
  include_prompt_text: taskForm.scan_kind === 'dify_asset_inventory' && taskForm.include_prompt_text,
  infer_agent_intent: taskForm.scan_kind === 'dify_asset_inventory' && taskForm.infer_agent_intent,
  intent_inference_model: taskForm.scan_kind === 'dify_asset_inventory' && taskForm.infer_agent_intent ? taskForm.intent_inference_model || null : null,
  knowledge_content_authorized: taskForm.scan_kind === 'dify_asset_inventory' && taskForm.knowledge_content_authorized,
  max_knowledge_documents: taskForm.max_knowledge_documents,
  max_knowledge_segments: taskForm.max_knowledge_segments,
  max_knowledge_bytes: taskForm.max_knowledge_bytes,
})
const loadTaskPreview = async () => {
  if (previewingTask.value || submittingTask.value) return
  if (!taskForm.target_id || !taskForm.policy_id) return message.warning(t('agentSecurityScans.requiredFields'))
  if (taskForm.scan_kind === 'llm_redteam_scan' && taskForm.llm_input_mode === 'dataset' && !taskForm.datasets.length) return message.warning(t('agentSecurityScans.requiredFields'))
  if (requiresProductionApproval.value && !taskForm.approval_id) return message.warning(t('agentSecurityScans.tasks.productionApprovalRequired'))
  const payload = taskPlanPayload()
  const requestKey = JSON.stringify(payload)
  previewingTask.value = true
  taskPreview.value = null
  try {
    const preview = await previewSecurityTask(payload)
    if (requestKey === JSON.stringify(taskPlanPayload())) taskPreview.value = preview
  } catch (error) { message.error(errorText(error)) } finally { previewingTask.value = false }
}
const saveTask = async () => {
  if (submittingTask.value) return
  if (!taskPreview.value) return message.warning(t('agentSecurityScans.tasks.previewRequired'))
  submittingTask.value = true
  const payload = { ...taskPlanPayload(), preview_fingerprint: taskPreview.value.preview_fingerprint, idempotency_key: `web-${Date.now()}-${crypto.randomUUID().slice(0, 8)}` }
  try {
    const created = await createSecurityTask(payload)
    taskModalOpen.value = false
    await loadCoreData()
    activeStage.value = 'tasks'
    message.success(t('agentSecurityScans.tasks.created'))
    openTaskDetail(created.task_id)
  } catch (error) {
    if (error.response?.data?.error_code === 'agent_security.scan_preview_stale') taskPreview.value = null
    message.error(errorText(error))
  } finally { submittingTask.value = false }
}
const canCancel = record => currentUser.value?.role !== 'security_auditor' && ['pending', 'running'].includes(record.status)
const cancelTask = async record => { try { await cancelSecurityTask(record.task_id); await loadCoreData(); message.success(t('agentSecurityScans.tasks.cancelled')) } catch (error) { message.error(errorText(error)) } }
const canKill = record => canAdmin.value && ['pending', 'running'].includes(record.status) && !record.kill_switch_activated
const openKillSwitchModal = record => { killSwitchTask.value = record; killSwitchReason.value = ''; killSwitchModalOpen.value = true }
const activateKillSwitch = async () => {
  if (submittingKillSwitch.value || !killSwitchTask.value || !killSwitchReason.value.trim()) return
  submittingKillSwitch.value = true
  try {
    await activateSecurityTaskKillSwitch(killSwitchTask.value.task_id, { reason: killSwitchReason.value.trim() })
    killSwitchModalOpen.value = false
    await loadCoreData()
    if (taskDetail.value?.task?.task_id === killSwitchTask.value.task_id) await openTaskDetail(killSwitchTask.value.task_id)
    message.success(t('agentSecurityScans.tasks.killSwitchSubmitted'))
  } catch (error) { message.error(errorText(error)) } finally { submittingKillSwitch.value = false }
}

const loadFindings = async taskId => { if (!taskId) { findings.value = []; return } findingsLoading.value = true; try { findings.value = await listSecurityTaskFindings(taskId) } catch (error) { findings.value = []; message.error(errorText(error)) } finally { findingsLoading.value = false } }
const openFindingDetail = record => { selectedFinding.value = record; findingDetailOpen.value = true }
const openFindingTrace = finding => {
  const traceability = normalizeFindingTraceability(finding)
  if (!traceability.traceId || !traceability.eventId) return
  router.push({ name: 'runtime-traces', query: { trace_id: traceability.traceId, event_id: traceability.eventId } })
}
const routeValue = value => Array.isArray(value) ? value[0] : value
const openFindingFromRoute = async () => {
  const stage = routeValue(route.query.stage)
  const taskId = routeValue(route.query.task_id)
  const findingId = routeValue(route.query.finding_id)
  if (stage === 'findings' || taskId || findingId) activeStage.value = 'findings'
  if (findingId) {
    try {
      const finding = await getSecurityFinding(findingId)
      findingTaskId.value = finding.task_id
      await loadFindings(finding.task_id)
      openFindingDetail(findings.value.find(item => item.finding_id === findingId) || finding)
    } catch (error) { message.error(errorText(error)) }
  } else if (taskId) {
    findingTaskId.value = taskId
    await loadFindings(taskId)
  }
}
const openDispositionModal = record => { dispositionFinding.value = record; Object.assign(dispositionForm, { status: record.status, comment: record.disposition_comment || '' }); dispositionModalOpen.value = true }
const saveDisposition = async () => { if (submittingDisposition.value) return; submittingDisposition.value = true; try { await updateSecurityFinding(dispositionFinding.value.finding_id, { ...dispositionForm }); dispositionModalOpen.value = false; await loadFindings(findingTaskId.value); message.success(t('agentSecurityScans.saved')) } catch (error) { message.error(errorText(error)) } finally { submittingDisposition.value = false } }

const openTaskDetail = async taskId => { detailDrawerOpen.value = true; taskDetailLoading.value = true; taskDetail.value = null; try { taskDetail.value = await getSecurityTask(taskId) } catch (error) { message.error(errorText(error)) } finally { taskDetailLoading.value = false } }
const openComparison = record => { comparisonTask.value = record; comparisonResult.value = null; comparisonBaselineId.value = undefined; comparisonModalOpen.value = true; if (comparisonBaselines.value.length) comparisonBaselineId.value = comparisonBaselines.value[0].task_id }
const loadComparison = async () => { if (!comparisonTask.value || !comparisonBaselineId.value || comparisonLoading.value) return; comparisonLoading.value = true; comparisonResult.value = null; try { comparisonResult.value = await compareSecurityTasks(comparisonTask.value.task_id, comparisonBaselineId.value) } catch (error) { message.error(errorText(error)) } finally { comparisonLoading.value = false } }
const comparisonFinding = (item, bucket) => bucket === 'unable_to_retest' ? item.finding : item
const comparisonReasonLabel = reason => t(`agentSecurityScans.comparison.reasons.${reason}`)
const comparisonBucketColor = bucket => ({ new: 'red', unchanged: 'blue', resolved: 'green' }[bucket] || 'default')
const downloadReport = async record => { try { const payload = await exportSecurityTask(record.task_id); const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${record.task_id}-security-report.json`; link.click(); URL.revokeObjectURL(url); message.success(t('agentSecurityScans.reports.exported')) } catch (error) { message.error(errorText(error)) } }
const viewArtifact = async (taskId, artifact) => {
  if (artifactLoading.value) return
  artifactModalOpen.value = true
  artifactLoading.value = true
  artifactContent.value = ''
  artifactRows.value = []
  artifactError.value = ''
  artifactTab.value = 'summary'
  selectedArtifact.value = { taskId, artifact }
  try {
    const payload = await getSecurityArtifactContent(taskId, artifact.artifact_id)
    const result = parseRedteamArtifact(payload.content)
    artifactContent.value = result.parsed ? JSON.stringify(result.parsed, null, 2) : payload.content
    artifactRows.value = result.rows
  } catch (error) { artifactError.value = errorText(error); artifactContent.value = '' } finally { artifactLoading.value = false }
}
const retryArtifact = () => { if (selectedArtifact.value) viewArtifact(selectedArtifact.value.taskId, selectedArtifact.value.artifact) }

onMounted(async () => {
  try {
    const [userResult, gatewayResult] = await Promise.allSettled([getMe(), listMcpGateways()])
    if (userResult.status === 'fulfilled') currentUser.value = userResult.value
    if (gatewayResult.status === 'fulfilled') mcpGateways.value = gatewayResult.value
    if (canAdmin.value) {
      try { modelEndpoints.value = await listModelEndpoints() } catch { modelEndpoints.value = [] }
    }
    await loadCoreData()
    await openFindingFromRoute()
  } catch (error) { loadError.value = errorText(error) } finally { loading.value = false }
})
watch(() => [route.query.stage, route.query.task_id, route.query.finding_id], openFindingFromRoute)
watch(() => JSON.stringify(taskPlanPayload()), () => { taskPreview.value = null })
</script>

<style scoped>
.report-overview { padding: 0 0 20px; }
.report-overview h3 { margin: 0 0 14px; font-size: 16px; }
.report-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 0; }
.report-metrics dt { color: #5c6573; font-size: 13px; }
.report-metrics dd { margin: 4px 0 0; font-size: 26px; font-weight: 600; }
.report-metrics small { display: block; color: #5c6573; font-size: 12px; }
.report-metrics .risk-number { color: #b42318; }
.report-technical { margin-top: 16px; }
.case-statistics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; margin: 0 0 12px; padding: 12px 0; border-bottom: 1px solid #e2e8f0; }
.case-statistics dt { font-size: 12px; color: #5c6573; }
.case-statistics dd { margin: 4px 0 0; font-size: 20px; font-weight: 600; white-space: nowrap; }
@media (max-width: 900px) { .case-statistics { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 480px) { .case-statistics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.report-evidence { margin-top: 16px; color: #5c6573; }
.report-evidence summary { cursor: pointer; }
.report-findings { overflow-wrap: anywhere; }
@media (max-width: 640px) { .report-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.scan-page { max-width: 1480px; margin: 0 auto; color: #17233d; }
.comparison-controls { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; margin: 16px 0; }
.comparison-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.comparison-bucket { min-width: 0; padding: 12px; border: 1px solid #e3e9f2; border-radius: 10px; background: #fbfcfe; }
.comparison-bucket header { display: flex; justify-content: space-between; gap: 12px; padding-bottom: 8px; border-bottom: 1px solid #edf1f6; font-weight: 650; }
.comparison-bucket header strong { color: #1668dc; }
.comparison-empty, .comparison-limit { margin: 10px 0 0; }
.comparison-limit { color: #64748b; font-size: 12px; }
.ops-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 20px; padding: 8px 2px 0; }
.ops-header h1 { margin: 3px 0 6px; font-size: clamp(25px, 2.5vw, 34px); line-height: 1.15; letter-spacing: -0.025em; }
.ops-header p, .panel-heading p { margin: 0; color: #64748b; }
.eyebrow { color: #1668dc; font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
.scan-pipeline { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin-bottom: 18px; overflow: hidden; border: 1px solid #dce4ef; border-radius: 12px; background: #fff; box-shadow: 0 8px 28px rgba(30, 55, 90, .06); }
.pipeline-stage { position: relative; display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; align-items: center; gap: 9px; min-height: 84px; padding: 12px 14px; color: #4b5f7a; text-align: left; background: transparent; border: 0; border-right: 1px solid #e8edf4; cursor: pointer; transition: background .18s ease, color .18s ease; }
.pipeline-stage:last-child { border-right: 0; }
.pipeline-stage:hover { background: #f7faff; }
.pipeline-stage.active { color: #0f4fa8; background: #edf5ff; box-shadow: inset 0 -3px #1668dc; }
.stage-index { color: #8da0b9; font: 600 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
.stage-copy { display: grid; gap: 2px; min-width: 0; }
.stage-copy strong { font-size: 14px; }
.stage-copy small { color: #7a8ca5; font-size: 11px; line-height: 1.35; overflow-wrap: anywhere; }
.stage-count { display: grid; min-width: 27px; height: 27px; place-items: center; padding: 0 6px; color: #34506f; font: 700 12px/1 ui-monospace, SFMono-Regular, Menlo, monospace; background: #eef2f7; border-radius: 999px; }
.active .stage-count { color: #fff; background: #1668dc; }
.page-alert { margin-bottom: 16px; }
.trace-evidence-link { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.trace-evidence-link > div { position: relative; display: grid; min-width: 0; gap: 3px; padding-left: 18px; }
.trace-evidence-link > div::before { position: absolute; top: 4px; bottom: 4px; left: 3px; border-left: 1px dashed #8fa7cf; content: ''; }
.trace-evidence-link span { color: #4e6590; font-size: 11px; font-weight: 700; }
.trace-evidence-link code { overflow: hidden; color: #6e7c91; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.traceability-summary { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.stage-panel { min-height: 430px; padding: 22px; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 10px 32px rgba(30, 55, 90, .05); }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; }
.panel-heading h2 { margin: 0 0 5px; font-size: 20px; }
.search-control { width: 260px; }
.filter-row { display: flex; gap: 10px; margin-bottom: 16px; }
.filter-control { width: 190px; }
.task-picker { width: min(420px, 100%); }
.primary-cell, .finding-title { display: grid; min-width: 0; max-width: 100%; gap: 3px; }
.primary-cell strong, .primary-cell code { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.primary-cell code, .finding-title code, .detail-identity code, .id-link { color: #55708f; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
.target-classification { display: grid; min-width: 0; gap: 4px; }
.target-classification > span { min-width: 0; overflow: hidden; color: #64748b; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.endpoint-text { max-width: 230px; }
.credential-tag { display: block; width: 100%; max-width: 100%; overflow: hidden; box-sizing: border-box; }
.credential-tag__text { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.credential-inventory { display: grid; gap: 8px; padding: 12px; background: #f7f9fc; border: 1px solid #e1e7ef; }
.credential-inventory > div { display: grid; grid-template-columns: minmax(120px, .8fr) minmax(0, 1.2fr) auto auto; align-items: center; gap: 10px; min-width: 0; }
.credential-inventory code { min-width: 0; overflow: hidden; color: #60748c; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 640px) { .credential-inventory > div { grid-template-columns: minmax(0, 1fr) auto; }.credential-inventory code { grid-column: 1 / -1; grid-row: 2; } }
.manual-dsl { margin-top: 12px; }
.budget-stack, .usage-cell { display: grid; gap: 2px; color: #51647c; font-size: 12px; }
.case-list :deep(.ant-list-item) { align-items: flex-start; gap: 14px; }
.case-list :deep(.ant-list-item-meta) { min-width: 0; }
.case-title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: #20324a; }
.case-meta-line, .artifact-row-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.case-details { margin-top: 8px; }
.case-detail-grid { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 8px 12px; margin: 0; }
.case-detail-grid dt { color: #64748b; font-size: 12px; font-weight: 600; }
.case-detail-grid dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.source-text { white-space: pre-wrap; }
.artifact-report-list :deep(.ant-list-item-meta) { min-width: 0; }
.artifact-overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 14px; }
.artifact-overview span { padding: 10px 12px; color: #51647c; background: #f7f9fc; border: 1px solid #e2e8f0; border-radius: 6px; }
.artifact-reason { margin-top: 8px; color: #51647c; white-space: pre-wrap; overflow-wrap: anywhere; }
.muted { color: #93a1b3; }
.mapping-version { color: #64748b; font-size: 12px; }
.id-link { display: block; max-width: 100%; padding: 0; overflow: hidden; color: #1668dc; text-overflow: ellipsis; white-space: nowrap; background: none; border: 0; cursor: pointer; }
.severity-strip { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.severity-item { display: flex; align-items: center; gap: 8px; min-width: 118px; padding: 9px 12px; background: #f8fafc; border: 1px solid #e5eaf1; border-radius: 8px; }
.severity-item strong { margin-left: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.severity-dot { width: 8px; height: 8px; border-radius: 50%; }
.severity-critical { background: #cf1322; }.severity-high { background: #fa541c; }.severity-medium { background: #fa8c16; }.severity-low { background: #fadb14; }.severity-info { background: #1677ff; }
.number-input { width: 100%; }.code-input, .raw-block, .evidence-block { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.mcp-binding-editor { display: grid; gap: 10px; }
.mcp-binding-summary, .preview-binding-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.mcp-binding-summary span, .preview-binding-summary span { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 10px; color: #64748b; background: #f7f9fc; border: 1px solid #e2e8f0; border-radius: 6px; }
.mcp-binding-summary strong, .preview-binding-summary strong { color: #20324a; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.mcp-binding-list { display: grid; overflow: hidden; border: 1px solid #dfe7f0; border-radius: 7px; }
.mcp-binding-row { display: grid; grid-template-columns: minmax(220px, 1.2fr) minmax(260px, 1fr) auto; align-items: center; gap: 12px; min-width: 0; padding: 11px 12px; border-bottom: 1px solid #e8edf3; }
.mcp-binding-row:last-child { border-bottom: 0; }
.mcp-binding-provider { display: grid; min-width: 0; gap: 6px; }
.mcp-binding-provider code { overflow: hidden; color: #263b53; text-overflow: ellipsis; white-space: nowrap; }
.mcp-binding-provider > div { display: flex; flex-wrap: wrap; gap: 4px; }
.mcp-binding-provider :deep(.ant-tag) { margin: 0; }
.mcp-binding-provider small, .mcp-server-option small { color: #74859a; overflow-wrap: anywhere; }
.mcp-server-option { display: grid; min-width: 0; gap: 2px; padding: 3px 0; }
.mcp-server-option strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.approval-select { min-width: 0; flex: 1 1 auto; }
.field-help-error { margin-top: 6px; color: #cf1322; font-size: 12px; }
.modal-alert { margin-bottom: 16px; }
.tc260-table { margin-top: 16px; }
.kill-switch-form { margin-top: 16px; }
.task-preview { margin-top: 18px; padding: 16px; border: 1px solid #dbe5f1; border-radius: 10px; background: #f8fbff; }
.preview-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.preview-heading > div { display: grid; gap: 3px; }
.preview-heading span { color: #64748b; font-size: 12px; line-height: 1.5; }
.task-preview h4 { margin: 16px 0 8px; }
.preview-list { display: grid; max-height: 190px; overflow: auto; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; }
.preview-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 8px 10px; border-bottom: 1px solid #eef2f7; }
.preview-row:last-child { border-bottom: 0; }
.preview-row > span:first-child, .preview-row code { min-width: 0; overflow-wrap: anywhere; }
.preview-row > span:last-child { color: #64748b; font-size: 12px; text-align: right; }
.preview-budget { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.preview-budget span { display: grid; gap: 2px; padding: 9px 10px; color: #64748b; font-size: 11px; background: #fff; border: 1px solid #e2e8f0; border-radius: 7px; }
.preview-budget strong { color: #20324a; font: 600 13px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }
.preview-binding-summary { margin-top: 12px; }
.preview-limit { margin-top: 14px; }
.preview-empty { margin: 18px 0 4px; padding: 14px; border: 1px dashed #d7e0eb; border-radius: 9px; }
.detail-identity { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; padding: 12px 14px; background: #f4f7fb; border-left: 3px solid #1668dc; }
.detail-identity > div { display: grid; gap: 3px; min-width: 0; }
.detail-identity code { overflow-wrap: anywhere; }
.detail-identity > .ant-tag { flex-shrink: 0; margin-right: 0; }
.detail-identity span { color: #74869d; font-size: 12px; }
.evidence-block, .raw-block { max-width: 100%; margin: 0; padding: 14px; overflow: auto; color: #d7e4f5; font-size: 12px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; background: #182638; border-radius: 8px; }
.raw-block { min-height: 260px; max-height: 60vh; }
@media (max-width: 1050px) { .scan-pipeline { grid-template-columns: 1fr; }.pipeline-stage { min-height: 58px; border-right: 0; border-bottom: 1px solid #e8edf4; }.pipeline-stage:last-child { border-bottom: 0; }.pipeline-stage.active { box-shadow: inset 3px 0 #1668dc; } }
@media (max-width: 720px) {
  .ops-header, .panel-heading { align-items: stretch; flex-direction: column; }
  .ops-header :deep(.ant-space), .panel-heading :deep(.ant-space) { width: 100%; }
  .ops-header :deep(.ant-space-item), .panel-heading :deep(.ant-space-item) { flex: 1 1 auto; }
  .ops-header :deep(.ant-btn), .panel-heading :deep(.ant-btn) { width: 100%; }
  .stage-panel { min-width: 0; padding: 14px; overflow: hidden; }
  .filter-row { flex-direction: column; }
  .filter-control, .search-control { width: 100%; }
  .pipeline-stage { min-height: 66px; }
  .preview-budget { grid-template-columns: 1fr 1fr; }
  .mcp-binding-summary, .preview-binding-summary { grid-template-columns: 1fr; }
  .mcp-binding-row { grid-template-columns: 1fr; align-items: stretch; }
  .case-detail-grid { grid-template-columns: 1fr; gap: 3px; }
  .artifact-overview { grid-template-columns: 1fr 1fr; }
  .preview-heading { flex-direction: column; }
  .comparison-controls, .comparison-grid { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) { .pipeline-stage { transition: none; } }
</style>

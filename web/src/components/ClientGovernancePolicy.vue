<template>
  <a-modal :open="open" :title="t(impact ? 'clientGovernance.preview' : clientId ? 'clientPolicy.settings' : 'clientPolicy.globalSettings')" width="820px" class="client-governance-modal" :style="{ top: '24px', paddingBottom: 0, margin: '0 auto' }" :closable="!modalBusy" :mask-closable="!modalBusy" :keyboard="!modalBusy" :z-index="1010" @cancel="close">
    <nav v-if="!impact" class="settings-navigation" :aria-label="t('clientPolicy.navigation')">
      <button v-for="section in settingsSections" :key="section" type="button" :disabled="modalBusy || !!impact" :aria-pressed="settingsSection === section" @click="settingsSection = section">{{ section === 'risk' ? t('securityRules.title') : t(`clientPolicy.${section === 'audit' ? 'content' : section}`) }}</button>
    </nav>
    <a-tabs v-show="!impact && settingsSection === 'skills'" v-model:active-key="skillSection" size="small" :aria-label="t('clientPolicy.skills')">
      <a-tab-pane v-if="can('settings:view')" key="usage" :tab="t('clientPolicy.usageAudit')" :disabled="modalBusy || !!impact" />
      <a-tab-pane v-if="can('clients:view')" key="classification" :tab="t('clientPolicy.classification')" :disabled="modalBusy || !!impact" />
    </a-tabs>
    <AidrRedactionSettings v-if="open && auditVisited && can('settings:view')" v-show="settingsSection === 'audit'" :key="clientId" ref="auditSettings" :client-id="clientId" embedded external-actions />
    <AidrRedactionSettings v-if="open && skillsVisited && can('settings:view')" v-show="settingsSection === 'skills' && skillSection === 'usage'" :key="clientId" ref="skillAuditSettings" :client-id="clientId" embedded external-actions section="skill" @saved="emit('saved')" />
    <ClientDiscoveryConfig v-if="open && discoveryVisited && can('clients:view')" v-show="settingsSection === 'discovery'" :key="clientId" ref="discoverySettings" :client-id="clientId" @saved="emit('saved')" />
    <ClientSecurityRules v-if="open && riskVisited" v-show="settingsSection === 'risk'" :key="clientId" ref="riskSettings" :client-id="clientId" :active="settingsSection === 'risk'" @saved="emit('saved')" @global="emit('global-risk')" @configure="settingsSection = 'runtime'" />
    <a-spin v-if="can('clients:view')" v-show="activeTab === 'integration'" :spinning="loading">
      <a-alert v-if="policyError" type="error" show-icon :message="t('clientGovernance.policyLoadFailed')" :description="policyError"><template #action><a-button :disabled="loading" @click="load">{{ t('clientGovernance.retryLoad') }}</a-button></template></a-alert>
      <a-alert v-if="gatewayError" type="warning" show-icon :message="t('clientGovernance.gatewayLoadFailed')" :description="gatewayError"><template #action><a-button :disabled="loading" @click="load">{{ t('clientGovernance.retryLoad') }}</a-button></template></a-alert>
      <template v-if="policy">
        <a-alert v-if="!editable && !gatewayError && !policyError" type="warning" :message="t(policy.supported ? 'clientGovernance.readonly' : 'clientGovernance.upgrade')" />
        <a-alert v-if="!impact && clientId && policy.advanced_supported === false" type="warning" show-icon :message="t('clientGovernance.capabilityAvailable')" />
        <a-form v-if="!impact" layout="vertical" class="policy-form">
          <p v-if="settingsSection === 'skills'" class="settings-description">{{ t('clientPolicy.classificationHelp') }}</p>
          <section v-show="settingsSection === 'desktop'" class="policy-group">
            <p class="settings-description">{{ t('clientGovernance.desktop.description') }}</p>
            <a-alert v-if="clientId" :type="policy.desktop_menu_sync_status === 'synced' ? 'success' : 'info'" show-icon :message="t(`clientGovernance.desktop.${policy.desktop_menu_sync_status || 'unsupported'}`)" :description="t('clientGovernance.desktop.syncHint')" />
            <div v-if="clientId" class="settings-toolbar">
              <span v-if="policy.desktop_menu_reported_at">{{ t('clientGovernance.desktop.reportedAt') }}: {{ new Date(policy.desktop_menu_reported_at + (/[Z+]/.test(policy.desktop_menu_reported_at) ? '' : 'Z')).toLocaleString() }}</span>
              <a-button :disabled="!editable || busy" @click="desktopMenus = {}">{{ t('clientGovernance.desktop.reset') }}</a-button>
            </div>
            <p>{{ t('clientGovernance.desktop.connect') }}: {{ t('clientGovernance.desktop.fixed') }}</p>
            <div class="group-rules">
              <a-form-item v-for="menu in menuKeys" :key="menu" :label="t(`clientGovernance.desktop.${menu}`)">
                <a-select v-if="clientId" :value="Object.hasOwn(desktopMenus, menu) ? (desktopMenus[menu] ? 'show' : 'hide') : 'inherit'" :disabled="!editable || busy" @change="value => setDesktopMenu(menu, value)">
                  <a-select-option v-for="option in ['inherit', 'show', 'hide']" :key="option" :value="option">{{ t(`clientGovernance.desktop.${option}`) }}</a-select-option>
                </a-select>
                <a-switch v-else v-model:checked="desktopMenus[menu]" :disabled="!editable || busy" />
                <div class="effective">{{ t('clientGovernance.desktop.saved') }}: {{ t(policy.desktop_menu_visibility?.[menu] === false ? 'clientGovernance.desktop.hide' : 'clientGovernance.desktop.show') }} · {{ t(policy.desktop_menu_sources?.[menu] === 'client' ? 'clientGovernance.desktop.client' : 'clientGovernance.desktop.global') }}</div>
              </a-form-item>
            </div>
          </section>
          <section v-show="settingsSection === 'runtime'" class="policy-group">
            <a-checkbox v-if="clientId && policy.runtime_channels_protocol === 3" v-model:checked="inheritRuntime" :disabled="!editable || busy">{{ t('clientGovernance.inherit') }}</a-checkbox>
            <p v-else-if="clientId">{{ t('clientGovernance.runtime.inherited') }}</p>
            <div class="group-rules">
              <a-form-item class="runtime-master" :label="t('clientGovernance.runtime.enabled')" :tooltip="t('clientGovernance.runtime.pauseHint')"><a-switch v-model:checked="runtimeGovernance.enabled" :disabled="runtimeDisabled" /></a-form-item>
              <a-alert v-if="!runtimeGovernance.enabled" class="runtime-off-hint" type="warning" show-icon :message="t('clientGovernance.runtime.disabledHint')" />
              <a-form-item v-if="policy.runtime_channels_protocol === 3" :label="t('clientGovernance.runtime.channels')" :tooltip="t('clientGovernance.runtime.channelHint')">
                <a-space wrap><a-checkbox v-for="name in ['logs', 'hooks', 'system']" :key="name" v-model:checked="runtimeGovernance.channels[name]" :disabled="runtimeConfigDisabled">{{ t(`clientGovernance.runtime.channel_${name}`) }}</a-checkbox></a-space>
              </a-form-item>
              <a-form-item v-for="channel in ['hooks', 'system']" :key="channel" :label="t(`clientGovernance.runtime.mode_${channel}`)" :tooltip="t(`clientGovernance.runtime.mode_${channel}_hint`)">
                <a-select :value="runtimeGovernance.modes?.[channel] || 'legacy'" :disabled="runtimeConfigDisabled" @change="value => setMode(channel, value)">
                  <a-select-option v-if="!runtimeGovernance.modes?.[channel]" value="legacy">{{ t('clientGovernance.runtime.mode_legacy') }}</a-select-option>
                  <a-select-option v-for="mode in ['audit','intercept']" :key="mode" :value="mode">{{ t(`clientGovernance.runtime.mode_${mode}`) }}</a-select-option>
                </a-select>
              </a-form-item>
              <a-form-item :label="t('clientGovernance.runtime.logSources')" :tooltip="t('clientGovernance.runtime.productHint')">
                <a-select :value="selectedProductGroups(runtimeGovernance.log_sources || ['claude', 'codex'])" mode="multiple" :disabled="runtimeConfigDisabled" @change="setLogProducts"><a-select-option v-for="product in logSourceOptions" :key="product.id" :value="product.id">{{ product.name }}</a-select-option></a-select>
              </a-form-item>
              <a-form-item :label="t('clientGovernance.runtime.userEnrollment')" :tooltip="t('clientGovernance.runtime.userEnrollmentHint')">
                <a-switch v-model:checked="runtimeGovernance.allow_user_enrollment" :disabled="runtimeConfigDisabled" />
              </a-form-item>
              <a-form-item :label="t('clientGovernance.runtime.hosts')" :tooltip="t('clientGovernance.runtime.hostsHint')">
                <a-select :value="selectedProductGroups(runtimeGovernance.hosts)" mode="multiple" :disabled="runtimeConfigDisabled" @change="setHookProducts"><a-select-option v-for="product in hookProductOptions" :key="product.id" :value="product.id" :disabled="!product.entries.some(hookEntryEligible)">{{ product.name }}</a-select-option></a-select>
                <details v-if="selectedProductGroups(runtimeGovernance.hosts).includes('qoder')" class="effective">
                  <summary>{{ t('clientGovernance.runtime.qoderEntries') }}</summary>
                  <a-checkbox-group :value="runtimeGovernance.hosts.filter(id => productGroupId(id) === 'qoder')" :disabled="runtimeConfigDisabled" @change="setQoderHookEntries">
                    <a-space wrap><a-checkbox v-for="entry in qoderHookEntries" :key="entry.id" :value="entry.id" :aria-label="hookProductLabel(entry.id)" :disabled="runtimeConfigDisabled || !hookEntryEligible(entry)">{{ hookProductLabel(entry.id) }}</a-checkbox></a-space>
                  </a-checkbox-group>
                </details>
              </a-form-item>
              <details class="runtime-advanced">
                <summary>{{ t('clientPolicy.advanced') }}</summary>
                <div class="group-rules">
              <a-form-item v-for="field in ['installation', 'access_mode', 'updates']" :key="field" :label="t(`clientGovernance.runtime.${field}`)"><a-select v-model:value="runtimeGovernance[field]" :disabled="runtimeConfigDisabled"><a-select-option v-for="option in runtimeOptions[field]" :key="option" :value="option">{{ t(`clientGovernance.runtime.${field}_${option}`) }}</a-select-option></a-select></a-form-item>
              <a-form-item :label="t('clientGovernance.runtime.retry')" :tooltip="t('clientGovernance.runtime.retryHint')"><a-select v-model:value="runtimeGovernance.retry.mode" :disabled="runtimeConfigDisabled"><a-select-option v-for="mode in ['none','fixed','continuous']" :key="mode" :value="mode">{{ t(`clientGovernance.runtime.retry_${mode}`) }}</a-select-option></a-select></a-form-item>
              <a-form-item v-if="runtimeGovernance.retry.mode === 'fixed'" :label="t('clientGovernance.runtime.retryCount')"><a-input-number v-model:value="runtimeGovernance.retry.retries" :min="0" :max="20" :precision="0" :disabled="runtimeConfigDisabled" /></a-form-item>
              <a-form-item v-if="runtimeGovernance.retry.mode !== 'none'" :label="t('clientGovernance.runtime.retryInterval')"><a-input-number v-model:value="runtimeGovernance.retry.max_interval_seconds" :min="10" :max="3600" :precision="0" :disabled="runtimeConfigDisabled" /></a-form-item>
                </div>
              </details>
            </div>
            <a-alert v-if="runtimeGovernance.access_mode === 'managed'" type="warning" show-icon :message="t('clientGovernance.runtime.managedHint')" />
            <details v-if="clientId && open && activeTab === 'integration'" class="runtime-status"><summary>{{ t('clientPolicy.statusDetails') }}</summary><ClientProtectionStatus :client-id="clientId" /></details>
          </section>
          <section v-show="settingsSection === 'models'" class="policy-group">
            <header class="group-heading"><h3>{{ t('clientGovernance.modelRouting.title') }}</h3><p>{{ t('clientGovernance.modelRouting.description') }}</p></header>
            <a-checkbox v-if="clientId" v-model:checked="inheritModelRouting" :disabled="!editable || busy">{{ t('clientGovernance.inherit') }}</a-checkbox>
            <div class="group-rules model-routing-rules">
              <a-form-item :label="t('clientGovernance.modelRouting.enabled')">
                <a-switch v-model:checked="modelRouting.external_gateway_enabled" :disabled="modelRoutingDisabled || (!!clientId && !modelRoutingDefault.external_gateway_enabled)" />
                <div v-if="clientId && !modelRoutingDefault.external_gateway_enabled" class="effective">{{ t('clientGovernance.modelRouting.cannotEnable') }}</div>
              </a-form-item>
              <a-form-item :label="t('clientGovernance.modelRouting.gateway')" required>
                <a-select v-model:value="modelRouting.external_gateway_id" :disabled="modelRoutingDisabled || !modelRouting.external_gateway_enabled || !!clientId" :placeholder="t('clientGovernance.modelRouting.gatewayPlaceholder')">
                  <a-select-option v-for="gateway in availableGateways" :key="gateway.id" :value="gateway.id">{{ gateway.name }}</a-select-option>
                </a-select>
                <div v-if="clientId" class="effective">{{ t('clientGovernance.modelRouting.gatewayInherited') }}</div>
              </a-form-item>
              <a-form-item :label="t('clientGovernance.modelRouting.clientSelectModel')"><a-switch v-model:checked="modelRouting.client_select_model" :disabled="modelRoutingDisabled || !modelRouting.external_gateway_enabled || (!!clientId && !modelRoutingDefault.client_select_model)" /></a-form-item>
              <a-form-item :label="t('clientGovernance.modelRouting.autoRegisterAgent')"><a-switch v-model:checked="modelRouting.auto_register_agent" :disabled="modelRoutingDisabled || !modelRouting.external_gateway_enabled || (!!clientId && !modelRoutingDefault.auto_register_agent)" /></a-form-item>
            </div>
            <div class="effective">{{ t('clientGovernance.effective', { action: modelRoutingLabel(policy.model_routing) }) }}</div>
            <a-alert v-if="modelRouting.external_gateway_enabled" class="routing-note" type="warning" show-icon :message="t('clientGovernance.modelRouting.internalCapabilitiesUnavailable')" />
          </section>
          <section v-show="settingsSection === 'models'" class="policy-group policy-group-divider" :class="{ 'policy-group-disabled': modelRouting.external_gateway_enabled }">
            <header class="group-heading"><h3>{{ t('clientGovernance.compression.title') }}</h3><p>{{ t('clientGovernance.compression.description') }}</p></header>
            <a-checkbox v-if="clientId" v-model:checked="inheritCompression" :disabled="!editable || busy || modelRouting.external_gateway_enabled">{{ t('clientGovernance.inherit') }}</a-checkbox>
            <div class="group-rules">
              <a-form-item :label="t('clientGovernance.compression.enabled')"><a-switch v-model:checked="compression.enabled" :disabled="!editable || busy || inheritCompression || modelRouting.external_gateway_enabled" /></a-form-item>
              <a-form-item :label="t('clientGovernance.compression.level')">
                <a-select v-model:value="compression.level" :disabled="!editable || busy || inheritCompression || !compression.enabled || modelRouting.external_gateway_enabled">
                  <a-select-option v-for="level in ['auto', 'conservative', 'aggressive']" :key="level" :value="level">{{ t(`clientGovernance.compression.${level}`) }}</a-select-option>
                </a-select>
              </a-form-item>
            </div>
            <div class="effective">{{ t('clientGovernance.effective', { action: compressionLabel(policy.compression) }) }}</div>
            <div v-if="inheritCompression" class="effective">{{ t('clientGovernance.prompt.defaultValue', { value: compressionLabel(policy.compression_default) }) }}</div>
          </section>
          <section v-show="settingsSection === 'models'" class="policy-group policy-group-divider" :class="{ 'policy-group-disabled': modelRouting.external_gateway_enabled }">
            <header class="group-heading"><h3>{{ t('clientGovernance.prompt.title') }}</h3><p>{{ t('clientGovernance.prompt.description') }}</p></header>
            <a-checkbox v-if="clientId" v-model:checked="inheritPrompt" :disabled="!editable || busy || modelRouting.external_gateway_enabled">{{ t('clientGovernance.inherit') }}</a-checkbox>
            <div class="group-rules">
              <a-form-item :label="t('clientGovernance.prompt.mode')">
                <a-select v-model:value="promptGuard.mode" :disabled="!editable || busy || inheritPrompt || modelRouting.external_gateway_enabled">
                  <a-select-option v-for="mode in ['off', 'log', 'warn', 'block']" :key="mode" :value="mode">{{ t(`clientGovernance.prompt.${mode}`) }}</a-select-option>
                </a-select>
              </a-form-item>
              <a-form-item :label="t('clientGovernance.prompt.llmReview')"><a-switch v-model:checked="promptGuard.llm_review" :disabled="!editable || busy || inheritPrompt || modelRouting.external_gateway_enabled" /><div class="effective">{{ t('clientGovernance.prompt.reviewHint') }}</div></a-form-item>
            </div>
            <div class="effective">{{ t('clientGovernance.effective', { action: promptLabel(policy.prompt_guard) }) }}</div>
            <div v-if="inheritPrompt" class="effective">{{ t('clientGovernance.prompt.defaultValue', { value: promptLabel(policy.prompt_guard_default) }) }}</div>
          </section>
          <section v-for="(group, index) in groups" v-show="settingsSection === 'skills'" :key="group.key" class="policy-group" :class="{ 'policy-group-divider': index > 0 }">
            <header class="group-heading">
              <h3>{{ t(`clientGovernance.groups.${group.key}.title`) }}</h3>
              <p v-if="group.key === 'results'">{{ t('clientGovernance.groups.results.description') }}</p>
            </header>
            <div class="group-rules">
              <div v-for="trigger in group.triggers" :key="trigger" :ref="element => ruleFields[trigger] = element" class="rule-field" :data-rule="trigger" :class="{ 'priority-rule': trigger === 'malicious' }">
                <a-form-item>
                  <template #label>
                    {{ t(`clientGovernance.${trigger}`) }}
                  </template>
                  <a-select :value="rules[trigger] || ''" :disabled="!editable || busy" @change="value => setRule(trigger, value)">
                    <a-select-option v-if="clientId" value="">{{ t('clientGovernance.inherit') }}</a-select-option>
                    <a-select-option v-for="action in choices[trigger]" :key="action" :value="action">{{ t(`clientGovernance.${action}`) }}</a-select-option>
                  </a-select>
                  <div class="effective">{{ t('clientGovernance.effective', { action: t(`clientGovernance.${policy.rules[trigger]}`) }) }}</div>
                  <button v-if="draftAction(trigger) === 'submit_scan'" type="button" class="scan-followup" @click="focusRule(rejectionRule(trigger))">
                    {{ t('clientGovernance.scanFollowup', { action: t(`clientGovernance.${draftAction(rejectionRule(trigger))}`) }) }}
                    <span>{{ t('clientGovernance.configureFollowup') }} →</span>
                  </button>
                </a-form-item>
              </div>
            </div>
          </section>
        </a-form>
        <div v-else class="impact-preview">
          <small class="effective">{{ clientId || t('clientPolicy.globalSettings') }}</small>
          <table v-if="changeRows.length" class="change-list">
            <thead><tr><th>{{ t('clientPolicy.field') }}</th><th>{{ t('clientPolicy.before') }}</th><th>{{ t('clientPolicy.after') }}</th></tr></thead>
            <tbody><tr v-for="row in changeRows" :key="row.label"><th scope="row">{{ row.label }}</th><td>{{ row.before }}</td><td>{{ row.after }}</td></tr></tbody>
          </table>
          <p v-else>{{ t('clientPolicy.noChanges') }}</p>
          <h3 v-if="changedMenus.length || affectedModelSections.length || impact.classificationOnly || impact.incompatible_clients?.length">{{ t('clientPolicy.scope') }}</h3>
          <a-alert v-if="impact.incompatible_clients?.length" type="warning" show-icon :message="t('clientPolicy.blocked', { count: impact.incompatible_clients.length })">
            <template #description><details><summary>{{ t('clientPolicy.blockDetails') }}</summary>
              <ul class="prompt-impact"><li v-for="client in impact.incompatible_clients" :key="client.client_id">{{ client.client_name || client.client_id }} · {{ client.rules.map(rule => t(`clientGovernance.${rule}`)).join(' / ') }}</li></ul>
              {{ t('clientGovernance.capabilityHint') }}
            </details></template>
          </a-alert>
          <section v-if="!impact.classificationOnly && changedMenus.length">
            <details v-if="menuClients.length">
              <summary>{{ t('clientPolicy.clientDetails', { count: menuClients.length }) }}</summary>
              <ul class="prompt-impact"><li v-for="item in menuClients" :key="item.client_id">{{ item.client_name || item.client_id }} · {{ menuImpactText(item) }}<span v-if="item.preserved_overrides?.length"> · {{ t('clientGovernance.desktop.overrideKept') }}: {{ item.preserved_overrides.map(key => t(`clientGovernance.desktop.${key}`)).join(' / ') }}</span><span v-if="!item.supported"> · {{ t('clientGovernance.desktop.unsupported') }}</span></li></ul>
            </details>
            <p v-else>{{ t('clientGovernance.desktop.preview', { count: 0 }) }}</p>
          </section>
          <section v-for="section in affectedModelSections" :key="section.key">
            <details v-if="section.items.length">
              <summary>{{ t(`clientGovernance.${section.name}.title`) }} · {{ t('clientPolicy.clientDetails', { count: section.items.length }) }}</summary>
              <ul class="prompt-impact"><li v-for="item in section.items" :key="item.client_id">{{ item.client_name || item.client_id }}</li></ul>
            </details>
            <p v-if="section.name !== 'modelRouting' && section.count">{{ section.summary }}</p>
          </section>
          <template v-if="impact.classificationOnly">
          <p>{{ t('clientGovernance.candidates', { clients: impact.client_count, count: impact.candidate_count }) }}</p>
          <details v-if="impact.excluded_clients?.length">
            <summary>{{ t('clientGovernance.excludedTitle', { count: impact.excluded_clients.length }) }}</summary>
            <ul class="prompt-impact">
              <li v-for="client in impact.excluded_clients" :key="client.client_id">{{ client.client_name || client.client_id }} · {{ t(`clientGovernance.exclusion.${client.reason}`) }}</li>
            </ul>
          </details>
          <a-alert v-if="impact.contains_uninstall" type="warning" show-icon :message="t('clientGovernance.uninstallWarning')" />
          <details v-if="impact.items?.some(item => item.effect === 'recheck')" class="recheck-help">
            <summary>{{ t('clientGovernance.recheckCompact', { count: impact.items.filter(item => item.effect === 'recheck').length }) }}</summary>
            <div class="recheck-instructions">
              <p>{{ t('clientGovernance.recheckSteps') }}</p>
              <p v-if="impact.items?.some(item => ['broken_link', 'unscannable', 'external_link'].includes(item.recheck_reason))">{{ t('clientGovernance.recheckBlocked') }}</p>
            </div>
          </details>
          <details v-if="impact.items?.length">
          <summary>{{ t('clientGovernance.actionComparison') }} ({{ impact.candidate_count }})</summary>

          <a-table class="impact-tree" :data-source="impactTree" :columns="columns" row-key="key" :expanded-row-keys="expandedKeys" @expandedRowsChange="keys => expandedKeys = keys" :pagination="{ pageSize: 8, hideOnSinglePage: true }" :locale="{ emptyText: t('clientGovernance.empty') }" size="small" table-layout="fixed">
            <template #bodyCell="{ column, record }">
              <template v-if="column.dataIndex === 'name'">
                <span class="impact-name">{{ record.name }}</span>
                <div v-if="record.path" class="impact-path">{{ record.path }}</div>
                <div v-if="record.path" class="impact-effect" :class="{ changed: record.effect === 'changed' }">
                  <details v-if="record.effect === 'recheck'" class="skill-reason">
                    <summary>{{ t(`clientGovernance.reasonShort.${record.recheck_reason || 'missing_observation'}`) }}</summary>
                    <p>{{ t(`clientGovernance.recheckReason.${record.recheck_reason || 'missing_observation'}`) }}</p>
                  </details>
                  <template v-else>
                    <span>{{ record.trigger ? t(`clientGovernance.${record.trigger}`) : t('clientGovernance.noTrigger') }}</span>
                    <div>{{ t(`clientGovernance.${record.current_action}`) }} → {{ t(`clientGovernance.${record.proposed_action}`) }}</div>
                    <span v-if="record.client_override">{{ t('clientGovernance.overrideUnaffected') }}</span>
                  </template>
                </div>
                <div v-else class="impact-summary">{{ summaryText(record) }}</div>
              </template>
            </template>
          </a-table>
          </details>
          </template>
        </div>
      </template>
    </a-spin>
    <template #footer>
      <div class="actions">
        <a-button v-if="activeTab === 'integration' && impact" :disabled="modalBusy" @click="impact = null">{{ t('clientGovernance.back') }}</a-button>
        <a-button v-if="!impact" :disabled="modalBusy" @click="close">{{ t('clientGovernance.cancel') }}</a-button>
        <a-button v-if="activeTab === 'integration' && policy" type="primary" :loading="busy" :disabled="!editable || busy || (impact && !canConfirm)" @click="impact ? save() : preview()">{{ t(impact ? 'clientGovernance.confirm' : settingsSection === 'skills' ? 'clientPolicy.saveClassification' : 'clientGovernance.preview') }}</a-button>
        <a-button v-if="activeTab === 'audit' && auditSettings?.editable" type="primary" :loading="auditSettings.busy" :disabled="!auditSettings.canReview" @click="auditSettings.review()">{{ t('clientGovernance.preview') }}</a-button>
        <a-button v-if="activeTab === 'skillAudit' && skillAuditSettings?.editable" type="primary" :loading="skillAuditSettings.busy" :disabled="!skillAuditSettings.canReview" @click="skillAuditSettings.review()">{{ t('clientPolicy.saveUsage') }}</a-button>
        <a-button v-if="activeTab === 'discovery' && can('clients:update')" type="primary" :loading="discoverySettings?.busy" :disabled="!discoverySettings?.canSave" @click="discoverySettings.save()">{{ t('clientDiscovery.save') }}</a-button>
        <a-button v-if="activeTab === 'risk' && riskSettings?.editable" type="primary" :loading="riskSettings.busy" :disabled="!riskSettings.canSave" @click="riskSettings.save()">{{ t('aidrRisk.save') }}</a-button>
      </div>
    </template>
  </a-modal>
</template>

<script setup>
import products from '../aidr-products.json'
import { expandProductSelection, groupProductEntries, productGroupId, selectedProductGroups } from '../aidr-product-groups'
import ClientSecurityRules from './ClientSecurityRules.vue'
import { computed, ref, toRaw, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AidrRedactionSettings from './AidrRedactionSettings.vue'
import ClientDiscoveryConfig from './ClientDiscoveryConfig.vue'
import ClientProtectionStatus from './ClientProtectionStatus.vue'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { getClientGovernance, listExternalAiGateways, previewClientGovernance, saveClientGovernance } from '../api'
const props = defineProps({ open: Boolean, clientId: { type: String, default: '' }, initialTab: { type: String, default: 'integration' } })
const emit = defineEmits(['update:open', 'saved', 'global-risk'])
const { t } = useI18n()
const settingsSection = ref('runtime')
const skillSection = ref('usage')
const activeTab = computed(() => settingsSection.value === 'skills' && skillSection.value === 'usage' ? 'skillAudit' : ['audit', 'discovery', 'risk'].includes(settingsSection.value) ? settingsSection.value : 'integration')
const settingsSections = computed(() => {
  const clients = can('clients:view'), settings = can('settings:view')
  return [...(clients ? ['runtime'] : []), ...(settings ? ['audit'] : []),
    ...(clients ? ['models', 'discovery', 'skills', 'desktop'] : settings ? ['skills'] : []),
    ...(clients || settings ? ['risk'] : [])]
})
const riskVisited = ref(false)
const riskSettings = ref(null)
const auditVisited = ref(false)
const skillsVisited = ref(false)
const skillAuditSettings = ref(null)
const discoveryVisited = ref(false)
const discoverySettings = ref(null)
const menuKeys = ['discover', 'models', 'records', 'runtime-governance']
const desktopMenus = ref({})
let loadedPolicyPayload = ''
function menuImpactText(item) {
  return menuKeys.filter(key => item.current[key] !== item.proposed[key]).map(key =>
    `${t(`clientGovernance.desktop.${key}`)} ${t(item.current[key] ? 'clientGovernance.desktop.show' : 'clientGovernance.desktop.hide')} → ${t(item.proposed[key] ? 'clientGovernance.desktop.show' : 'clientGovernance.desktop.hide')}`
  ).join(' · ') || t('clientGovernance.desktop.unchanged')
}
function setDesktopMenu(menu, value) {
  if (value === 'inherit') delete desktopMenus.value[menu]
  else desktopMenus.value[menu] = value === 'show'
}
const policy = ref(null), rules = ref({}), impact = ref(null), loading = ref(false), busy = ref(false)
const auditSettings = ref(null)
const modalBusy = computed(() => loading.value || busy.value || riskSettings.value?.busy || auditSettings.value?.busy || auditSettings.value?.reviewOpen || discoverySettings.value?.busy || skillAuditSettings.value?.busy || skillAuditSettings.value?.reviewOpen)
function close() { if (!modalBusy.value) emit('update:open', false) }
const promptGuard = ref({ mode: 'log', llm_review: false }), inheritPrompt = ref(false)
const compression = ref({ enabled: false, level: 'auto' }), inheritCompression = ref(false)
const gateways = ref([]), policyError = ref(''), gatewayError = ref('')
const modelRouting = ref({ external_gateway_enabled: false, external_gateway_id: null, auto_register_agent: true, client_select_model: true })
const modelRoutingDefault = ref({ external_gateway_enabled: false, external_gateway_id: null, auto_register_agent: true, client_select_model: true })
const inheritModelRouting = ref(false)
const runtimeDefaults = () => ({ enabled: true, allow_user_enrollment: true, modes: { hooks: 'audit', system: 'audit' }, channels: { logs: true, hooks: true, system: false }, hosts: ['codex', 'claude'], installation: 'automatic', access_mode: 'ordinary', updates: 'automatic', retry: {mode: 'fixed', retries: 2, max_interval_seconds: 300} })
const runtimeGovernance = ref(runtimeDefaults())
// Retain selected legacy sources when editing another policy field.
const logSourceOptions = computed(() => groupProductEntries(products.filter(product => product.logs && (
  product.collection_visible !== false || runtimeGovernance.value.log_sources?.includes(product.id)
))))
const hookProductOptions = groupProductEntries(products.filter(product => product.hooks))
const qoderHookEntries = hookProductOptions.find(product => product.id === 'qoder')?.entries || []
const hookEntryEligible = entry => runtimeGovernance.value.access_mode !== 'managed' || entry.managed
const hookProductLabel = id => id === 'qoder-hooks' ? t('clientGovernance.runtime.qoderSharedHook') : products.find(product => product.id === id)?.name || id
function setLogProducts(value) {
  runtimeGovernance.value.log_sources = expandProductSelection(value, runtimeGovernance.value.log_sources || ['claude', 'codex'], logSourceOptions.value)
}
function setHookProducts(value) {
  runtimeGovernance.value.hosts = expandProductSelection(value, runtimeGovernance.value.hosts, hookProductOptions, hookEntryEligible)
}
function setQoderHookEntries(value) {
  runtimeGovernance.value.hosts = [...runtimeGovernance.value.hosts.filter(id => productGroupId(id) !== 'qoder'), ...value]
}
function setMode(channel, value) {
  runtimeGovernance.value.modes = { hooks: null, system: null, ...runtimeGovernance.value.modes, [channel]: value === 'legacy' ? null : value }
}
const inheritRuntime = ref(false)
watch(inheritRuntime, value => {
  if (value && policy.value) {
    runtimeGovernance.value = structuredClone(toRaw(policy.value.runtime_governance_default) || runtimeDefaults())
    if (!runtimeGovernance.value.channels) runtimeGovernance.value.channels = { logs: false, hooks: true, system: false }
  }
})
const runtimeOptions = {installation: ['automatic','manual'], access_mode: ['ordinary','managed'], updates: ['automatic','manual']}
const runtimeDisabled = computed(() => !editable.value || busy.value || (!!props.clientId && (policy.value?.runtime_channels_protocol !== 3 || inheritRuntime.value)))
const runtimeConfigDisabled = computed(() => runtimeDisabled.value || !runtimeGovernance.value.enabled)
const availableGateways = computed(() => gateways.value.filter(item => item.enabled || item.id === modelRouting.value.external_gateway_id))
const modelRoutingDisabled = computed(() => !editable.value || busy.value || inheritModelRouting.value)
const compressionLabel = value => value ? (value.enabled ? `${t('clientGovernance.prompt.enabled')} · ${t(`clientGovernance.compression.${value.level}`)}` : t('clientGovernance.prompt.disabled')) : ''
const promptLabel = guard => guard ? `${t(`clientGovernance.prompt.${guard.mode}`)} · ${t('clientGovernance.prompt.llmReview')}: ${t(guard.llm_review ? 'clientGovernance.prompt.enabled' : 'clientGovernance.prompt.disabled')}` : ''
const modelRoutingLabel = value => !value?.external_gateway_enabled
  ? t('clientGovernance.modelRouting.disabled')
  : `${gateways.value.find(item => item.id === value.external_gateway_id)?.name || (gatewayError.value ? t('clientGovernance.gatewayUnknown') : t('clientGovernance.modelRouting.gatewayMissing'))} · ${t(value.client_select_model ? 'clientGovernance.modelRouting.selectable' : 'clientGovernance.modelRouting.fixed')}`
const expandedKeys = ref([])
const savedMenus = computed(() => (props.clientId ? policy.value?.desktop_menu_overrides : policy.value?.desktop_menu_visibility) || {})
const changedMenus = computed(() => menuKeys.filter(key => savedMenus.value[key] !== desktopMenus.value[key]))
const menuLabel = value => t(`clientGovernance.desktop.${value == null ? 'inherit' : value ? 'show' : 'hide'}`)
const menuClients = computed(() => (impact.value?.desktop_menu_impacts || []).filter(item =>
  item.preserved_overrides?.length || menuKeys.some(key => item.current[key] !== item.proposed[key])))
const baseline = computed(() => impact.value && JSON.parse(loadedPolicyPayload))
const edited = key => Object.hasOwn(impact.value.request, key) && JSON.stringify(impact.value.request[key]) !== JSON.stringify(baseline.value[key])
const editedInheritance = key => edited(key) && (impact.value.request[key] == null || baseline.value[key] == null)
const sourceLabel = value => t(value == null ? 'clientGovernance.desktop.global' : 'clientGovernance.desktop.client')
function runtimeValues(value = {}) {
  const yesNo = on => t(on ? 'clientGovernance.prompt.enabled' : 'clientGovernance.prompt.disabled')
  const option = (field, code) => code ? t(`clientGovernance.runtime.${field}_${code}`) : '—'
  return {
    enabled: yesNo(value.enabled), userEnrollment: yesNo(value.allow_user_enrollment),
    channels: ['logs', 'hooks', 'system'].filter(key => value.channels?.[key]).map(key => option('channel', key)).join(' / ') || '—',
    mode_hooks: option('mode', value.modes?.hooks || 'legacy'), mode_system: option('mode', value.modes?.system || 'legacy'),
    logSources: (value.log_sources || ['claude', 'codex']).map(hookProductLabel).join(' / ') || '—',
    hosts: (value.hosts || []).map(hookProductLabel).join(' / ') || '—',
    installation: option('installation', value.installation), access_mode: option('access_mode', value.access_mode),
    updates: option('updates', value.updates), retry: option('retry', value.retry?.mode),
    retryCount: value.retry?.retries ?? '—', retryInterval: value.retry?.max_interval_seconds ?? '—',
  }
}
const runtimeChanges = computed(() => {
  if (!impact.value?.runtime_proposed || !Object.hasOwn(impact.value.request, 'runtime_governance')) return []
  const before = runtimeValues(impact.value.runtime_current || {}), after = runtimeValues(impact.value.runtime_proposed)
  return Object.keys(after).filter(key => before[key] !== after[key]).map(key => ({ label: t(`clientGovernance.runtime.${key}`), before: before[key], after: after[key] }))
})
const modelSections = computed(() => {
  if (!impact.value || impact.value.classificationOnly) return []
  return [
    ['model_routing', 'modelRouting'], ['compression', 'compression'], ['prompt_guard', 'prompt'],
  ].flatMap(([key, name]) => {
    if (!edited(key)) return []
    const items = (impact.value[`${key === 'prompt_guard' ? 'prompt' : key}_impacts`] || []).filter(item =>
      item.changed_credentials || Object.keys(item.proposed).some(field => item.current[field] !== item.proposed[field]))
    const count = name === 'modelRouting' ? items.length : items.reduce((sum, item) => sum + item.changed_credentials, 0)
    return [{ key, name, items, count, summary: t(`clientGovernance.${name}.preview`, { count }) }]
  })
})
const affectedModelSections = computed(() => modelSections.value.filter(section => section.items.length))
const changeRows = computed(() => {
  const { request, classificationOnly } = impact.value
  if (classificationOnly) {
    const saved = baseline.value.rules
    return [...new Set([...Object.keys(saved), ...Object.keys(request.rules)])].filter(key => saved[key] !== request.rules[key]).map(key => ({
      label: t(`clientGovernance.${key}`), before: t(`clientGovernance.${saved[key] || 'inherit'}`), after: t(`clientGovernance.${request.rules[key] || 'inherit'}`),
    }))
  }
  const rows = [...runtimeChanges.value, ...changedMenus.value.map(key => ({
    label: t(`clientGovernance.desktop.${key}`), before: menuLabel(savedMenus.value[key]), after: menuLabel(desktopMenus.value[key]),
  }))]
  const addSource = (key, label) => {
    if (props.clientId && editedInheritance(key)) rows.push({ label: t('clientPolicy.policySource', { label }), before: sourceLabel(baseline.value[key]), after: sourceLabel(request[key]) })
  }
  addSource('runtime_governance', t('clientPolicy.runtime'))
  const fields = {
    prompt_guard: { mode: 'prompt.title', llm_review: 'prompt.llmReview' },
    compression: { enabled: 'compression.title', level: 'compression.level' },
    model_routing: { external_gateway_enabled: 'modelRouting.enabled', external_gateway_id: 'modelRouting.gateway', auto_register_agent: 'modelRouting.autoRegisterAgent', client_select_model: 'modelRouting.clientSelectModel' },
  }
  const display = (key, value) => {
    if (value == null) return '—'
    if (key === 'mode' || key === 'level') return t(`clientGovernance.${key === 'mode' ? 'prompt' : 'compression'}.${value}`)
    if (key === 'external_gateway_id') return gateways.value.find(item => item.id === value)?.name || value
    return t(value ? 'clientGovernance.prompt.enabled' : 'clientGovernance.prompt.disabled')
  }
  for (const { key, name } of modelSections.value) {
    addSource(key, t(`clientGovernance.${name}.title`))
    const before = policy.value[key], after = request[key] ?? policy.value[key + '_default']
    for (const [field, label] of Object.entries(fields[key])) {
      if (before?.[field] !== after?.[field]) rows.push({ label: t(`clientGovernance.${label}`), before: display(field, before?.[field]), after: display(field, after?.[field]) })
    }
  }
  return rows
})
const canConfirm = computed(() => impact.value && !impact.value.incompatible_clients?.length && (impact.value.has_changes ?? changeRows.value.length > 0))
const impactTree = computed(() => {
  const clients = new Map()
  for (const item of impact.value?.items || []) {
    if (!clients.has(item.client_id)) clients.set(item.client_id, { key: JSON.stringify(['client', item.client_id]), name: item.client_name || item.client_id, agent_count: 0, skill_count: 0, agents: new Map() })
    const client = clients.get(item.client_id)
    if (!client.agents.has(item.agent_type)) client.agents.set(item.agent_type, { key: JSON.stringify(['agent', item.client_id, item.agent_type]), name: item.agent_type, skill_count: 0, children: [] })
    const agent = client.agents.get(item.agent_type)
    agent.children.push({ ...item, key: JSON.stringify(['skill', item.client_id, item.agent_type, item.path]), name: item.skill_name })
    agent.skill_count += 1
    client.skill_count += 1
  }
  return [...clients.values()].map(({ agents, ...client }) => ({ ...client, agent_count: [...agents.keys()].filter(type => type !== 'global-skills').length, ...(agents.size ? { children: [...agents.values()] } : {}) }))
})
const summaryText = record => {
  const skills = (record.children || []).flatMap(child => child.children || [child])
  const counts = {}
  for (const skill of skills) {
    const key = skill.effect === 'changed' ? skill.proposed_action : skill.effect === 'unchanged' ? 'unchanged' : 'recheck'
    counts[key] = (counts[key] || 0) + 1
  }
  return Object.entries(counts).map(([key, count]) => `${t(`clientGovernance.${key}`)} ${count}`).join(' · ')
}
let loadSequence = 0
const editable = computed(() => !gatewayError.value && !policyError.value && !loading.value && can('clients:update') && (policy.value?.supported || settingsSection.value === 'desktop') && (props.clientId || policy.value?.editable))
const choices = {
  unverified: ['record_only', 'record', 'submit_scan', 'quarantine'], malicious: ['record_only', 'record', 'quarantine', 'uninstall'],
  trusted_content_changed: ['record_only', 'record', 'submit_scan', 'quarantine', 'restore_trusted'], unverified_content_changed: ['record_only', 'record', 'submit_scan', 'quarantine'],
  trusted_scan_rejected: ['record_only', 'record', 'quarantine', 'restore_trusted'],
  unverified_scan_rejected: ['record_only', 'record', 'quarantine'],
}
const groups = [
  { key: 'unverified', triggers: ['unverified', 'unverified_content_changed'] },
  { key: 'certified', triggers: ['trusted_content_changed'] },
  { key: 'results', triggers: ['malicious', 'trusted_scan_rejected', 'unverified_scan_rejected'] },
]
const ruleFields = ref({})
const draftAction = trigger => rules.value[trigger] || policy.value.defaults?.[trigger] || policy.value.rules[trigger]
const rejectionRule = trigger => trigger === 'trusted_content_changed' ? 'trusted_scan_rejected' : 'unverified_scan_rejected'
const focusRule = trigger => {
  const element = ruleFields.value[trigger]
  element?.scrollIntoView({ block: 'center', behavior: 'auto' })
  element?.querySelector('input')?.focus({ preventScroll: true })
}
const columns = computed(() => [
  { title: t('clientGovernance.client'), dataIndex: 'name' },
  { title: t('clientGovernance.agentCount'), dataIndex: 'agent_count', width: 110, align: 'right' },
  { title: t('clientGovernance.skillCount'), dataIndex: 'skill_count', width: 110, align: 'right' },
])
const setRule = (trigger, action) => { impact.value = null; if (action) rules.value[trigger] = action; else delete rules.value[trigger] }
async function load() {
  const sequence = ++loadSequence
  busy.value = false; impact.value = null; policy.value = null; policyError.value = ''; gatewayError.value = ''; gateways.value = []
  if (!props.open || !can('clients:view') || activeTab.value !== 'integration') { loading.value = false; return }
  loading.value = true
  const clientId = props.clientId
  try {
    const gatewayRequest = can('external_gateways:view') ? listExternalAiGateways() : Promise.resolve([])
    const [policyResult, gatewayResult] = await Promise.allSettled([getClientGovernance(clientId), gatewayRequest])
    if (sequence !== loadSequence) return
    if (gatewayResult.status === 'rejected') gatewayError.value = 'client_governance_gateway_load_failed'
    if (policyResult.status === 'rejected') { policyError.value = 'client_governance_policy_load_failed'; return }
    const result = policyResult.value
    const gatewayRows = gatewayResult.status === 'fulfilled' ? gatewayResult.value : []
    policy.value = result
    desktopMenus.value = { ...(clientId ? result.desktop_menu_overrides : result.desktop_menu_visibility) }
    runtimeGovernance.value = structuredClone(result.runtime_governance_override || result.runtime_governance_default || runtimeDefaults())
    if (!result.runtime_governance_configured) runtimeGovernance.value.modes = runtimeDefaults().modes
    if (result.runtime_channels_protocol === 3 && !runtimeGovernance.value.channels) runtimeGovernance.value.channels = { logs: false, hooks: true, system: false }
    inheritRuntime.value = Boolean(clientId && !result.runtime_governance_override)
    rules.value = { ...(clientId ? result.overrides : result.rules) }
    promptGuard.value = { ...result.prompt_guard }
    inheritPrompt.value = Boolean(clientId && !result.prompt_guard_override)
    compression.value = { ...result.compression }
    inheritCompression.value = Boolean(clientId && !result.compression_override)
    gateways.value = gatewayRows || []
    modelRoutingDefault.value = { ...modelRoutingDefault.value, ...(result.model_routing_default || result.model_routing || {}) }
    modelRouting.value = { ...modelRoutingDefault.value, ...(result.model_routing || {}) }
    inheritModelRouting.value = Boolean(clientId && !result.model_routing_override)
    loadedPolicyPayload = JSON.stringify(payload())
  } catch (error) { if (sequence === loadSequence) policyError.value = 'client_governance_policy_load_failed' }
  finally { if (sequence === loadSequence) loading.value = false }
}
watch(() => [props.open, props.clientId, props.initialTab], () => {
  settingsSection.value = props.initialTab === 'risk' ? 'risk' : can('settings:view') && (props.initialTab === 'audit' || !can('clients:view')) ? 'audit' : props.initialTab === 'discovery' ? 'discovery' : 'runtime'
  riskVisited.value = settingsSection.value === 'risk'
  auditVisited.value = settingsSection.value === 'audit'
  discoveryVisited.value = settingsSection.value === 'discovery'
  skillsVisited.value = settingsSection.value === 'skills'
  skillSection.value = can('settings:view') ? 'usage' : 'classification'
  load()
}, { immediate: true })
watch(settingsSection, section => {
  if (section === 'risk') riskVisited.value = true
  if (section === 'audit') auditVisited.value = true
  if (section === 'discovery') discoveryVisited.value = true
  if (section === 'skills') skillsVisited.value = true
})
watch(activeTab, tab => { if (props.open && tab === 'integration' && !policy.value && !loading.value) load() })
const routingPayload = () => {
  if (inheritModelRouting.value) return null
  if (!props.clientId) return { ...modelRouting.value }
  return {
    ...modelRoutingDefault.value,
    external_gateway_enabled: Boolean(modelRoutingDefault.value.external_gateway_enabled && modelRouting.value.external_gateway_enabled),
    external_gateway_id: modelRoutingDefault.value.external_gateway_id,
    auto_register_agent: Boolean(modelRoutingDefault.value.auto_register_agent && modelRouting.value.auto_register_agent),
    client_select_model: Boolean(modelRoutingDefault.value.client_select_model && modelRouting.value.client_select_model),
  }
}
const payload = () => ({ rules: { ...rules.value }, prompt_guard: inheritPrompt.value ? null : { ...promptGuard.value }, compression: inheritCompression.value ? null : { ...compression.value }, model_routing: routingPayload(), ...(!props.clientId || policy.value.runtime_channels_protocol === 3 ? {runtime_governance: props.clientId && inheritRuntime.value ? null : JSON.parse(JSON.stringify(runtimeGovernance.value))} : {}), expected_version: policy.value.version })
const current = (sequence, clientId) => sequence === loadSequence && props.open && clientId === props.clientId
async function handleError(error) {
  const code = error.apiErrorCode || error.response?.data?.error_code
  if (code === 'client.policy_changed') {
    message.warning(t('clientGovernance.policyChanged'))
    await load()
  } else {
    impact.value = null
    message.error(code === 'client.policy_preview_required' ? t('clientGovernance.previewChanged') : error.response?.data?.detail || t('clientGovernance.failed'))
  }
}
async function preview() {
  if (busy.value || loading.value || !props.open || !editable.value) return
  const sequence = loadSequence, clientId = props.clientId
  const classificationOnly = settingsSection.value === 'skills'
  const request = { rules: { ...(classificationOnly ? rules.value : clientId ? policy.value.overrides : policy.value.rules) }, expected_version: policy.value.version }
  if (!classificationOnly) {
    const saved = JSON.parse(loadedPolicyPayload)
    const draft = payload()
    for (const key of ['runtime_governance', 'prompt_guard', 'compression', 'model_routing']) {
      if (Object.hasOwn(draft, key) && JSON.stringify(saved[key]) !== JSON.stringify(draft[key])) request[key] = draft[key]
    }
    if (changedMenus.value.length || Object.keys(request).length === 2) request.desktop_menu_visibility = { ...desktopMenus.value }
  }
  busy.value = true
  try {
    const result = await previewClientGovernance(clientId, request)
    if (current(sequence, clientId)) { expandedKeys.value = []; impact.value = { ...result, request, classificationOnly } }
  }
  catch (error) { if (current(sequence, clientId)) await handleError(error) }
  finally { if (current(sequence, clientId)) busy.value = false }
}
async function save() {
  if (busy.value || loading.value || !props.open || !editable.value || !canConfirm.value) return
  const sequence = loadSequence, clientId = props.clientId
  const request = { ...impact.value.request, preview_id: impact.value.preview_id }
  busy.value = true
  try {
    const saved = await saveClientGovernance(clientId, request)
    if (!current(sequence, clientId)) return
    const baseline = impact.value.classificationOnly ? JSON.parse(loadedPolicyPayload) : payload()
    policy.value = saved
    loadedPolicyPayload = JSON.stringify({ ...baseline, rules: { ...(clientId ? saved.overrides : saved.rules) }, expected_version: saved.version })
    impact.value = null
    message.success(t('clientGovernance.saved')); emit('saved')
  } catch (error) { if (current(sequence, clientId)) await handleError(error) }
  finally { if (current(sequence, clientId)) busy.value = false }
}
</script>

<style scoped>
:global(.client-governance-modal .ant-modal-content) { display: flex; flex-direction: column; max-height: calc(100dvh - 48px); }
:global(.client-governance-modal .ant-modal-body) { min-height: 0; overflow-y: auto; }
:global(.client-governance-modal .ant-modal-header),
:global(.client-governance-modal .ant-modal-footer) { flex-shrink: 0; }
.policy-form { margin-top: 16px; display: grid; gap: 16px; padding: 0; }
.settings-navigation { display: flex; gap: 4px; padding: 4px; margin-bottom: 16px; background: #f1f4f9; border-radius: 8px; overflow-x: auto; }
.settings-navigation button { flex: 1 0 auto; white-space: nowrap; padding: 8px 10px; border: 0; border-radius: 6px; background: transparent; color: #596b83; font: inherit; cursor: pointer; }
.settings-navigation button[aria-pressed=true] { background: #fff; color: #285bc4; font-weight: 600; box-shadow: 0 1px 4px #223c6114; }
.settings-navigation button:focus-visible { outline: 2px solid #3265df; outline-offset: 2px; }
.settings-navigation button:disabled { cursor: default; opacity: .65; }
.settings-description { margin: 0 0 8px; color: #66768c; font-size: 13px; line-height: 1.6; }
.runtime-advanced { grid-column: 1 / -1; border-top: 1px solid #e6eaf0; padding-top: 12px; }
.runtime-advanced summary { cursor: pointer; color: #445971; font-weight: 500; }
.runtime-advanced .group-rules { padding-top: 12px; }
.runtime-master, .runtime-off-hint { grid-column: 1 / -1; }
.runtime-status { margin-top: 16px; border-top: 1px solid #e6eaf0; padding-top: 16px; }
.runtime-status summary { cursor: pointer; color: #526987; font-size: 13px; margin-bottom: 10px; }
.policy-group { padding: 0; min-width: 0; }
.policy-group-divider { border-top: 1px solid #e6eaf0; padding-top: 16px; }
.settings-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin: 12px 0; }
.policy-group-disabled { background: #fafafa; color: #8c8c8c; }
.policy-group-disabled .group-heading p,
.policy-group-disabled .effective { color: #a3a3a3; }
.prompt-impact { max-height: 160px; overflow-y: auto; padding-left: 20px; overflow-wrap: anywhere; }
.group-heading { margin-bottom: 16px; }
.group-heading h3 { margin: 0; font-size: 15px; font-weight: 600; }
.group-heading p { margin: 4px 0 0; color: #777; font-size: 12px; line-height: 1.5; }
.group-rules { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.rule-field { min-width: 0; scroll-margin: 20px; }
.priority-rule { grid-column: 1 / -1; }
.policy-form .policy-group > .ant-checkbox-wrapper { margin-bottom: 8px; }
.policy-form :deep(.ant-form-item) { margin-bottom: 0; min-width: 0; }
.policy-form :deep(.ant-form-item-label > label) { height: auto; flex-wrap: wrap; }
.scan-followup { display: block; width: 100%; margin-top: 8px; padding: 8px 10px; border: 0; border-radius: 4px; background: #f5f8ff; color: #4c6075; text-align: start; font: inherit; font-size: 12px; line-height: 1.5; cursor: pointer; overflow-wrap: anywhere; }
.scan-followup span { color: #1677ff; margin-left: 6px; }
.scan-followup:focus-visible { outline: 2px solid #1677ff; outline-offset: 2px; }
@media (max-width: 600px) {
  .group-rules { grid-template-columns: minmax(0, 1fr); }
  .settings-navigation { flex-wrap: nowrap; overflow-x: auto; }
  .settings-navigation button { flex: 0 0 auto; white-space: nowrap; }
}
.recheck-help { margin-top: 12px; padding: 10px 12px; border-radius: 6px; background: #f5f7fa; color: #596975; }
.recheck-help summary, .skill-reason summary { cursor: pointer; font-size: 12px; line-height: 1.6; }
.recheck-instructions { padding-top: 6px; }
.skill-reason p { margin: 6px 0 0; }
.recheck-help p { margin: 6px 0 0; line-height: 1.6; }
.impact-name, .impact-path { overflow-wrap: anywhere; }
.impact-path { margin: 4px 0 0; color: #697986; font-size: 12px; line-height: 1.5; }
.impact-effect { margin: 6px 0 0; font-size: 12px; line-height: 1.6; color: #687681; overflow-wrap: anywhere; }
.impact-effect.changed { color: #ad5925; background: #fff8ed; padding: 6px 8px; border-radius: 4px; }
.impact-summary { margin-top: 4px; color: #687681; font-size: 12px; overflow-wrap: anywhere; }
.impact-preview { display: flex; flex-direction: column; gap: 12px; overflow-wrap: anywhere; }
.impact-preview p { margin: 0; }
.impact-preview summary { cursor: pointer; }
.change-list { border-collapse: collapse; table-layout: fixed; width: 100%; text-align: start; }
.change-list th, .change-list td { text-align: start; padding: 8px 10px; border-bottom: 1px solid #e6eaf0; overflow-wrap: anywhere; }
.change-list thead { background: #f5f7fa; }
.change-list tbody th { font-weight: 400; }
.impact-preview h3 { margin: 0 0 6px; font-size: 15px; }
.impact-tree :deep(.ant-table-cell) { vertical-align: top; }
.effective { color: #777; margin-top: 6px; overflow-wrap: anywhere; }
.routing-note { margin-top: 14px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
</style>

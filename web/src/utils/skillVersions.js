export const lifecycleVersionId = record => String(record?.version_id || record?.skill_id || '').trim()

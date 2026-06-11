# Per-User Token Usage Statistics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-user token usage statistics page to the model gateway, showing input/output token breakdown, compression savings, and daily trends filtered by user.

**Architecture:** Single backend endpoint JOINs `LlmUsageMetric` → `LlmApiKey` → `User` to aggregate by `user_id`. New Vue page reuses existing `Chart` component and follows `ModelGatewayStats.vue` patterns. No new database tables.

**Tech Stack:** SQLAlchemy (JOIN + GROUP BY), FastAPI, Vue 3 + ECharts + Ant Design Vue

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/routers/llm_gateway.py` | Add `GET /llm-stats/by-user` endpoint |
| Create | `web/src/views/UserTokenStats.vue` | Per-user stats page with cards + charts + table |
| Modify | `web/src/router/index.js` | Add `/model-gateway/user-stats` route |
| Modify | `web/src/App.vue` | Add "用户用量" menu item under 模型网关 |
| Modify | `web/src/api/index.js` | Add `getLlmStatsByUser()` API function |

---

### Task 1: Backend — Per-user aggregation endpoint

**Files:**
- Modify: `backend/routers/llm_gateway.py` (insert before the `_chat_completions_impl` function, near the other `@admin_router.get("/llm-stats/...")` endpoints)

- [ ] **Step 1: Add the endpoint**

Find the last `@admin_router.get("/llm-stats/by-model")` endpoint (near line ~1820). Insert this new endpoint right after it:

```python
@admin_router.get("/llm-stats/by-user")
async def get_llm_stats_by_user(
    days: int = Query(default=30, ge=1, le=365),
    model: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    """按用户统计的 Token 用量数据（JOIN user 表获取用户名）"""
    since = _now() - timedelta(days=max(1, min(days, 365)))

    q = (
        db.query(
            models.LlmApiKey.user_id,
            models.User.username,
            func.coalesce(func.sum(models.LlmUsageMetric.prompt_tokens), 0).label("prompt"),
            func.coalesce(func.sum(models.LlmUsageMetric.completion_tokens), 0).label("completion"),
            func.coalesce(func.sum(models.LlmUsageMetric.total_tokens), 0).label("total"),
            func.coalesce(func.sum(models.LlmUsageMetric.tokens_saved), 0).label("saved"),
            func.count(models.LlmUsageMetric.id).label("requests"),
        )
        .join(models.LlmApiKey, models.LlmUsageMetric.api_key_id == models.LlmApiKey.id)
        .join(models.User, models.LlmApiKey.user_id == models.User.id)
        .filter(models.LlmUsageMetric.created_at >= since)
    )
    if model:
        q = q.filter(models.LlmUsageMetric.model == model)

    rows = (
        q.group_by(models.LlmApiKey.user_id)
        .order_by(func.sum(models.LlmUsageMetric.total_tokens).desc())
        .all()
    )

    return {
        "days": days,
        "model": model,
        "users": [
            {
                "user_id": row.user_id,
                "username": row.username or f"user-{row.user_id}",
                "prompt_tokens": int(row.prompt),
                "completion_tokens": int(row.completion),
                "total_tokens": int(row.total),
                "tokens_saved": int(row.saved),
                "requests": row.requests,
            }
            for row in rows
        ],
    }
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('backend/routers/llm_gateway.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/llm_gateway.py
git commit -m "feat: add per-user token stats endpoint with JOIN to user table"
```

---

### Task 2: Frontend API function

**Files:**
- Modify: `web/src/api/index.js`

- [ ] **Step 1: Add the API function**

After the existing `getLlmStatsByModel` line, add:

```javascript
export const getLlmStatsByUser = (params = {}) => api.get('/v1/llm-stats/by-user', { params })
```

- [ ] **Step 2: Commit**

```bash
git add web/src/api/index.js
git commit -m "feat: add getLlmStatsByUser API function"
```

---

### Task 3: Frontend — User token stats page

**Files:**
- Create: `web/src/views/UserTokenStats.vue`

- [ ] **Step 1: Create the page**

Write `web/src/views/UserTokenStats.vue`:

```vue
<template>
  <div>
    <a-page-header title="模型网关" sub-title="按用户统计 Token 用量" />

    <!-- 筛选 -->
    <a-space style="margin-bottom: 16px" wrap>
      <span>统计范围:</span>
      <a-radio-group v-model:value="days" @change="loadData" button-style="solid" size="small">
        <a-radio-button :value="7">近 7 天</a-radio-button>
        <a-radio-button :value="14">近 14 天</a-radio-button>
        <a-radio-button :value="30">近 30 天</a-radio-button>
        <a-radio-button :value="90">近 90 天</a-radio-button>
      </a-radio-group>
      <a-select
        v-model:value="selectedModel"
        style="width: 200px"
        placeholder="全部模型"
        allow-clear
        @change="loadData"
        size="small"
      >
        <a-select-option v-for="m in availableModels" :key="m" :value="m">{{ m }}</a-select-option>
      </a-select>
      <a-button size="small" @click="loadData" :loading="loading">刷新</a-button>
    </a-space>

    <!-- 柱状图: 按用户 Token 用量 -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :xs="24" :xl="16">
        <a-card title="各用户 Token 用量（堆叠柱状图）">
          <Chart v-if="userStats.users?.length" :options="userBarOptions" height="380px" />
          <a-empty v-else description="暂无数据" style="padding: 80px 0" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="8">
        <a-card title="各用户压缩节省">
          <Chart v-if="hasCompression" :options="savedBarOptions" height="380px" />
          <a-empty v-else description="暂无压缩数据" style="padding: 80px 0" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 明细表 -->
    <a-card title="用户用量明细">
      <a-table
        :data-source="userStats.users"
        :columns="columns"
        row-key="user_id"
        :loading="loading"
        :pagination="false"
        size="small"
        :locale="{ emptyText: '暂无数据' }"
      />
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import Chart from '../components/Chart.vue'
import { getLlmStatsByUser, getLlmStatsByModel } from '../api'

const days = ref(30)
const selectedModel = ref(null)
const loading = ref(false)
const userStats = ref({ users: [] })
const availableModels = ref([])

const formatNumber = (n) => {
  if (!n && n !== 0) return '-'
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

const hasCompression = computed(() =>
  userStats.value.users?.some(u => u.tokens_saved > 0)
)

const loadData = async () => {
  loading.value = true
  try {
    const params = { days: days.value }
    if (selectedModel.value) params.model = selectedModel.value
    const data = await getLlmStatsByUser(params)
    userStats.value = data
    // 加载模型列表供筛选
    if (!selectedModel.value) {
      const bm = await getLlmStatsByModel({ days: days.value })
      availableModels.value = (bm.models || []).map(m => m.model)
    }
  } catch (e) {
    message.error('加载统计数据失败')
  } finally {
    loading.value = false
  }
}

const userBarOptions = computed(() => {
  const users = userStats.value.users || []
  const names = users.map(u => u.username)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['输入 Token', '输出 Token'] },
    grid: { left: 60, right: 10, top: 30, bottom: 100 },
    xAxis: { type: 'category', data: names, axisLabel: { rotate: 45, fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: formatNumber } },
    series: [
      { name: '输入 Token', type: 'bar', stack: 'tokens', data: users.map(u => u.prompt_tokens), itemStyle: { color: '#1890ff' } },
      { name: '输出 Token', type: 'bar', stack: 'tokens', data: users.map(u => u.completion_tokens), itemStyle: { color: '#52c41a' } },
    ],
  }
})

const savedBarOptions = computed(() => {
  const users = (userStats.value.users || []).filter(u => u.tokens_saved > 0)
  const names = users.map(u => u.username)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p) => {
        const u = users[p[0].dataIndex]
        const pct = u.prompt_tokens ? Math.round(u.tokens_saved / u.prompt_tokens * 100) : 0
        return `${u.username}<br/>节省: ${formatNumber(u.tokens_saved)} (${pct}%)`
      },
    },
    grid: { left: 60, right: 10, top: 30, bottom: 100 },
    xAxis: { type: 'category', data: names, axisLabel: { rotate: 45, fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: formatNumber } },
    series: [{
      name: '压缩节省', type: 'bar',
      data: users.map(u => u.tokens_saved),
      itemStyle: { color: '#722ed1' },
      label: { show: true, position: 'top', formatter: (p) => formatNumber(p.value), fontSize: 10 },
    }],
  }
})

const columns = [
  { title: '用户', dataIndex: 'username', width: 140 },
  { title: '请求数', dataIndex: 'requests', width: 80, align: 'right', customRender: ({ text }) => formatNumber(text) },
  { title: '输入 Token', dataIndex: 'prompt_tokens', width: 120, align: 'right', sorter: (a, b) => a.prompt_tokens - b.prompt_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: '输出 Token', dataIndex: 'completion_tokens', width: 120, align: 'right', sorter: (a, b) => a.completion_tokens - b.completion_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: '总 Token', dataIndex: 'total_tokens', width: 120, align: 'right', sorter: (a, b) => a.total_tokens - b.total_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: '压缩节省', dataIndex: 'tokens_saved', width: 120, align: 'right', customRender: ({ text, record }) => {
    if (!text) return '-'
    const pct = record.prompt_tokens ? Math.round(text / record.prompt_tokens * 100) : 0
    return `${formatNumber(text)} (${pct}%)`
  } },
]

onMounted(() => loadData())
</script>
```

- [ ] **Step 2: Commit**

```bash
git add web/src/views/UserTokenStats.vue
git commit -m "feat: add per-user token stats page with bar charts and table"
```

---

### Task 4: Route + Menu entry

**Files:**
- Modify: `web/src/router/index.js`
- Modify: `web/src/App.vue`

- [ ] **Step 1: Add route**

In `web/src/router/index.js`, add after the existing `/model-gateway/stats` route:

```javascript
  { path: '/model-gateway/user-stats', name: 'model-gateway-user-stats', component: () => import('../views/UserTokenStats.vue'), meta: { requiresAuth: true } },
```

- [ ] **Step 2: Add menu item**

In `web/src/App.vue`, find the model-gateway children array and add after the `stats` entry:

```javascript
      { key: '/model-gateway/user-stats', label: '用户用量', icon: TeamOutlined },
```

Also add `TeamOutlined` to the import from `@ant-design/icons-vue` (it should already be available in the icon library).

- [ ] **Step 3: Verify build**

```bash
cd web && npm run build
```

Expected: builds successfully with `UserTokenStats-*.js` in output.

- [ ] **Step 4: Commit**

```bash
git add web/src/router/index.js web/src/App.vue
git commit -m "feat: add user token stats route and menu entry"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - [x] Per-user token usage (input/output/total) — `by-user` endpoint + bar chart + table
   - [x] Per-user compression savings — `tokens_saved` column + separate bar chart
   - [x] Filter by model — `?model=` query param
   - [x] Date range — `?days=` query param (reused from existing pattern)

2. **Placeholder scan:** No TBDs, TODOs, or vague instructions. Every step has exact code.

3. **Type consistency:**
   - `getLlmStatsByUser(params)` → returns `{users: [{user_id, username, prompt_tokens, ...}]}`
   - Frontend destructures correctly: `userStats.value.users`
   - Chart `computed` refs access the same shape

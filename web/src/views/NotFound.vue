<template>
  <a-result status="404" title="页面不存在" sub-title="请从左侧导航返回可用页面。">
    <template #extra>
      <a-button type="primary" @click="$router.push('/dashboard')">返回首页</a-button>
    </template>
  </a-result>
</template>

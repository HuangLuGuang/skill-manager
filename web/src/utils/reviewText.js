export const REVIEW_TEXT_LIMIT = 1000

// 按 Unicode 字符计数，与后端一致；保留完整草稿，不截断超长内容。
export const reviewTextLength = value => Array.from(value).length

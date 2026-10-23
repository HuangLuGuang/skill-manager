export const commandParsingMessages = {
  'zh-CN': {
    title: '解析出的子命令 · {count}', original: '原始命令', summary: '已采集命令摘要', line: '第 {line} 行', dynamic: '动态程序名',
    summaryPreview: '命令摘要已采集，展开详情查看',
    boundary: '按 Shell 语法拆分并统计命令在文本中的出现次数。执行结果按整个工具调用记录。',
    shortened: '子命令预览已缩短，完整内容见原始命令。',
    status: {
      partial: '部分程序名依赖动态展开，保留对应文本，仅将能确定的程序名计入排行。',
      invalid: '命令语法不完整或不在当前 Bash / POSIX 解析范围，保留原文，未计入命令出现次数。',
      truncated: '已采集命令被截断，无法可靠拆分，未计入命令出现次数。',
      unavailable: '未采集完整命令或内容已省略，无法拆分。',
      limit: '命令超出解析资源上限，保留原文，未计入命令出现次数。',
    },
  },
  'en-US': {
    title: 'Parsed subcommands · {count}', original: 'Original command', summary: 'Captured command summary', line: 'Line {line}', dynamic: 'Dynamic program name',
    summaryPreview: 'Command summary collected; expand details to view',
    boundary: 'Shell parsing counts command occurrences in the text. Execution results are recorded for the whole tool call.',
    shortened: 'Subcommand preview shortened. See the original command for the full captured text.',
    status: {
      partial: 'Some program names depend on dynamic expansion. Their text is retained; only resolved names enter the ranking.',
      invalid: 'Incomplete syntax or outside the supported Bash / POSIX grammar. Original text is retained and excluded from command occurrences.',
      truncated: 'Captured command was truncated and cannot be reliably split. Excluded from command occurrences.',
      unavailable: 'Complete command text was not collected or was omitted; parsing is unavailable.',
      limit: 'Command exceeds parsing limits. Original text is retained and excluded from command occurrences.',
    },
  },
}

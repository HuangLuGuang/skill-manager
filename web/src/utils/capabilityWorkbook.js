import { BlobWriter, TextReader, ZipWriter } from '@zip.js/zip.js'

import { capabilityModuleLabel } from '../docs/capabilityCatalog.js'

const MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

const xml = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&apos;')

const columnName = index => {
  let value = index + 1
  let name = ''
  while (value) {
    value -= 1
    name = String.fromCharCode(65 + (value % 26)) + name
    value = Math.floor(value / 26)
  }
  return name
}

const cell = (row, column, value, style = 0) => {
  const ref = `${columnName(column)}${row}`
  if (typeof value === 'number') return `<c r="${ref}" s="${style}"><v>${value}</v></c>`
  return `<c r="${ref}" s="${style}" t="inlineStr"><is><t xml:space="preserve">${xml(value)}</t></is></c>`
}

const row = (index, values, style = 0, height) => {
  const cells = values.map((value, column) => cell(index, column, value, style)).join('')
  return `<row r="${index}"${height ? ` ht="${height}" customHeight="1"` : ''}>${cells}</row>`
}

const workbookLabels = locale => locale === 'en-US' ? {
  overview: 'Overview',
  list: 'Feature list',
  title: 'Agent Manager feature list',
  generatedAt: 'Generated at',
  scope: 'Export scope',
  module: 'Module',
  description: 'Description',
  count: 'Feature count',
  total: 'Total features',
  headers: ['No.', 'Module', 'Capability area', 'Feature', 'Description', 'Usage scenario', 'Entry point', 'Capability boundary', 'Help article'],
} : {
  overview: '功能总览',
  list: '功能清单',
  title: 'Agent Manager 产品功能清单',
  generatedAt: '生成时间',
  scope: '导出范围',
  module: '一级模块',
  description: '功能说明',
  count: '功能项数量',
  total: '功能项总数',
  headers: ['序号', '一级模块', '二级能力', '功能名称', '功能说明', '使用场景', '操作入口', '能力边界', '帮助章节'],
}

const moduleDescription = (moduleId, locale) => {
  const descriptions = locale === 'en-US' ? {
    skill: 'Govern Skills from submission and scanning through approval, signing, and runtime verification.',
    agent: 'Manage Agent identities, authorization, credentials, and runtime controls.',
    client: 'Discover local Agents and deliver, inspect, recover, or isolate Skills.',
    scanner: 'Discover and submit Skills from customer hosts with a standalone binary scanner.',
    security: 'Run authorized AI security assessments and manage evidence and remediation.',
    mcp: 'Govern MCP Servers, Tools, Gateways, credentials, approvals, and audit events.',
    model: 'Control model access, privacy processing, prompt protection, usage, and traces.',
    system: 'Manage identities, settings, documentation, exports, and audit records.',
    operations: 'Deploy, verify, protect, upgrade, and size the Docker Compose platform.',
  } : {
    skill: '治理 Skill 从提交、检测、审核到签名和运行时校验的完整生命周期。',
    agent: '治理 Agent 身份、授权、凭证和运行时控制。',
    client: '发现本地 Agent，并下发、巡检、恢复或隔离 Skill。',
    scanner: '使用独立二进制扫描器在客户主机发现并提交 Skill。',
    security: '对授权目标执行 AI 安全评估并管理证据和修复闭环。',
    mcp: '治理 MCP Server、Tool、Gateway、凭证、审批和审计。',
    model: '控制模型接入、隐私处理、Prompt 防护、用量和轨迹。',
    system: '管理身份、系统设置、帮助文档、导出和审计记录。',
    operations: '部署、检查、保护、升级和评估 Docker Compose 平台容量。',
  }
  return descriptions[moduleId] || ''
}

const sheetXml = ({ columns, rows, merges = [], freezeRows = 0, autoFilter }) => `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews><sheetView workbookViewId="0" showGridLines="0">${freezeRows ? `<pane ySplit="${freezeRows}" topLeftCell="A${freezeRows + 1}" activePane="bottomLeft" state="frozen"/>` : ''}</sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>${columns.map((width, index) => `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`).join('')}</cols>
  <sheetData>${rows.join('')}</sheetData>
  ${autoFilter ? `<autoFilter ref="${autoFilter}"/>` : ''}
  ${merges.length ? `<mergeCells count="${merges.length}">${merges.map(ref => `<mergeCell ref="${ref}"/>`).join('')}</mergeCells>` : ''}
  <pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
</worksheet>`

const stylesXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="4">
    <font><sz val="10"/><name val="Arial"/></font>
    <font><b/><sz val="16"/><color rgb="FF17365D"/><name val="Arial"/></font>
    <font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>
    <font><b/><sz val="10"/><color rgb="FF17365D"/><name val="Arial"/></font>
  </fonts>
  <fills count="4">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFD9EAF7"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFE6E6E6"/></left><right style="thin"><color rgb="FFE6E6E6"/></right><top style="thin"><color rgb="FFE6E6E6"/></top><bottom style="thin"><color rgb="FFE6E6E6"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="8">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`

const addText = (writer, path, content) => writer.add(path, new TextReader(content))

export async function buildCapabilityWorkbookBlob({ items, locale = 'zh-CN', generatedAt = new Date() }) {
  const labels = workbookLabels(locale)
  const modules = [...new Set(items.map(item => item.module))]
  const overviewRows = [
    row(1, [labels.title], 1, 28),
    row(2, [labels.generatedAt, new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(generatedAt)], 0, 22),
    row(3, [labels.scope, modules.map(id => capabilityModuleLabel(id, locale)).join(locale === 'en-US' ? ', ' : '、')], 0, 28),
    row(5, [labels.module, labels.description, labels.count], 2, 26),
  ]
  modules.forEach((moduleId, index) => {
    overviewRows.push(row(6 + index, [
      capabilityModuleLabel(moduleId, locale),
      moduleDescription(moduleId, locale),
      items.filter(item => item.module === moduleId).length,
    ], 3, 30))
  })
  overviewRows.push(row(7 + modules.length, [labels.total, '', items.length], 4, 26))

  const detailRows = [
    row(1, [labels.title], 1, 28),
    row(3, labels.headers, 2, 34),
  ]
  items.forEach((item, index) => {
    detailRows.push(row(4 + index, [
      index + 1,
      capabilityModuleLabel(item.module, locale),
      item.submodule,
      item.name,
      item.description,
      item.scenario,
      item.entry,
      item.boundary,
      item.docs,
    ], index % 2 ? 3 : 7, 54))
  })

  const overviewXml = sheetXml({
    columns: [28, 72, 16],
    rows: overviewRows,
    merges: ['A1:C1', 'B2:C2', 'B3:C3', `A${7 + modules.length}:B${7 + modules.length}`],
  })
  const lastDetailRow = Math.max(3, 3 + items.length)
  const detailXml = sheetXml({
    columns: [8, 24, 20, 25, 52, 52, 30, 55, 24],
    rows: detailRows,
    merges: ['A1:I1'],
    freezeRows: 3,
    autoFilter: `A3:I${lastDetailRow}`,
  })

  const writer = new ZipWriter(new BlobWriter(MIME), { useWebWorkers: false })
  await addText(writer, '[Content_Types].xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>`)
  await addText(writer, '_rels/.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>`)
  await addText(writer, 'docProps/core.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>${xml(labels.title)}</dc:title><dc:creator>Agent Manager</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">${generatedAt.toISOString()}</dcterms:created></cp:coreProperties>`)
  await addText(writer, 'docProps/app.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Agent Manager</Application></Properties>`)
  await addText(writer, 'xl/workbook.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${xml(labels.overview)}" sheetId="1" r:id="rId1"/><sheet name="${xml(labels.list)}" sheetId="2" r:id="rId2"/></sheets></workbook>`)
  await addText(writer, 'xl/_rels/workbook.xml.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`)
  await addText(writer, 'xl/styles.xml', stylesXml)
  await addText(writer, 'xl/worksheets/sheet1.xml', overviewXml)
  await addText(writer, 'xl/worksheets/sheet2.xml', detailXml)
  return writer.close()
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

export const capabilityWorkbookFilename = (locale, date = new Date()) => {
  const stamp = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('')
  return locale === 'en-US'
    ? `Agent-Manager-feature-list-${stamp}.xlsx`
    : `Agent-Manager-产品功能清单-${stamp}.xlsx`
}

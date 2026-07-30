export const parseUnifiedDiff = (diff = '') => {
  const lines = diff.split('\n')
  const sideRows = []
  const inlineRows = []
  let oldLineNo = 0
  let newLineNo = 0
  let rowIndex = 0

  const lineCell = (lineNo, text, kind, marker) => ({
    lineNo,
    text,
    kind,
    marker,
  })
  const pushInline = (kind, marker, text, oldNo = '', newNo = '') => {
    inlineRows.push({
      key: `inline-${rowIndex++}`,
      kind,
      marker,
      text,
      oldLineNo: oldNo,
      newLineNo: newNo,
    })
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    if (line.startsWith('--- ') || line.startsWith('+++ ')) continue
    if (line.startsWith('@@')) {
      const header = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/)
      if (header) {
        oldLineNo = Number(header[1])
        newLineNo = Number(header[2])
      }
      sideRows.push({ key: `side-${rowIndex++}`, kind: 'hunk', text: line })
      pushInline('hunk', '', line)
      continue
    }
    if (line.startsWith('-')) {
      const removed = []
      const added = []
      while (index < lines.length && lines[index].startsWith('-') && !lines[index].startsWith('--- ')) {
        removed.push(lines[index].slice(1))
        index += 1
      }
      while (index < lines.length && lines[index].startsWith('+') && !lines[index].startsWith('+++ ')) {
        added.push(lines[index].slice(1))
        index += 1
      }
      index -= 1
      const removedCells = removed.map(text => lineCell(oldLineNo++, text, 'removed', '-'))
      const addedCells = added.map(text => lineCell(newLineNo++, text, 'added', '+'))
      const pairedCount = Math.max(removedCells.length, addedCells.length)
      for (let pairIndex = 0; pairIndex < pairedCount; pairIndex += 1) {
        sideRows.push({
          key: `side-${rowIndex++}`,
          kind: 'change',
          left: removedCells[pairIndex] || null,
          right: addedCells[pairIndex] || null,
        })
      }
      removedCells.forEach(cell => pushInline('removed', '-', cell.text, cell.lineNo, ''))
      addedCells.forEach(cell => pushInline('added', '+', cell.text, '', cell.lineNo))
      continue
    }
    if (line.startsWith('+')) {
      const right = lineCell(newLineNo++, line.slice(1), 'added', '+')
      sideRows.push({ key: `side-${rowIndex++}`, kind: 'change', left: null, right })
      pushInline('added', '+', right.text, '', right.lineNo)
      continue
    }
    if (line.startsWith(' ')) {
      const text = line.slice(1)
      const left = lineCell(oldLineNo++, text, 'context', '')
      const right = lineCell(newLineNo++, text, 'context', '')
      sideRows.push({ key: `side-${rowIndex++}`, kind: 'context', left, right })
      pushInline('context', '', text, left.lineNo, right.lineNo)
    }
  }
  return { sideRows, inlineRows }
}

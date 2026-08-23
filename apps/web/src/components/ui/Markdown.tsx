// 최소 마크다운 렌더러 — Agent 보고서(자연어 md)를 그리는 용도.
//  지원: ##/### 제목, - 목록, 1. 목록, > 인용, --- 구분선, **굵게**, `코드`, | 표 |.
//  원문 HTML은 해석하지 않고 텍스트 노드로만 렌더링한다(주입 위험 없음).
import { Fragment, type ReactNode } from 'react'

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`)/g

function inline(text: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <b key={index}>{part.slice(2, -2)}</b>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index} className="md-code">{part.slice(1, -1)}</code>
    return <Fragment key={index}>{part}</Fragment>
  })
}

type Block =
  | { kind: 'h2' | 'h3' | 'p' | 'quote'; text: string }
  | { kind: 'hr' }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'table'; header: string[]; rows: string[][] }

// GFM 표 구분행: |---|:--:|---:| 형태(정렬 콜론 허용).
const TABLE_SEP = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/

function splitRow(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map((cell) => cell.trim())
}

function parse(source: string): Block[] {
  const blocks: Block[] = []
  const lines = source.split('\n').map((raw) => raw.trimEnd())
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const bullet = /^[-*]\s+(.*)$/.exec(line)
    const numbered = /^\d+\.\s+(.*)$/.exec(line)
    const last = blocks[blocks.length - 1]

    if (!line.trim()) { i++; continue }
    if (line.startsWith('### ')) { blocks.push({ kind: 'h3', text: line.slice(4) }); i++; continue }
    if (line.startsWith('## ')) { blocks.push({ kind: 'h2', text: line.slice(3) }); i++; continue }
    if (line.startsWith('# ')) { blocks.push({ kind: 'h2', text: line.slice(2) }); i++; continue }
    if (line.startsWith('> ')) { blocks.push({ kind: 'quote', text: line.slice(2) }); i++; continue }
    if (/^(-{3,}|_{3,})$/.test(line.trim())) { blocks.push({ kind: 'hr' }); i++; continue }
    if (line.trim().startsWith('|') && TABLE_SEP.test(lines[i + 1]?.trim() ?? '')) {
      const header = splitRow(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(splitRow(lines[i]))
        i++
      }
      blocks.push({ kind: 'table', header, rows })
      continue
    }
    if (bullet) {
      if (last?.kind === 'ul') last.items.push(bullet[1])
      else blocks.push({ kind: 'ul', items: [bullet[1]] })
      i++; continue
    }
    if (numbered) {
      if (last?.kind === 'ol') last.items.push(numbered[1])
      else blocks.push({ kind: 'ol', items: [numbered[1]] })
      i++; continue
    }
    blocks.push({ kind: 'p', text: line })
    i++
  }
  return blocks
}

export function Markdown({ source }: { source: string }) {
  return (
    <div className="md">
      {parse(source).map((block, index) => {
        switch (block.kind) {
          case 'h2': return <h4 key={index} className="md-h2">{inline(block.text)}</h4>
          case 'h3': return <h5 key={index} className="md-h3">{inline(block.text)}</h5>
          case 'quote': return <blockquote key={index} className="md-quote">{inline(block.text)}</blockquote>
          case 'hr': return <hr key={index} className="md-hr" />
          case 'ul': return <ul key={index} className="md-list">{block.items.map((item, i) => <li key={i}>{inline(item)}</li>)}</ul>
          case 'ol': return <ol key={index} className="md-list">{block.items.map((item, i) => <li key={i}>{inline(item)}</li>)}</ol>
          case 'table': return (
            <div key={index} className="md-table-wrap">
              <table className="table md-table">
                <thead><tr>{block.header.map((cell, c) => <th key={c}>{inline(cell)}</th>)}</tr></thead>
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r}>{row.map((cell, c) => <td key={c}>{inline(cell)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
          default: return <p key={index} className="md-p">{inline(block.text)}</p>
        }
      })}
    </div>
  )
}

import type { ReactNode } from 'react'

/** Small Markdown renderer for agent replies: paragraphs, lists, tables, **bold**, `code`, <br>.
 *  Builds React elements only (no innerHTML), so agent text can never inject markup. */
export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, '').split('\n')
  const out: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows: string[][] = []
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        if (!/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().slice(1, -1).split('|').map((c) => c.trim()))
        i++
      }
      const [head, ...body] = rows
      out.push(
        <div className="md-table" key={out.length}><table>
          <thead><tr>{head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
          <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody>
        </table></div>)
      continue
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const items: string[] = []
      const ordered = /^\s*\d/.test(line)
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*•]|\d+[.)])\s+/, ''))
      const L = ordered ? 'ol' : 'ul'
      out.push(<L key={out.length}>{items.map((t, j) => <li key={j}>{inline(t)}</li>)}</L>)
      continue
    }
    const h = line.match(/^#{1,4}\s+(.*)/)
    if (h) { out.push(<p key={out.length}><b>{inline(h[1])}</b></p>); i++; continue }
    if (!line.trim()) { i++; continue }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !/^\s*(\||[-*•]\s|\d+[.)]\s|#)/.test(lines[i])) para.push(lines[i++])
    if (!para.length) para.push(lines[i++])
    out.push(<p key={out.length}>{para.map((p, j) => <span key={j}>{j > 0 && <br />}{inline(p)}</span>)}</p>)
  }
  return <div className="md">{out}</div>
}

function inline(s: string): ReactNode[] {
  return s.split(/(<br\s*\/?>|\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((part, k) => {
    if (/^<br/i.test(part)) return <br key={k} />
    if (part.startsWith('**')) return <b key={k}>{part.slice(2, -2)}</b>
    if (part.startsWith('`')) return <code key={k}>{part.slice(1, -1)}</code>
    return part
  })
}

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type Row } from '../api'
import { MpBadge, PageHead, toast, useLoad } from '../components/ui'

export default function TemplateEdit() {
  const { id } = useParams()
  const meta = useLoad<Row>(() => api.get('/api/fields'))
  const [t, setT] = useState<Row | null>(null)
  const [layout, setLayout] = useState<Row>({})
  const [filter, setFilter] = useState<'all' | 'mapped' | 'unmapped' | 'dropdown'>('all')
  const [openMap, setOpenMap] = useState<string | null>(null)

  useEffect(() => {
    api.get(`/api/templates/${id}`).then((d) => { setT(d); setLayout({ sheet_name: d.sheet_name, header_row: d.header_row, data_start_row: d.data_start_row }) }).catch(toast.err)
  }, [id])
  if (!t || !meta.data) return null

  const sources: Row[] = meta.data.sources
  const groups = [...new Set(sources.map((s) => s.group))]
  const setMap = (letter: string, patch: Row) => setT({ ...t, mapping: { ...t.mapping, [letter]: { ...t.mapping[letter], ...patch } } })
  const save = async () => {
    try { const r = await api.put(`/api/templates/${id}`, { mapping: t.mapping, name: t.name }); setT({ ...t, ...r }); toast.ok('Mapping saved') } catch (e) { toast.err(e) }
  }
  const relayout = async () => {
    try { const r = await api.post(`/api/templates/${id}/layout`, layout); setT(r); toast.ok('Columns re-read') } catch (e) { toast.err(e) }
  }
  const cols = (t.columns as Row[]).filter((c) => {
    const m = t.mapping[c.letter]
    if (filter === 'mapped') return !!m?.source
    if (filter === 'unmapped') return !m?.source
    if (filter === 'dropdown') return c.allowed?.length
    return true
  })
  const mapped = (t.columns as Row[]).filter((c) => t.mapping[c.letter]?.source).length

  return (
    <>
      <PageHead title={t.name} sub={<><MpBadge mp={t.marketplace} /> {t.original_filename} · {mapped} of {t.columns.length} columns filled</>}>
        <Link className="btn" to="/templates">Back</Link>
        <button className="primary" onClick={save}>Save mapping</button>
      </PageHead>
      <div className="card">
        <h2>Where the data goes</h2>
        <div className="row">
          <div style={{ width: 220 }}><label>Sheet</label><select value={layout.sheet_name} onChange={(e) => setLayout({ ...layout, sheet_name: e.target.value })}>
            {t.sheets?.map((s: string) => <option key={s}>{s}</option>)}</select></div>
          <div style={{ width: 120 }}><label>Header row</label><input type="number" value={layout.header_row} onChange={(e) => setLayout({ ...layout, header_row: Number(e.target.value) })} /></div>
          <div style={{ width: 140 }}><label>First data row</label><input type="number" value={layout.data_start_row} onChange={(e) => setLayout({ ...layout, data_start_row: Number(e.target.value) })} /></div>
          <div style={{ alignSelf: 'flex-end' }}><button onClick={relayout}>Apply</button></div>
        </div>
        <p className="muted small" style={{ marginTop: 8 }}>These were detected automatically. Change them only if the columns below look wrong, e.g. if example rows sit under the header.</p>
      </div>
      <div className="row" style={{ marginBottom: 10 }}>
        {(['all', 'unmapped', 'mapped', 'dropdown'] as const).map((f) => <button key={f} className={filter === f ? 'primary' : ''} onClick={() => setFilter(f)}>
          {f === 'dropdown' ? 'With dropdowns' : f[0].toUpperCase() + f.slice(1)}</button>)}
      </div>
      <div className="table-wrap"><table>
        <thead><tr><th>Col</th><th>Template column</th><th style={{ width: 320 }}>Fill with</th><th>Dropdown</th><th /></tr></thead>
        <tbody>{cols.map((c) => {
          const m = t.mapping[c.letter] || { source: '', value: '', value_map: {} }
          return (
            <tr key={c.letter}>
              <td className="muted">{c.letter}</td>
              <td>{c.label && c.label !== c.header ? <><b>{c.label}</b><div className="muted small">{c.header}</div></> : <b>{c.header}</b>}</td>
              <td>
                <select value={m.source || ''} onChange={(e) => setMap(c.letter, { source: e.target.value })}>
                  <option value="">— leave blank —</option>
                  {groups.map((g) => <optgroup key={g} label={g}>{sources.filter((s) => s.group === g).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</optgroup>)}
                </select>
                {m.source === 'const.custom' && (c.allowed?.length
                  ? <select style={{ marginTop: 6 }} value={m.value || ''} onChange={(e) => setMap(c.letter, { value: e.target.value })}><option value="">Choose…</option>{c.allowed.map((a: string) => <option key={a}>{a}</option>)}</select>
                  : <input style={{ marginTop: 6 }} placeholder="Value for every row" value={m.value || ''} onChange={(e) => setMap(c.letter, { value: e.target.value })} />)}
              </td>
              <td className="small muted">{c.allowed?.length ? `${c.allowed.length} values` : '—'}</td>
              <td className="num">{m.source && m.source !== 'const.custom' && <button className="ghost" onClick={() => setOpenMap(openMap === c.letter ? null : c.letter)}>
                Translate values{Object.keys(m.value_map || {}).length ? ` (${Object.keys(m.value_map).length})` : ''}</button>}
                {openMap === c.letter && <ValueMap value={m.value_map || {}} allowed={c.allowed || []} onChange={(vm) => setMap(c.letter, { value_map: vm })} />}
              </td>
            </tr>
          )
        })}</tbody>
      </table></div>
    </>
  )
}

function ValueMap({ value, allowed, onChange }: { value: Record<string, string>; allowed: string[]; onChange: (v: Record<string, string>) => void }) {
  const [text, setText] = useState(Object.entries(value).map(([k, v]) => `${k} = ${v}`).join('\n'))
  const apply = (s: string) => {
    setText(s)
    const out: Record<string, string> = {}
    s.split('\n').forEach((line) => { const [a, ...b] = line.split('='); if (a?.trim() && b.length) out[a.trim()] = b.join('=').trim() })
    onChange(out)
  }
  return (
    <div style={{ textAlign: 'left', marginTop: 6, width: 300, marginLeft: 'auto' }}>
      <textarea rows={4} placeholder={'Your value = template value\nUnstitched Blouse Piece = Separate Blouse Piece'} value={text} onChange={(e) => apply(e.target.value)} />
      {allowed.length > 0 && <div className="help">Allowed: {allowed.slice(0, 20).join(', ')}{allowed.length > 20 ? '…' : ''}</div>}
    </div>
  )
}

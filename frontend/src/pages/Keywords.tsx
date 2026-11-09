import { useState } from 'react'
import { api, MARKETPLACES, MP_LABEL, type Row } from '../api'
import { Empty, Modal, PageHead, toast, useLoad } from '../components/ui'

const blank = { name: '', match_terms: '', primary_keywords: '', secondary_keywords: '', long_tail: '', notes: '' }

export default function Keywords() {
  const { data, reload } = useLoad<Row[]>(() => api.get('/api/keyword-sets'))
  const [edit, setEdit] = useState<Row | null>(null)
  const blocked = useLoad<Row[]>(() => api.get('/api/blocked-terms'))
  const [bt, setBt] = useState({ term: '', replacement: '', marketplace: 'all' })
  const addBlocked = async () => {
    try { await api.post('/api/blocked-terms', bt); setBt({ ...bt, term: '', replacement: '' }); blocked.reload(); toast.ok('Added') } catch (e) { toast.err(e) }
  }
  const save = async () => {
    try {
      if (edit!.id) await api.put(`/api/keyword-sets/${edit!.id}`, edit)
      else await api.post('/api/keyword-sets', edit)
      setEdit(null); reload(); toast.ok('Saved')
    } catch (e) { toast.err(e) }
  }
  return (
    <>
      <PageHead title="3. SEO keywords" sub="One keyword plan per saree type. AI drafts use it: primary words go in the title, secondary in highlights and bullets, long-tail in search terms.">
        <button className="primary" onClick={() => setEdit({ ...blank })}>Add keyword set</button>
      </PageHead>
      <div className="notice info">
        Where to find keywords: type the saree type into each marketplace's search bar and note the suggestions. Read the top 10 competitor titles. If you have Amazon Brand Registry, use Brand Analytics → Search Query Performance.
      </div>
      {data?.length === 0 ? <div className="card"><Empty>No keyword sets yet. Start with your best-selling saree type.</Empty></div> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Name</th><th>Applies when fabric/type contains</th><th>Primary</th><th>Secondary</th><th /></tr></thead>
          <tbody>{data?.map((k) => (
            <tr key={k.id} className="clickable" onClick={() => setEdit(k)}><td><b>{k.name}</b></td><td className="small">{k.match_terms}</td>
              <td className="small">{k.primary_keywords}</td><td className="small muted">{k.secondary_keywords}</td>
              <td className="num"><button className="ghost danger" onClick={async (e) => { e.stopPropagation(); if (confirm('Delete?')) { await api.del(`/api/keyword-sets/${k.id}`); reload() } }}>Delete</button></td></tr>
          ))}</tbody>
        </table></div>
      )}
      <div className="card">
        <h2>Blocked words</h2>
        <p className="muted small">Words a marketplace flags as look-alikes of authorised brands or restricted products (for example a design name). They are swapped for your replacement, or removed, in titles, highlights, bullets, descriptions and search terms whenever a listing is exported or filled by the extension. The SEO check also warns about them.</p>
        <div className="row">
          <input placeholder="Flagged word or phrase" value={bt.term} onChange={(e) => setBt({ ...bt, term: e.target.value })} />
          <input placeholder="Replace with (blank = remove)" value={bt.replacement} onChange={(e) => setBt({ ...bt, replacement: e.target.value })} />
          <select value={bt.marketplace} onChange={(e) => setBt({ ...bt, marketplace: e.target.value })}>
            <option value="all">All marketplaces</option>
            {MARKETPLACES.map((m) => <option key={m} value={m}>{MP_LABEL[m]}</option>)}
          </select>
          <button className="primary" disabled={!bt.term.trim()} onClick={addBlocked}>Add</button>
        </div>
        {blocked.data?.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Word</th><th>Replaced with</th><th>Where</th><th /></tr></thead>
            <tbody>{blocked.data.map((b) => (
              <tr key={b.id}><td><b>{b.term}</b></td><td>{b.replacement || <span className="muted">removed</span>}</td>
                <td>{b.marketplace === 'all' ? 'All' : MP_LABEL[b.marketplace as keyof typeof MP_LABEL]}</td>
                <td className="num"><button className="ghost danger" onClick={async () => { await api.del(`/api/blocked-terms/${b.id}`); blocked.reload() }}>Remove</button></td></tr>
            ))}</tbody>
          </table></div>
        ) : <Empty>No blocked words yet.</Empty>}
      </div>
      {edit && (
        <Modal title={edit.id ? 'Edit keyword set' : 'New keyword set'} onClose={() => setEdit(null)}>
          {([['name', 'Name', 'Kanjivaram silk'], ['match_terms', 'Applies to products whose fabric / type contains (comma separated)', 'kanjivaram, kanchipuram, kanchi'],
            ['primary_keywords', 'Primary keywords (title)', 'kanjivaram silk saree, kanchipuram saree'],
            ['secondary_keywords', 'Secondary keywords (highlights, bullets)', 'zari border, pure zari, wedding saree, bridal'],
            ['long_tail', 'Long-tail (backend search terms)', 'pattu saree, south indian wedding saree, silk sari for women with blouse'],
            ['notes', 'Notes', '']] as const).map(([k, label, ph]) => (
            <div className="field" key={k}><label>{label}</label>
              {k === 'name' || k === 'match_terms' ? <input value={edit[k] || ''} placeholder={ph} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />
                : <textarea rows={2} value={edit[k] || ''} placeholder={ph} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />}</div>
          ))}
          <div className="row"><span className="spacer" /><button onClick={() => setEdit(null)}>Cancel</button><button className="primary" disabled={!edit.name} onClick={save}>Save</button></div>
        </Modal>
      )}
    </>
  )
}

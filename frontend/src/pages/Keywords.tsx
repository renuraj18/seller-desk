import { useState } from 'react'
import { api, type Row } from '../api'
import { Empty, Modal, PageHead, toast, useLoad } from '../components/ui'

const blank = { name: '', match_terms: '', primary_keywords: '', secondary_keywords: '', long_tail: '', notes: '' }

export default function Keywords() {
  const { data, reload } = useLoad<Row[]>(() => api.get('/api/keyword-sets'))
  const [edit, setEdit] = useState<Row | null>(null)
  const save = async () => {
    try {
      if (edit!.id) await api.put(`/api/keyword-sets/${edit!.id}`, edit)
      else await api.post('/api/keyword-sets', edit)
      setEdit(null); reload(); toast.ok('Saved')
    } catch (e) { toast.err(e) }
  }
  return (
    <>
      <PageHead title="SEO keywords" sub="One keyword plan per saree type. AI drafts use it: primary words go in the title, secondary in highlights and bullets, long-tail in search terms.">
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

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, MARKETPLACES, money, MP_LABEL, type Marketplace, type Row } from '../api'
import { Empty, FileButton, Modal, PageHead, toast, useLoad } from '../components/ui'

export default function Products() {
  const [q, setQ] = useState('')
  const { data, reload } = useLoad<Row[]>(() => api.get(`/api/products?q=${encodeURIComponent(q)}`), [q])
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [aiOpen, setAiOpen] = useState(false)
  const [mps, setMps] = useState<Marketplace[]>(['amazon', 'flipkart', 'meesho'])
  const [running, setRunning] = useState(false)
  const nav = useNavigate()

  const toggle = (id: number) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allOn = !!data?.length && data.every((p) => sel.has(p.id))

  const importFile = async (f: File) => {
    try {
      const r = await api.upload('/api/products/import', f)
      toast.ok(`${r.created} created, ${r.updated} updated`)
      r.messages?.forEach((m: string) => toast.err(m))
      reload()
    } catch (e) { toast.err(e) }
  }
  const runAI = async () => {
    setRunning(true)
    try {
      const r = await api.post('/api/drafts/ai-bulk', { product_ids: [...sel], marketplaces: mps })
      toast.ok(`${r.drafted} listings drafted. Approved ones were kept.`)
      r.failed?.forEach((m: string) => toast.err(m))
      setAiOpen(false)
    } catch (e) { toast.err(e) } finally { setRunning(false) }
  }

  return (
    <>
      <PageHead title="Products" sub="Your saree master. Every account's listing links back to one product here.">
        <a className="btn" href="/api/products/import-template">Download import sheet</a>
        <FileButton label="Import Excel / CSV" accept=".xlsx,.csv" onFile={importFile} />
        <a className="btn" href="/api/products/export">Export all</a>
        <button className="primary" onClick={() => nav('/products/new')}>Add saree</button>
      </PageHead>
      <div className="row" style={{ marginBottom: 12 }}>
        <input style={{ width: 300 }} placeholder="Search SKU, name, fabric, colour" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="spacer" />
        {sel.size > 0 && <>
          <span className="muted">{sel.size} selected</span>
          <button className="primary" onClick={() => setAiOpen(true)}>✨ AI draft listings</button>
          <button onClick={() => nav(`/templates?products=${[...sel].join(',')}`)}>Fill a template</button>
        </>}
      </div>
      {data?.length === 0 ? <div className="card"><Empty>No products yet. Add one, import the sheet, or create them from <Link to="/matching">SKU matching</Link>.</Empty></div> : (
        <div className="table-wrap"><table>
          <thead><tr><th><input type="checkbox" checked={allOn} onChange={() => setSel(allOn ? new Set() : new Set(data!.map((p) => p.id)))} /></th>
            <th /><th>SKU</th><th>Saree</th><th>Colour</th><th className="num">MRP</th><th className="num">Base price</th><th className="num">Cost</th><th className="num">Stock</th><th className="num">Accounts</th></tr></thead>
          <tbody>{data?.map((p) => (
            <tr key={p.id} className="clickable" onClick={() => nav(`/products/${p.id}`)}>
              <td onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(p.id)} /></td>
              <td>{p.images?.[0] ? <img className="thumb" src={p.images[0]} alt="" /> : <div className="thumb" />}</td>
              <td><code>{p.sku}</code></td>
              <td>{[p.saree_type, p.fabric].filter(Boolean).join(' · ') || <span className="muted">—</span>}<div className="muted small">{p.name}</div></td>
              <td>{p.color || '—'}</td>
              <td className="num">{money(p.mrp)}</td><td className="num">{money(p.selling_price)}</td><td className="num">{money(p.cost_price)}</td>
              <td className="num">{p.stock_qty ?? '—'}</td><td className="num">{p.listing_count}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {aiOpen && (
        <Modal title={`AI draft for ${sel.size} product(s)`} onClose={() => !running && setAiOpen(false)}>
          <p className="small">Claude writes the title, highlights, bullets, description and keywords. It uses only your product data and the matching SEO keyword set. Marketplace limits are applied afterwards. Drafts you have approved are not overwritten.</p>
          <div className="row" style={{ margin: '10px 0 16px' }}>{MARKETPLACES.map((m) => (
            <label key={m} className="row" style={{ margin: 0, color: 'var(--ink)', fontSize: 14 }}>
              <input type="checkbox" checked={mps.includes(m)} onChange={() => setMps(mps.includes(m) ? mps.filter((x) => x !== m) : [...mps, m])} />{MP_LABEL[m]}</label>
          ))}</div>
          <p className="muted small">About {sel.size * mps.length} AI calls. Keep this page open.</p>
          <div className="row"><span className="spacer" /><button disabled={running} onClick={() => setAiOpen(false)}>Cancel</button>
            <button className="primary" disabled={running || !mps.length} onClick={runAI}>{running ? 'Drafting…' : 'Draft now'}</button></div>
        </Modal>
      )}
    </>
  )
}

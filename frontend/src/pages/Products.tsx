import { useEffect, useState } from 'react'
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
  const [addOpen, setAddOpen] = useState(false)
  const [linksOpen, setLinksOpen] = useState(false)
  const nav = useNavigate()

  const removeSarees = async (ids: number[]) => {
    const skus = (data || []).filter((p) => ids.includes(p.id)).map((p) => p.sku)
    const list = skus.length > 4 ? `${skus.slice(0, 4).join(', ')} and ${skus.length - 4} more` : skus.join(', ')
    if (!confirm(`Delete ${ids.length} saree(s) from Seller Desk?\n\n${list}\n\nTheir listings, content drafts and stock history here are deleted too. Past orders stay but lose the link. Nothing is removed from the marketplaces. This cannot be undone.`)) return
    try {
      const r = await api.post('/api/products/delete', { product_ids: ids })
      let deleted = r.deleted
      if (r.held_back.length) {
        const held = r.held_back.map((h: Row) => `${h.sku} (${h.listed_on.join(', ')})`).join('\n')
        if (confirm(`These are still exported or live on a marketplace:\n\n${held}\n\nDeleting them here does NOT take them off the marketplace. Delete them from Seller Desk anyway?`)) {
          deleted += (await api.post('/api/products/delete', { product_ids: r.held_back.map((h: Row) => h.id), force: true })).deleted
        }
      }
      toast.ok(`${deleted} saree(s) deleted`)
      setSel(new Set()); reload()
    } catch (e) { toast.err(e) }
  }
  const duplicate = async (p: Row) => {
    const sku = prompt(`SKU for the copy of ${p.sku}`, `${p.sku}-COPY`)?.trim()
    if (!sku) return
    try { const n = await api.post(`/api/products/${p.id}/duplicate?new_sku=${encodeURIComponent(sku)}`); toast.ok('Copied. Opening the copy'); nav(`/products/${n.id}`) } catch (e) { toast.err(e) }
  }

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
      <PageHead title="All sarees" sub={<>Your saree master, one row per colour. Every account's listing links back to one saree here. New catalog? <Link to="/new-catalog">See the steps</Link>.</>}>
        <a className="btn" href="/api/products/import-template">Download import sheet</a>
        <FileButton label="Import Excel / CSV" accept=".xlsx,.csv" onFile={importFile} />
        <a className="btn" href="/api/products/export">Export all</a>
        <button onClick={() => nav('/products/import-folder')}>Import photo folder</button>
        <button className="primary" onClick={() => nav('/products/new')}>Add saree</button>
      </PageHead>
      <div className="row" style={{ marginBottom: 12 }}>
        <input style={{ width: 300 }} placeholder="Search SKU, name, fabric, colour" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="spacer" />
        {sel.size > 0 && <>
          <span className="muted">{sel.size} selected</span>
          <button className="primary" onClick={() => setAddOpen(true)}>Add to accounts</button>
          <button onClick={() => setAiOpen(true)}>✨ AI draft listings</button>
          <button onClick={() => nav(`/templates?products=${[...sel].join(',')}`)}>Fill a template</button>
          <button onClick={() => setLinksOpen(true)} title="Image links from Meesho's Image link Generator, for its Excel sheet">Meesho image links</button>
          <button className="danger" onClick={() => removeSarees([...sel])}>Delete {sel.size}</button>
        </>}
      </div>
      {data?.length === 0 ? <div className="card"><Empty>No products yet. Add one, import the sheet, or create them from <Link to="/matching">SKU matching</Link>.</Empty></div> : (
        <div className="table-wrap"><table>
          <thead><tr><th><input type="checkbox" checked={allOn} onChange={() => setSel(allOn ? new Set() : new Set(data!.map((p) => p.id)))} /></th>
            <th /><th>SKU</th><th>Saree</th><th>Colour</th><th className="num">MRP</th><th className="num">Base price</th><th className="num">Cost</th><th className="num">Stock</th><th className="num">Accounts</th><th /></tr></thead>
          <tbody>{data?.map((p) => (
            <tr key={p.id} className="clickable" onClick={() => nav(`/products/${p.id}`)}>
              <td onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(p.id)} /></td>
              <td>{p.images?.[0] ? <img className="thumb" src={p.images[0]} alt="" /> : <div className="thumb" />}</td>
              <td><code>{p.sku}</code></td>
              <td>{[p.saree_type, p.fabric].filter(Boolean).join(' · ') || <span className="muted">—</span>}<div className="muted small">{p.name}{p.parent_sku && <span className="pill" style={{ marginLeft: 6 }}>group {p.parent_sku}</span>}</div></td>
              <td>{p.color || '—'}</td>
              <td className="num">{money(p.mrp)}</td><td className="num">{money(p.selling_price)}</td><td className="num">{money(p.cost_price)}</td>
              <td className="num">{p.stock_qty ?? '—'}</td><td className="num">{p.listing_count}</td>
              <td className="num" style={{ whiteSpace: 'nowrap' }} onClick={(e) => e.stopPropagation()}>
                <button className="ghost" onClick={() => duplicate(p)}>Duplicate</button>
                <button className="ghost danger" onClick={() => removeSarees([p.id])}>Delete</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {linksOpen && <ImageLinksModal products={(data || []).filter((p) => sel.has(p.id))} onClose={() => setLinksOpen(false)} />}
      {addOpen && <AddToAccounts productIds={[...sel]} onClose={(n) => { setAddOpen(false); if (n !== undefined) { setSel(new Set()); reload() } }} />}
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

function AddToAccounts({ productIds, onClose }: { productIds: number[]; onClose: (added?: number) => void }) {
  const accounts = useLoad<Row[]>(() => api.get('/api/accounts'))
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const firms = [...new Set((accounts.data || []).map((a) => a.firm_name))]
  const save = async () => {
    try {
      const r = await api.post('/api/listings/add-to-accounts', { product_ids: productIds, account_ids: [...chosen] })
      toast.ok(`${r.added} listing(s) queued (${r.products} sarees incl. colour variants). Open the extension on each portal to list them.`)
      onClose(r.added)
    } catch (e) { toast.err(e) }
  }
  return (
    <Modal title={`Add ${productIds.length} saree(s) to accounts`} onClose={() => onClose()}>
      <p className="small muted">They appear under <b>To list</b> in the browser extension for each account. Colour variants of the same design are included automatically.</p>
      {firms.map((f) => (
        <div key={f} style={{ marginBottom: 10 }}>
          <div className="row" style={{ marginBottom: 4 }}><b>{f}</b><span className="spacer" />
            <button className="ghost small" onClick={() => setChosen(new Set([...chosen, ...accounts.data!.filter((a) => a.firm_name === f).map((a) => a.id)]))}>all</button></div>
          {accounts.data!.filter((a) => a.firm_name === f).map((a) => (
            <label key={a.id} className="row" style={{ color: 'var(--ink)', fontSize: 14, margin: '4px 0' }}>
              <input type="checkbox" checked={chosen.has(a.id)} onChange={() => { const n = new Set(chosen); n.has(a.id) ? n.delete(a.id) : n.add(a.id); setChosen(n) }} />
              {MP_LABEL[a.marketplace as Marketplace]} · {a.name}</label>
          ))}
        </div>
      ))}
      <div className="row"><button className="ghost" onClick={() => setChosen(new Set((accounts.data || []).map((a) => a.id)))}>Select all {accounts.data?.length ?? ''}</button><span className="spacer" />
        <button onClick={() => onClose()}>Cancel</button><button className="primary" disabled={!chosen.size} onClick={save}>Add to {chosen.size} account(s)</button></div>
    </Modal>
  )
}

function ImageLinksModal({ products, onClose }: { products: Row[]; onClose: () => void }) {
  const sorted = [...products].sort((a, b) => a.sku.localeCompare(b.sku))
  const [links, setLinks] = useState<Record<number, string>>({})
  const [paste, setPaste] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api.get(`/api/image-links?marketplace=meesho&product_ids=${sorted.map((p) => p.id).join(',')}`).then((r) => {
      setLinks(Object.fromEntries(Object.entries(r.links as Record<string, string[]>).map(([k, v]) => [k, v.join('\n')])))
    }).catch((e) => toast.err(e))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const match = async () => {
    try {
      const r = await api.post('/api/image-links/paste', { marketplace: 'meesho', product_ids: sorted.map((p) => p.id), text: paste, save: false })
      setLinks((l) => ({ ...l, ...Object.fromEntries(Object.entries(r.links as Record<string, string[]>).map(([k, v]) => [k, v.join('\n')])) }))
      setNote(`Matched ${Object.keys(r.links).length} saree(s).${r.missing_blocks ? ` ${r.missing_blocks} saree(s) got no links.` : ''}${r.extra_blocks ? ` ${r.extra_blocks} extra block(s) were left over.` : ''}${r.unmatched_lines.length ? ` Ignored: ${r.unmatched_lines.slice(0, 3).join(' | ')}` : ''}`)
    } catch (e) { toast.err(e) }
  }
  const save = async () => {
    setBusy(true)
    try {
      for (const p of sorted) {
        const list = (links[p.id] || '').split(/\s+/).filter(Boolean)
        await api.put(`/api/products/${p.id}/image-links/meesho`, { links: list })
      }
      toast.ok('Image links saved. Fill the Meesho template again to use them.')
      onClose()
    } catch (e) { toast.err(e) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Meesho image links · ${sorted.length} saree(s)`} onClose={onClose} wide>
      <p className="small muted">In Meesho's supplier panel use <b>Images Bulk Upload</b> / <b>Image link generator</b> for these photos, then copy the links it shows. Links must be https (Google Drive links are rejected by Meesho). First link = Image 1 (front).</p>
      <div className="field"><label>Paste all links</label>
        <textarea rows={5} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder={'Either one block of links per saree, a blank line between blocks (in SKU order below),\nor a SKU line before its links:\nKOLAM-PEACH\nhttps://…/1.jpg\nhttps://…/2.jpg'} />
        <div className="row" style={{ marginTop: 6 }}><button onClick={match} disabled={!paste.trim()}>Match to sarees</button><span className="muted small">{note}</span></div></div>
      <div className="table-wrap" style={{ maxHeight: 340, overflow: 'auto' }}><table>
        <thead><tr><th /><th>SKU</th><th>Links (one per line)</th></tr></thead>
        <tbody>{sorted.map((p) => (
          <tr key={p.id}>
            <td>{p.images?.[0] ? <img className="thumb" src={p.images[0]} alt="" /> : <div className="thumb" />}</td>
            <td><code>{p.sku}</code><div className="muted small">{p.color}</div></td>
            <td><textarea rows={3} style={{ width: '100%' }} value={links[p.id] || ''} onChange={(e) => setLinks({ ...links, [p.id]: e.target.value })} /></td>
          </tr>
        ))}</tbody>
      </table></div>
      <div className="row" style={{ marginTop: 12 }}><span className="spacer" /><button onClick={onClose}>Cancel</button><button className="primary" disabled={busy} onClick={save}>Save links</button></div>
    </Modal>
  )
}

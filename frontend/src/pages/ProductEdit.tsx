import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, MARKETPLACES, money, MP_LABEL, type Marketplace, type Row } from '../api'
import { Counter, MpBadge, PageHead, Score, Status, toast, useLoad } from '../components/ui'

export default function ProductEdit() {
  const { id } = useParams()
  const isNew = id === 'new'
  const nav = useNavigate()
  const meta = useLoad<Row>(() => api.get('/api/fields'))
  const [p, setP] = useState<Row | null>(isNew ? { images: [], country_of_origin: 'India' } : null)
  const [tab, setTab] = useState<'details' | Marketplace | 'accounts'>('details')

  useEffect(() => {
    if (!isNew) api.get(`/api/products/${id}`).then(setP).catch(toast.err)
  }, [id, isNew])

  if (!p || !meta.data) return null
  const fields: Row[] = meta.data.product_fields
  const groups = [...new Set(fields.map((f) => f.group))]

  const save = async () => {
    try {
      const body = { ...p, images: Array.isArray(p.images) ? p.images : String(p.images || '').split('\n') }
      const saved = isNew ? await api.post('/api/products', body) : await api.put(`/api/products/${id}`, body)
      toast.ok('Saved')
      if (isNew) nav(`/products/${saved.id}`, { replace: true })
      else setP({ ...p, ...saved })
    } catch (e) { toast.err(e) }
  }
  const del = async () => {
    if (!confirm(`Delete ${p.sku}? Its listings in Seller Desk are removed too (nothing changes on the marketplaces).`)) return
    await api.del(`/api/products/${id}`); nav('/products')
  }
  const dup = async () => {
    const sku = prompt('SKU for the copy (e.g. next colour)')
    if (!sku) return
    try { const n = await api.post(`/api/products/${id}/duplicate?new_sku=${encodeURIComponent(sku)}`); nav(`/products/${n.id}`) } catch (e) { toast.err(e) }
  }

  const input = (f: Row) => {
    const v = p[f.key]
    const set = (val: unknown) => setP({ ...p, [f.key]: val })
    if (f.type === 'images') return <textarea rows={4} value={Array.isArray(v) ? v.join('\n') : v || ''} placeholder="https://…" onChange={(e) => set(e.target.value.split('\n'))} />
    if (f.type === 'textarea') return <textarea value={v || ''} onChange={(e) => set(e.target.value)} />
    if (f.type === 'number') return <input type="number" step="any" value={v ?? ''} onChange={(e) => set(e.target.value === '' ? null : Number(e.target.value))} />
    return <>
      <input list={f.options ? `opt-${f.key}` : undefined} value={v || ''} onChange={(e) => set(e.target.value)} />
      {f.options && <datalist id={`opt-${f.key}`}>{f.options.map((o: string) => <option key={o} value={o} />)}</datalist>}
    </>
  }
  const margin = p.selling_price && p.cost_price ? p.selling_price - p.cost_price - (p.packaging_cost || 0) : null

  return (
    <>
      <PageHead title={isNew ? 'New saree' : p.sku} sub={!isNew && [p.saree_type, p.fabric, p.color].filter(Boolean).join(' · ')}>
        <Link className="btn" to="/products">Back</Link>
        {!isNew && <button onClick={dup}>Duplicate</button>}
        {!isNew && <button className="danger" onClick={del}>Delete</button>}
        {tab === 'details' && <button className="primary" onClick={save}>Save</button>}
      </PageHead>
      {!isNew && (
        <div className="tabs">
          <button className={tab === 'details' ? 'on' : ''} onClick={() => setTab('details')}>Details</button>
          {MARKETPLACES.map((m) => <button key={m} className={tab === m ? 'on' : ''} onClick={() => setTab(m)}>{MP_LABEL[m]} listing</button>)}
          <button className={tab === 'accounts' ? 'on' : ''} onClick={() => setTab('accounts')}>Accounts ({p.listings?.length || 0})</button>
        </div>
      )}
      {tab === 'details' && (
        <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) 260px', alignItems: 'start' }}>
          <div>{groups.map((g) => (
            <div className="card" key={g}><h2>{g}</h2>
              <div className="form-grid">{fields.filter((f) => f.group === g).map((f) => (
                <div className="field" key={f.key} style={f.type === 'textarea' || f.type === 'images' ? { gridColumn: '1 / -1' } : undefined}>
                  <label>{f.label}{f.required && ' *'}</label>{input(f)}{f.help && <div className="help">{f.help}</div>}
                </div>
              ))}</div>
            </div>
          ))}</div>
          <div className="card" style={{ position: 'sticky', top: 16 }}>
            <h2>Preview</h2>
            {(p.images || []).filter(Boolean)[0] ? <img src={p.images.filter(Boolean)[0]} alt="" style={{ width: '100%', borderRadius: 8, marginBottom: 10 }} /> : <div className="empty small">No image</div>}
            <div className="small">Base price {money(p.selling_price)} · MRP {money(p.mrp)}</div>
            {margin !== null && <div className="small" style={{ marginTop: 4 }}>Gross margin before fees: <b>{money(margin)}</b></div>}
            <div className="small muted" style={{ marginTop: 8 }}>{(p.images || []).filter(Boolean).length} images · aim for 6+</div>
          </div>
        </div>
      )}
      {MARKETPLACES.includes(tab as Marketplace) && <ContentEditor productId={Number(id)} marketplace={tab as Marketplace} />}
      {tab === 'accounts' && (
        <div className="table-wrap"><table>
          <thead><tr><th>Account</th><th>SKU there</th><th>ASIN / FSN / ID</th><th className="num">Price</th><th className="num">Stock</th><th>Status</th></tr></thead>
          <tbody>{p.listings?.map((l: Row) => (
            <tr key={l.id}><td><MpBadge mp={l.marketplace} /> {l.account_name}</td><td><code>{l.marketplace_sku || '(prefix + SKU)'}</code></td><td>{l.listing_ref || '—'}</td>
              <td className="num">{money(l.price)}</td><td className="num">{l.stock_qty ?? '—'}</td><td><Status value={l.status} /></td></tr>
          ))}
          {!p.listings?.length && <tr><td colSpan={6} className="muted">Not on any account yet. Add it from <Link to="/listings">Listings by account</Link> or export a template.</td></tr>}</tbody>
        </table></div>
      )}
    </>
  )
}

function ContentEditor({ productId, marketplace }: { productId: number; marketplace: Marketplace }) {
  const { data, reload } = useLoad<Row>(() => api.get(`/api/products/${productId}/drafts`), [productId])
  const [d, setD] = useState<Row | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (data) setD({ ...data.drafts[marketplace] }) }, [data, marketplace])
  if (!data || !d) return null
  const rules = d.rules

  const save = async (approved: boolean) => {
    try {
      const r = await api.put(`/api/products/${productId}/drafts/${marketplace}`, { ...d, approved })
      toast.ok(approved ? 'Approved — this text will be used in exports' : 'Saved'); setD({ ...r, rules, saved: true }); reload()
    } catch (e) { toast.err(e) }
  }
  const ai = async () => {
    setBusy(true)
    try { await api.post(`/api/products/${productId}/drafts/${marketplace}/ai`); toast.ok('AI draft ready — review and approve'); reload() }
    catch (e) { toast.err(e) } finally { setBusy(false) }
  }
  const reset = async () => { await api.del(`/api/products/${productId}/drafts/${marketplace}`); reload() }
  const bullets: string[] = [...(d.bullets || []), '', '', '', '', ''].slice(0, 5)

  return (
    <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) 280px', alignItems: 'start' }}>
      <div className="card">
        <div className="row" style={{ marginBottom: 14 }}>
          <MpBadge mp={marketplace} />
          <span className="pill">{d.saved ? (d.source === 'ai' ? 'AI draft' : 'Edited') : 'Auto (rules)'}</span>
          {d.approved ? <span className="status st-live">Approved</span> : null}
          <span className="spacer" />
          <button className="primary" disabled={busy || !data.ai_enabled} title={data.ai_enabled ? '' : 'Add your Anthropic API key in Settings'} onClick={ai}>{busy ? 'Writing…' : '✨ Draft with AI'}</button>
          {d.saved && <button className="ghost" onClick={reset}>Reset to auto</button>}
        </div>
        {!data.ai_enabled && <div className="notice">AI drafting is off. Add your Anthropic API key in <Link to="/settings">Settings</Link>.</div>}
        <div className="field"><label className="row">Title <span className="spacer" /><Counter n={(d.title || '').length} max={rules.title_max} /></label>
          <input value={d.title || ''} onChange={(e) => setD({ ...d, title: e.target.value })} />
          {marketplace === 'flipkart' && <div className="help">Flipkart builds the shop title from brand + attributes; this goes in model / style name.</div>}</div>
        {rules.highlights_max > 0 && (
          <div className="field"><label className="row">Item Highlights <span className="spacer" /><Counter n={(d.highlights || '').length} max={rules.highlights_max} /></label>
            <textarea rows={2} value={d.highlights || ''} onChange={(e) => setD({ ...d, highlights: e.target.value })} />
            <div className="help">Searchable, shown under the title. Put attributes here that aren't in the title.</div></div>
        )}
        {bullets.map((b, i) => (
          <div className="field" key={i}><label className="row">Bullet {i + 1} <span className="spacer" /><Counter n={b.length} max={rules.bullet_max} /></label>
            <textarea rows={2} value={b} onChange={(e) => { const n = [...bullets]; n[i] = e.target.value; setD({ ...d, bullets: n }) }} /></div>
        ))}
        <div className="field"><label className="row">Description <span className="spacer" /><span className="counter">{(d.description || '').length}</span></label>
          <textarea rows={6} value={d.description || ''} onChange={(e) => setD({ ...d, description: e.target.value })} /></div>
        <div className="field"><label className="row">Search keywords <span className="spacer" />
          {marketplace === 'amazon' ? <Counter n={new TextEncoder().encode(d.search_terms || '').length} max={rules.search_terms_max_bytes} /> : null}</label>
          <textarea rows={2} value={d.search_terms || ''} onChange={(e) => setD({ ...d, search_terms: e.target.value })} /></div>
        <div className="row"><span className="spacer" /><button onClick={() => save(false)}>Save draft</button><button className="primary" onClick={() => save(true)}>Approve</button></div>
      </div>
      <div className="card" style={{ position: 'sticky', top: 16 }}>
        <div className="row"><h2 style={{ margin: 0 }}>SEO check</h2><span className="spacer" /><Score value={d.score} /></div>
        {d.issues?.length ? <ul className="issues">{d.issues.map((i: string) => <li key={i}>{i}</li>)}</ul> : <p className="small" style={{ color: 'var(--ok)', marginTop: 8 }}>No issues found.</p>}
        <p className="muted small" style={{ marginTop: 12 }}>The check updates after you save.</p>
        <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '14px 0' }} />
        <h3 style={{ marginBottom: 6 }}>Keyword set</h3>
        {data.keyword_set ? <div className="small"><b>{data.keyword_set.name}</b><div className="muted">Primary: {data.keyword_set.primary_keywords || '—'}</div></div>
          : <p className="small muted">No keyword set matches this saree's fabric or type. <Link to="/keywords">Add one</Link> for better SEO.</p>}
      </div>
    </div>
  )
}

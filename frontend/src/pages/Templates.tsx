import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, MARKETPLACES, MP_LABEL, type Marketplace, type Row } from '../api'
import { Empty, Modal, MpBadge, PageHead, toast, useLoad } from '../components/ui'

export default function Templates() {
  const { data, reload } = useLoad<Row[]>(() => api.get('/api/templates'))
  const exportsL = useLoad<Row[]>(() => api.get('/api/exports'))
  const [params] = useSearchParams()
  const preselected = (params.get('products') || '').split(',').filter(Boolean).map(Number)
  const [upload, setUpload] = useState<{ name: string; marketplace: Marketplace; file: File | null } | null>(null)
  const [exp, setExp] = useState<Row | null>(null)
  const nav = useNavigate()

  const doUpload = async () => {
    try {
      const r = await api.upload('/api/templates', upload!.file!, { name: upload!.name, marketplace: upload!.marketplace })
      toast.ok('Template read. Check the column mapping.')
      nav(`/templates/${r.id}`)
    } catch (e) { toast.err(e) }
  }

  return (
    <>
      <PageHead title="4b. Upload with an Excel template" sub={<>Upload the blank category sheet from a seller panel once. Seller Desk fills it for any account and sarees, and you upload the file yourself. To fill the portal form directly instead, use <Link to="/uploads">4a. Upload with extension</Link>.</>}>
        <button className="primary" onClick={() => setUpload({ name: '', marketplace: 'meesho', file: null })}>Add template</button>
      </PageHead>
      {preselected.length > 0 && <div className="notice info">{preselected.length} products selected. Choose a template below and click <b>Fill</b>.</div>}
      <div className="card">
        <h2>Templates</h2>
        {data?.length === 0 ? <Empty>No templates yet. Download them here:
          <ul style={{ textAlign: 'left', display: 'inline-block', marginTop: 10 }}>
            <li><b>Flipkart</b>: Seller Hub → Listings → Add new listings → Bulk upload → choose Saree vertical → download</li>
            <li><b>Meesho</b>: Supplier Panel → Catalog Uploads → Bulk Upload → choose Saree category → download template</li>
            <li><b>Amazon</b>: Seller Central → Catalog → Add Products via Upload → download the Saree template (only needed as a backup to the API)</li>
          </ul></Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Name</th><th>Marketplace</th><th>File</th><th>Sheet / rows</th><th className="num">Mapped</th><th /></tr></thead>
            <tbody>{data?.map((t) => (
              <tr key={t.id}>
                <td><Link to={`/templates/${t.id}`}>{t.name}</Link></td><td><MpBadge mp={t.marketplace} /></td><td className="small muted">{t.original_filename}</td>
                <td className="small">{t.sheet_name} · header {t.header_row} · data from {t.data_start_row}</td>
                <td className="num">{t.mapped_count}/{t.column_count}</td>
                <td className="num"><div className="actions" style={{ justifyContent: 'flex-end' }}>
                  <Link className="btn" to={`/templates/${t.id}`}>Mapping</Link>
                  <button className="primary" onClick={() => setExp(t)}>Fill</button>
                  <button className="ghost" title="Fill columns from what was learned on the live form" onClick={async () => { try { const r = await api.post(`/api/templates/${t.id}/apply-learned`); toast.ok(`${r.applied} columns mapped from learned fields`); reload() } catch (e) { toast.err(e) } }}>Apply learned</button>
                  <button className="ghost danger" onClick={async () => { if (confirm('Delete template?')) { await api.del(`/api/templates/${t.id}`); reload() } }}>Delete</button>
                </div></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      <div className="card">
        <h2>Generated files</h2>
        {exportsL.data?.length === 0 ? <p className="muted">Nothing generated yet.</p> : (
          <div className="table-wrap"><table>
            <thead><tr><th>When</th><th>Account</th><th>Template</th><th className="num">Products</th><th className="num">Warnings</th><th /></tr></thead>
            <tbody>{exportsL.data?.map((e) => (
              <tr key={e.id}><td className="small">{new Date(e.created_at + 'Z').toLocaleString('en-IN')}</td><td>{e.marketplace && <MpBadge mp={e.marketplace} />} {e.account_name}</td>
                <td>{e.template_name}</td><td className="num">{e.product_count}</td><td className="num">{e.warning_count || '—'}</td>
                <td className="num"><a className="btn" href={`/api/exports/${e.id}/download`}>Download</a></td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      {upload && (
        <Modal title="Add template" onClose={() => setUpload(null)}>
          <div className="field"><label>Marketplace</label><select value={upload.marketplace} onChange={(e) => setUpload({ ...upload, marketplace: e.target.value as Marketplace })}>
            {MARKETPLACES.map((m) => <option key={m} value={m}>{MP_LABEL[m]}</option>)}</select></div>
          <div className="field"><label>Name</label><input value={upload.name} placeholder="e.g. Meesho Sarees" onChange={(e) => setUpload({ ...upload, name: e.target.value })} /></div>
          <div className="field"><label>Template file (.xlsx, .xlsm, .xls)</label><input type="file" accept=".xlsx,.xlsm,.xls" onChange={(e) => setUpload({ ...upload, file: e.target.files?.[0] || null })} /></div>
          <div className="row"><span className="spacer" /><button onClick={() => setUpload(null)}>Cancel</button>
            <button className="primary" disabled={!upload.file || !upload.name} onClick={doUpload}>Upload &amp; read</button></div>
        </Modal>
      )}
      {exp && <ExportModal template={exp} preselected={preselected} onClose={() => { setExp(null); exportsL.reload() }} />}
    </>
  )
}

function ExportModal({ template, preselected, onClose }: { template: Row; preselected: number[]; onClose: () => void }) {
  const accounts = useLoad<Row[]>(() => api.get('/api/accounts'))
  const products = useLoad<Row[]>(() => api.get('/api/products?limit=5000'))
  const options = (accounts.data || []).filter((a) => a.marketplace === template.marketplace)
  const [accountId, setAccountId] = useState<number | null>(null)
  const [sel, setSel] = useState<Set<number>>(new Set(preselected))
  const [q, setQ] = useState('')
  const [result, setResult] = useState<Row | null>(null)
  const [busy, setBusy] = useState(false)
  const acc = accountId ?? options[0]?.id

  const run = async () => {
    setBusy(true)
    try { setResult(await api.post(`/api/templates/${template.id}/export`, { account_id: acc, product_ids: [...sel] })) }
    catch (e) { toast.err(e) } finally { setBusy(false) }
  }
  const list = (products.data || []).filter((p) => !q || `${p.sku} ${p.name || ''} ${p.fabric || ''} ${p.color || ''}`.toLowerCase().includes(q.toLowerCase()))

  return (
    <Modal title={`Fill: ${template.name}`} onClose={onClose} wide>
      {result ? <>
        <p>Filled <b>{result.product_count}</b> products into <code>{result.filename}</code>.</p>
        {result.warnings.length > 0 ? <>
          <div className="notice">{result.warnings.length} value{result.warnings.length === 1 ? '' : 's'} don't match the template's dropdowns. Fix them in the product, or add a value translation on the mapping page, before uploading.</div>
          <div className="table-wrap" style={{ maxHeight: 260, overflowY: 'auto' }}><table>
            <thead><tr><th>SKU</th><th>Column</th><th>Value</th><th>Allowed (sample)</th></tr></thead>
            <tbody>{result.warnings.map((w: Row, i: number) => <tr key={i}><td><code>{w.sku}</code></td><td>{w.column}</td><td>{w.value}</td><td className="small muted">{w.allowed_sample.join(', ')}</td></tr>)}</tbody>
          </table></div></> : <p style={{ color: 'var(--ok)' }}>All dropdown values matched.</p>}
        <div className="row" style={{ marginTop: 14 }}><span className="spacer" /><button onClick={onClose}>Close</button><a className="btn primary" href={`/api/exports/${result.export_id}/download`}>Download file</a></div>
      </> : <>
        {options.length === 0 ? <div className="notice">No {MP_LABEL[template.marketplace as Marketplace]} account yet.</div> : (
          <div className="field"><label>Account</label><select value={acc} onChange={(e) => setAccountId(Number(e.target.value))}>
            {options.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.firm_name})</option>)}</select>
            <div className="help">SKU prefix, brand and price rule of this account are applied.</div></div>
        )}
        <div className="row" style={{ marginBottom: 8 }}>
          <input style={{ width: 260 }} placeholder="Filter products" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="ghost" onClick={() => setSel(new Set(list.map((p) => p.id)))}>Select shown</button>
          <button className="ghost" onClick={() => setSel(new Set())}>Clear</button><span className="spacer" /><span className="muted">{sel.size} selected</span>
        </div>
        <div className="table-wrap" style={{ maxHeight: 320, overflowY: 'auto' }}><table><tbody>
          {list.map((p) => <tr key={p.id} className="clickable" onClick={() => setSel((s) => { const n = new Set(s); n.has(p.id) ? n.delete(p.id) : n.add(p.id); return n })}>
            <td style={{ width: 30 }}><input type="checkbox" readOnly checked={sel.has(p.id)} /></td><td><code>{p.sku}</code></td><td className="small">{[p.saree_type, p.fabric, p.color].filter(Boolean).join(' · ')}</td></tr>)}
        </tbody></table></div>
        <div className="row" style={{ marginTop: 14 }}><span className="spacer" /><button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !acc || sel.size === 0} onClick={run}>{busy ? 'Filling…' : `Fill ${sel.size} products`}</button></div>
      </>}
    </Modal>
  )
}

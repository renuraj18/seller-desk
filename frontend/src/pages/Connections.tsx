import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Row } from '../api'
import { Empty, FileButton, Modal, MpBadge, PageHead, Status, toast, useLoad } from '../components/ui'

const HOW = {
  amazon: (
    <ol className="steps small">
      <li>Seller Central (Primary User login) → <b>Apps and Services → Develop Apps</b>. Register as a developer (private, for your own business) if asked.</li>
      <li>Add a new app client. Roles: <b>Product Listing</b>, <b>Inventory and Order Tracking</b>. Add <b>Finance and Accounting</b> now so P&amp;L works later.</li>
      <li>Copy the <b>LWA Client ID</b> and <b>Client Secret</b>.</li>
      <li>Click <b>Authorize app</b> for this Amazon account and copy the <b>refresh token</b>. Repeat Authorize for each Amazon account; the client ID and secret stay the same.</li>
    </ol>
  ),
  flipkart: (
    <ol className="steps small">
      <li>Seller Hub → <b>Manage Profile → Developer Access → Create New Access</b>.</li>
      <li>Choose <b>Self Access Application</b>, give it a name, submit.</li>
      <li>Copy the <b>Application ID</b> and <b>Application Secret</b>. Don't share them with anyone else.</li>
    </ol>
  ),
  meesho: (
    <ol className="steps small">
      <li>Meesho has no self-service seller API, so this account works with files.</li>
      <li>Supplier Panel → <b>Inventory</b> → download the inventory file.</li>
      <li>Click <b>Upload inventory file</b> here. Repeat whenever you want fresh stock and status.</li>
    </ol>
  ),
} as const

export default function Connections() {
  const { data, reload } = useLoad<Row>(() => api.get('/api/connections'))
  const [edit, setEdit] = useState<Row | null>(null)
  const [creds, setCreds] = useState<Row>({})
  const [busy, setBusy] = useState<number | null>(null)

  const running = data?.runs?.some((r: Row) => r.status === 'running')
  useEffect(() => {
    if (!running) return
    const t = setInterval(reload, 5000)
    return () => clearInterval(t)
  }, [running, reload])

  const openCreds = async (a: Row) => {
    setEdit(a)
    setCreds(await api.get(`/api/accounts/${a.id}/credentials`))
  }
  const saveCreds = async () => {
    try {
      await api.put(`/api/accounts/${edit!.id}/credentials`, creds)
      toast.ok('Saved (encrypted on this PC)')
      const r = await api.post(`/api/accounts/${edit!.id}/test`)
      r.ok ? toast.ok(r.message) : toast.err(r.message)
      setEdit(null); reload()
    } catch (e) { toast.err(e) }
  }
  const test = async (a: Row) => {
    setBusy(a.id)
    try { const r = await api.post(`/api/accounts/${a.id}/test`); r.ok ? toast.ok(r.message) : toast.err(r.message); reload() }
    catch (e) { toast.err(e) } finally { setBusy(null) }
  }
  const sync = async (a: Row) => {
    try { await api.post(`/api/accounts/${a.id}/sync`); toast.ok('Sync started — Amazon reports can take a few minutes'); reload() }
    catch (e) { toast.err(e) }
  }
  const upload = async (a: Row, f: File) => {
    setBusy(a.id)
    try { const r = await api.upload(`/api/accounts/${a.id}/inventory-file`, f); toast.ok(`${r.rows} listings read, ${r.matched} matched to products`); reload() }
    catch (e) { toast.err(e) } finally { setBusy(null) }
  }

  if (!data) return null
  return (
    <>
      <PageHead title="Connections & inventory sync" sub="Link each account, then bring its current listings in." />
      {data.accounts.length === 0 ? <div className="card"><Empty>Add accounts in <Link to="/setup">Firms &amp; accounts</Link> first.</Empty></div> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Account</th><th>Connection</th><th className="num">Listings found</th><th className="num">Unmatched</th><th>Last sync</th><th /></tr></thead>
          <tbody>{data.accounts.map((a: Row) => (
            <tr key={a.id}>
              <td><MpBadge mp={a.marketplace} /> {a.name}<div className="muted small">{a.firm_name}</div></td>
              <td>{a.marketplace === 'meesho' ? <span className="pill">File upload</span>
                : !a.has_credentials ? <span className="muted">Not connected</span>
                : <span title={a.last_test_message || ''}><Status value={a.last_test_ok ? 'active' : a.last_test_at ? 'failed' : 'untested'} /></span>}
              </td>
              <td className="num">{a.remote_count}</td>
              <td className="num">{a.unmatched ? <Link to={`/matching?account=${a.id}`}>{a.unmatched}</Link> : 0}</td>
              <td className="small muted">{a.last_sync ? new Date(a.last_sync + 'Z').toLocaleString('en-IN') : '—'}</td>
              <td className="num"><div className="actions" style={{ justifyContent: 'flex-end' }}>
                {a.marketplace !== 'meesho' && <button onClick={() => openCreds(a)}>{a.has_credentials ? 'Credentials' : 'Connect'}</button>}
                {a.marketplace !== 'meesho' && !!a.has_credentials && <button disabled={busy === a.id} onClick={() => test(a)}>Test</button>}
                {a.marketplace !== 'meesho' && !!a.has_credentials && <button className="primary" onClick={() => sync(a)}>Sync inventory</button>}
                <FileButton label={a.marketplace === 'meesho' ? 'Upload inventory file' : 'Upload file'} className={a.marketplace === 'meesho' ? 'primary' : ''}
                  accept=".xlsx,.xls,.csv,.txt,.tsv" onFile={(f) => upload(a, f)} />
                {a.marketplace === 'meesho' && <button className="ghost" onClick={() => setEdit(a)}>How?</button>}
              </div></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Recent sync runs</h2>
        {data.runs.length === 0 ? <p className="muted">No syncs yet.</p> : (
          <div className="table-wrap"><table>
            <thead><tr><th>When</th><th>Account</th><th>Type</th><th>Status</th><th>Result</th></tr></thead>
            <tbody>{data.runs.map((r: Row) => {
              const a = data.accounts.find((x: Row) => x.id === r.account_id)
              return <tr key={r.id}><td className="small">{new Date(r.started_at + 'Z').toLocaleString('en-IN')}</td><td>{a?.name}</td>
                <td className="small">{r.kind === 'inventory_api' ? 'API' : 'File'}</td><td><Status value={r.status} /></td><td className="small">{r.message}</td></tr>
            })}</tbody>
          </table></div>
        )}
      </div>

      {edit && (
        <Modal title={`${edit.name} — ${edit.marketplace === 'meesho' ? 'how to sync' : 'connect'}`} onClose={() => setEdit(null)}>
          {HOW[edit.marketplace as keyof typeof HOW]}
          {edit.marketplace !== 'meesho' && <>
            <div style={{ marginTop: 14 }}>{data.credential_fields[edit.marketplace].map((f: Row) => (
              <div className="field" key={f.key}><label>{f.label}</label>
                <input type={f.secret ? 'password' : 'text'} value={creds[f.key] || ''} autoComplete="off"
                  onFocus={(e) => f.secret && String(e.target.value).startsWith('•') && setCreds({ ...creds, [f.key]: '' })}
                  onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })} /></div>
            ))}</div>
            <p className="muted small">Stored encrypted in this PC's database. Leave a secret blank to keep the saved one.</p>
            <div className="row"><span className="spacer" /><button onClick={() => setEdit(null)}>Cancel</button><button className="primary" onClick={saveCreds}>Save &amp; test</button></div>
          </>}
        </Modal>
      )}
    </>
  )
}

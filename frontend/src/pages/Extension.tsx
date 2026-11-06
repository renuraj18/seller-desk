import { api, MP_LABEL, type Marketplace, type Row } from '../api'
import { Empty, MpBadge, PageHead, toast, useLoad } from '../components/ui'

export default function Extension() {
  const fields = useLoad<Row[]>(() => api.get('/api/ext/fields'))
  const meta = useLoad<Row>(() => api.get('/api/fields'))
  const sourceLabel = (k: string) => meta.data?.sources.find((s: Row) => s.key === k)?.label || k

  const del = async (f: Row) => {
    try { await api.del(`/api/ext/fields/${f.id}`); fields.reload(); toast.ok('Removed') } catch (e) { toast.err(e) }
  }

  return (
    <>
      <PageHead title="Browser extension" sub="Fill Meesho, Flipkart and Amazon add-product forms from this catalogue, for any account and firm.">
        <a className="btn primary" href="/api/ext/download">Download extension</a>
        <a className="btn" href="/ext-demo?mp=meesho" target="_blank" rel="noreferrer">Open practice form</a>
      </PageHead>
      <div className="grid g2">
        <div className="card">
          <h2>Install (once per Chrome profile)</h2>
          <ol className="steps">
            <li>Click <b>Download extension</b> and unzip it into a folder you'll keep, e.g. <code>Documents\seller-desk-extension</code>.</li>
            <li>In Chrome open <code>chrome://extensions</code> and switch on <b>Developer mode</b> (top right).</li>
            <li>Click <b>Load unpacked</b> and choose the unzipped folder.</li>
            <li>Pin it from the puzzle-piece menu. Its popup should say <b>Connected</b> while Seller Desk is running.</li>
          </ol>
          <p className="muted small">Tip: use a separate Chrome profile for each firm so each stays logged in to its own Meesho, Flipkart and Amazon accounts. Install the extension in each profile.</p>
        </div>
        <div className="card">
          <h2>Listing one saree on every account</h2>
          <ol className="steps">
            <li>In <b>Products</b>, select sarees → <b>Add to accounts</b> → tick the accounts. They show under <b>To list</b> in the extension.</li>
            <li>Optional: <b>AI draft listings</b> and approve the text for each marketplace.</li>
            <li>Open the add-product page on the marketplace. Click <b>Seller Desk</b> (bottom right), choose the account, then the saree.</li>
            <li><b>Fill this page</b>, then <b>Attach images</b>. Check the form and submit it yourself on the marketplace.</li>
            <li>Click <b>I've submitted it ✓</b>. The saree is marked as exported for that account and the next one opens.</li>
          </ol>
          <p className="muted small">The extension never submits anything for you. You always review and click submit on the marketplace.</p>
        </div>
      </div>
      <div className="card">
        <h2>Taught fields</h2>
        <p className="muted small">When a field isn't recognised, click <b>Teach</b> in the extension. What you teach is saved here per marketplace and used for every account of both firms.</p>
        {fields.data?.length === 0 ? <Empty>Nothing taught yet.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Marketplace</th><th>Field on the form</th><th>Filled with</th><th>Translations</th><th /></tr></thead>
            <tbody>{fields.data?.map((f) => (
              <tr key={f.id}>
                <td><MpBadge mp={f.marketplace as Marketplace} /></td>
                <td><b>{f.label}</b></td>
                <td>{!f.source ? <span className="muted">Ignored</span> : f.source === 'const.custom' ? <>Fixed value: <code>{f.value}</code></> : sourceLabel(f.source)}</td>
                <td className="small">{Object.entries(f.value_map || {}).map(([a, b]) => `${a} → ${b}`).join(', ') || '—'}</td>
                <td className="num"><button className="ghost danger" onClick={() => del(f)}>Remove</button></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      <p className="muted small">Works on {Object.values(MP_LABEL).join(', ')} seller panels. Sites change their forms from time to time; when a field stops filling, teach it again.</p>
    </>
  )
}

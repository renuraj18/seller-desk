import { Link } from 'react-router-dom'
import { api, type Row } from '../api'
import { Empty, MpBadge, PageHead, useLoad } from '../components/ui'

export default function Dashboard() {
  const { data } = useLoad<Row>(() => api.get('/api/dashboard'))
  const check = useLoad<Row>(() => api.get('/api/daily-check'))
  if (!data) return null
  const firstRun = data.accounts === 0
  return (
    <>
      <PageHead title="Dashboard" sub="All firms and marketplace accounts at a glance" />
      {firstRun && (
        <div className="card">
          <h2>Get started</h2>
          <ol className="steps">
            <li><Link to="/setup">Add your 2 firms and 6 marketplace accounts</Link></li>
            <li><Link to="/connections">Connect Amazon and Flipkart</Link>, then sync inventory. For Meesho, upload the Inventory download.</li>
            <li><Link to="/matching">Match marketplace SKUs</Link> to master products, or create products from them.</li>
            <li><Link to="/settings">Add your Anthropic API key</Link> and set up <Link to="/keywords">SEO keyword sets</Link>.</li>
            <li>Draft listings with AI, then <Link to="/templates">fill the Flipkart / Meesho / Amazon templates</Link>.</li>
          </ol>
        </div>
      )}
      {check.data && check.data.accounts.length > 0 && (
        <div className="card">
          <div className="row"><h2 style={{ margin: 0 }}>Daily order check</h2><span className="spacer" /><Link to="/daily-check">Open</Link></div>
          <div className="row" style={{ margin: '8px 0' }}>
            <span className="stat">{check.data.accounts.reduce((n: number, a: Row) => n + a.pending, 0)}</span><span className="muted">pending orders across {check.data.accounts.length} accounts</span>
          </div>
          {check.data.attention.length === 0 ? <span className="muted">Nothing needs attention.</span> : check.data.attention.slice(0, 4).map((a: Row, i: number) => (
            <div key={i} className="small" style={{ padding: '3px 0' }}><b>{a.account}</b>: {a.text}</div>
          ))}
        </div>
      )}
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <div className="card"><div className="muted">Products</div><div className="stat">{data.products}</div></div>
        <div className="card"><div className="muted">Listings (all accounts)</div><div className="stat">{data.listings}</div></div>
        <div className="card"><div className="muted">Accounts</div><div className="stat">{data.accounts}</div><div className="muted small">{data.firms} firms</div></div>
        <div className="card">
          <div className="muted">Products missing key data</div>
          <div className="stat" style={{ color: data.incomplete_products ? 'var(--warn)' : undefined }}>{data.incomplete_products}</div>
          <div className="muted small">fabric, colour, MRP, price, HSN or images</div>
        </div>
      </div>
      <div className="card">
        <h2>Listings by account</h2>
        {data.by_account.length === 0 ? <Empty>No accounts yet.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Account</th><th>Firm</th><th className="num">Live</th><th className="num">Exported</th><th className="num">Draft</th><th className="num">Inactive / rejected</th></tr></thead>
            <tbody>{data.by_account.map((a: Row) => (
              <tr key={a.id}><td><MpBadge mp={a.marketplace} /> {a.name}</td><td>{a.firm_name}</td>
                <td className="num">{a.live ?? 0}</td><td className="num">{a.exported ?? 0}</td><td className="num">{a.draft ?? 0}</td><td className="num">{a.other ?? 0}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
    </>
  )
}

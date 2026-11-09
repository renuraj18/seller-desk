import { Link } from 'react-router-dom'
import { api, type Row } from '../api'
import { PageHead, useLoad } from '../components/ui'

type Step = { n: number; title: string; what: string; status: string; ok: boolean; links: [string, string][] }

export default function NewCatalog() {
  const defaults = useLoad<Row[]>(() => api.get('/api/product-templates'))
  const products = useLoad<Row[]>(() => api.get('/api/products?limit=5000'))
  const keywords = useLoad<Row[]>(() => api.get('/api/keyword-sets'))
  const uploads = useLoad<Row>(() => api.get('/api/uploads'))
  const excel = useLoad<Row[]>(() => api.get('/api/templates'))

  const nDefaults = defaults.data?.length ?? 0
  const withFolder = defaults.data?.filter((t) => t.variations_dir).length ?? 0
  const nProducts = products.data?.length ?? 0
  const nDrafts = products.data?.filter((p) => p.listing_count === 0).length ?? 0
  const q = uploads.data?.counts
  const taught = uploads.data?.accounts.filter((a: Row) => a.add_catalog_url).length ?? 0

  const steps: Step[] = [
    { n: 1, title: 'Product defaults', what: 'Shared facts for a kind of saree: fabric, HSN, GST, weight, blouse, wash care. You can also save the folder that holds its colour photos here.',
      status: `${nDefaults} saved, ${withFolder} with a photo folder`, ok: nDefaults > 0, links: [['/product-templates', 'Open product defaults']] },
    { n: 2, title: 'Add the sarees', what: 'One saree per colour. Add them from a photo folder, from Excel, by hand, or let Claude add every colour from the defaults\' photo folder.',
      status: `${nProducts} sarees, ${nDrafts} not on any account yet`, ok: nProducts > 0, links: [['/products/import-folder', 'Add from photo folder'], ['/products', 'See all sarees']] },
    { n: 3, title: 'SEO keywords and content', what: 'Keywords per saree type, then a title, bullets and description for each marketplace. Open a saree → Content to review and approve.',
      status: `${keywords.data?.length ?? 0} keyword sets`, ok: (keywords.data?.length ?? 0) > 0, links: [['/keywords', 'Keywords'], ['/products', 'Open a saree to approve content']] },
    { n: 4, title: 'Upload to the portals', what: 'Choose one: the browser extension fills each portal\'s add-catalog form for you, or Seller Desk fills the portal\'s Excel template for you to upload.',
      status: `${taught} account(s) ready for the extension, ${excel.data?.length ?? 0} Excel template(s); queue: ${q ? q.queued + q.filling + q.filled : 0} open`,
      ok: !!q && (q.submitted > 0), links: [['/uploads', 'Upload with the extension'], ['/templates', 'Upload with an Excel template']] },
    { n: 5, title: 'Track and stock', what: 'Check each account\'s listing status and SKU, then set the stock so every account matches.',
      status: '', ok: false, links: [['/listings', 'Listings by account'], ['/inventory', 'Inventory']] },
  ]

  return (
    <>
      <PageHead title="List new sarees" sub="The same five steps every time, in order. Each step opens the page where you do it." />
      <div className="card">
        {steps.map((s, i) => (
          <div key={s.n} className="row" style={{ padding: '12px 0', borderTop: i ? '1px solid var(--line)' : undefined, alignItems: 'flex-start', gap: 14 }}>
            <span className={`status ${s.ok ? 'st-live' : 'st-exported'}`} style={{ minWidth: 28, textAlign: 'center' }}>{s.n}</span>
            <div style={{ flex: 1 }}>
              <b>{s.title}</b>
              <div className="muted small" style={{ margin: '2px 0 6px' }}>{s.what}</div>
              {s.status && <div className="small">{s.status}</div>}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {s.links.map(([to, label], j) => <Link key={to} className={`btn${j === 0 ? ' primary' : ''}`} to={to} style={j === 0 ? { color: '#fff' } : undefined}>{label}</Link>)}
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <h2>Which page is which?</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>Page</th><th>What it is</th></tr></thead>
          <tbody>
            <tr><td><b>Products</b> (All sarees)</td><td>The list of your sarees, one row per colour. Everything else links back to it.</td></tr>
            <tr><td><b>Product defaults</b></td><td>Not sarees: reusable starting values for a kind of saree (HSN, GST, weight…) and its photo folder.</td></tr>
            <tr><td><b>Upload to portals</b></td><td>A queue. The browser extension opens the portal's add-catalog page and fills the form for each saree you queue.</td></tr>
            <tr><td><b>Excel upload templates</b></td><td>The blank sheet from a seller panel, with each column linked to a Seller Desk value. Seller Desk fills it; you upload the file yourself.</td></tr>
            <tr><td><b>Listings by account</b></td><td>After uploading: each saree's SKU, price and status per account.</td></tr>
          </tbody>
        </table></div>
      </div>

      <div className="card">
        <h2>Let Claude do steps 1 to 3</h2>
        <div className="muted small">With the Seller Desk MCP connected, ask Claude: <code>Use the new_saree_catalog prompt for Meesho: kolam sarees @899</code>.
          Claude researches, saves keywords, adds every colour from the defaults' photo folder, and writes content as drafts. You still approve content and do step 4.</div>
      </div>
    </>
  )
}

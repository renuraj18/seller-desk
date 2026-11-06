import { NavLink, Route, Routes } from 'react-router-dom'
import { Toasts } from './components/ui'
import Dashboard from './pages/Dashboard'
import Setup from './pages/Setup'
import Connections from './pages/Connections'
import Matching from './pages/Matching'
import Products from './pages/Products'
import ProductEdit from './pages/ProductEdit'
import Listings from './pages/Listings'
import Templates from './pages/Templates'
import TemplateEdit from './pages/TemplateEdit'
import Keywords from './pages/Keywords'
import Settings from './pages/Settings'
import Payments from './pages/Payments'

const NAV = [
  { group: 'Overview', items: [['/', 'Dashboard']] },
  { group: 'Catalog', items: [['/products', 'Products'], ['/keywords', 'SEO keywords'], ['/listings', 'Listings by account']] },
  { group: 'Marketplaces', items: [['/connections', 'Connections & sync'], ['/matching', 'SKU matching'], ['/templates', 'Upload templates']] },
  { group: 'Money', items: [['/payments', 'Payments & P&L']] },
  { group: 'Admin', items: [['/setup', 'Firms & accounts'], ['/settings', 'Settings']] },
]

export default function App() {
  return (
    <div className="app">
      <aside className="side">
        <div className="logo"><img src="/favicon.svg" alt="" />Seller Desk</div>
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="group">{g.group}</div>
            {g.items.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === '/'} className={to === '/payments' ? 'soon' : ''}>{label}</NavLink>
            ))}
          </div>
        ))}
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/connections" element={<Connections />} />
          <Route path="/matching" element={<Matching />} />
          <Route path="/products" element={<Products />} />
          <Route path="/products/:id" element={<ProductEdit />} />
          <Route path="/listings" element={<Listings />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/templates/:id" element={<TemplateEdit />} />
          <Route path="/keywords" element={<Keywords />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/payments" element={<Payments />} />
        </Routes>
      </main>
      <Toasts />
    </div>
  )
}

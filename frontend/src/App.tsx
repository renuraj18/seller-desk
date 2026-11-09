import { NavLink, Route, Routes } from 'react-router-dom'
import { Toasts } from './components/ui'
import Dashboard from './pages/Dashboard'
import Setup from './pages/Setup'
import Connections from './pages/Connections'
import Matching from './pages/Matching'
import Products from './pages/Products'
import ProductEdit from './pages/ProductEdit'
import ProductTemplates from './pages/ProductTemplates'
import Listings from './pages/Listings'
import Templates from './pages/Templates'
import TemplateEdit from './pages/TemplateEdit'
import Keywords from './pages/Keywords'
import Settings from './pages/Settings'
import Payments from './pages/Payments'
import Extension from './pages/Extension'
import Inventory from './pages/Inventory'
import ImportFolder from './pages/ImportFolder'
import Orders from './pages/Orders'
import Agents from './pages/Agents'
import DailyCheck from './pages/DailyCheck'
import Uploads from './pages/Uploads'
import NewCatalog from './pages/NewCatalog'

const NAV = [
  { group: 'Overview', items: [['/', 'Dashboard'], ['/daily-check', 'Daily order check'], ['/agents', 'Marketplace agents']] },
  { group: 'List new sarees', items: [['/new-catalog', 'How it works'], ['/product-templates', '1. Product defaults'], ['/products/import-folder', '2. Add from photo folder'], ['/keywords', '3. SEO keywords'], ['/uploads', '4a. Upload with extension'], ['/templates', '4b. Upload with Excel template']] },
  { group: 'My catalog', items: [['/products', 'All sarees'], ['/listings', 'Listings by account'], ['/inventory', 'Inventory'], ['/matching', 'SKU matching']] },
  { group: 'Orders & money', items: [['/orders', 'Orders & shipments'], ['/payments', 'Payments & P&L']] },
  { group: 'Connect', items: [['/extension', 'Browser extension'], ['/connections', 'Connections & sync']] },
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
              <NavLink key={to} to={to} end={to === '/' || to === '/products'} className={to === '/payments' ? 'soon' : ''}>{label}</NavLink>
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
          <Route path="/product-templates" element={<ProductTemplates />} />
          <Route path="/products/import-folder" element={<ImportFolder />} />
          <Route path="/products/:id" element={<ProductEdit />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/extension" element={<Extension />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/daily-check" element={<DailyCheck />} />
          <Route path="/uploads" element={<Uploads />} />
          <Route path="/new-catalog" element={<NewCatalog />} />
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

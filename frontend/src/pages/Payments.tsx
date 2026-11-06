import { PageHead } from '../components/ui'

export default function Payments() {
  return (
    <>
      <PageHead title="Payments & P&L" sub="Next phase" />
      <div className="card" style={{ maxWidth: 760 }}>
        <h2>What's coming</h2>
        <ul className="steps">
          <li>Import settlement / payment reports for each account (Amazon via API, Flipkart and Meesho payment files).</li>
          <li>Match every payout line to its order and product: commission, shipping, fixed fee, GST on fees, TCS, TDS, returns and RTO.</li>
          <li>P&amp;L by product, account, firm and month, using the cost price on each product plus your expenses (ads, packaging, staff).</li>
          <li>Flags for missing payouts and unusual deductions.</li>
        </ul>
        <p className="muted small">The database already has tables for orders, settlements and expenses, so this plugs in without changing existing data.</p>
      </div>
    </>
  )
}

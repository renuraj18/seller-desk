/* Seller Desk panel injected into Meesho / Flipkart / Amazon seller pages.
 * - detects the marketplace from the site and the logged-in account from the page
 * - List tab: fill add-product forms (single saree or all colour variants), attach images, autopilot through the queue
 * - Stock tab: read stock shown on the page and set it to Seller Desk's master stock */
(() => {
  if (window.top !== window || document.getElementById('seller-desk-ext-host')) return
  const E = globalThis.SDEngine

  const MP = (() => {
    const h = location.hostname
    if (h.includes('meesho')) return 'meesho'
    if (h.includes('flipkart')) return 'flipkart'
    if (h.includes('amazon')) return 'amazon'
    return new URLSearchParams(location.search).get('mp') || 'meesho'
  })()
  const MP_LABEL = { meesho: 'Meesho', flipkart: 'Flipkart', amazon: 'Amazon' }
  const SUBMIT_RE = /^(submit|submit catalog|submit catalogue|send for qc|save (and|&) submit|save (and|&) finish|publish|list now|create listing)$/i

  // ---------------------------------------------------------------- talk to Seller Desk via background
  const send = (msg) => new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false, error: chrome.runtime.lastError?.message || 'No response' }))
    } catch { resolve({ ok: false, error: 'Extension was updated — reload this page' }) }
  })
  async function api(path, method = 'GET', body) {
    const r = await send({ type: 'api', path, method, body })
    if (!r.ok) throw new Error(r.error || 'Request failed')
    return r.data
  }
  const store = {
    get: async (k, d) => (await chrome.storage.local.get(k))[k] ?? d,
    set: (k, v) => chrome.storage.local.set({ [k]: v }),
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  // ---------------------------------------------------------------- state
  const S = {
    open: false, connected: null, error: '', info: '', ctx: null, accountId: null, detected: false,
    view: 'list', tab: 'todo', q: '', products: [], product: null, group: [], variantIdx: -1,
    payloads: null, results: null, busy: '', onlyEmpty: false, teach: null,
    stock: [], stockScan: null, orderScan: null, pageStatus: '', tabHint: '', clickSave: true, auto: null, autoSubmit: false,
  }
  const currentPayloads = () => (S.variantIdx < 0 ? S.payloads : [S.payloads[S.variantIdx]])

  // ---------------------------------------------------------------- UI shell
  const host = document.createElement('div')
  host.id = 'seller-desk-ext-host'
  Object.assign(host.style, { position: 'fixed', right: '16px', bottom: '16px', zIndex: 2147483647 })
  const root = host.attachShadow({ mode: 'open' })
  document.documentElement.appendChild(host)

  const css = `
  :host { all: initial; }
  * { box-sizing: border-box; font-family: Inter, "Segoe UI", system-ui, sans-serif; }
  .fab { background: #7a1f2b; color: #fff; border: 0; border-radius: 999px; padding: 10px 16px; font-size: 13px; font-weight: 600; cursor: pointer; box-shadow: 0 6px 20px rgba(0,0,0,.25); display: flex; gap: 8px; align-items: center; }
  .fab .dot { width: 8px; height: 8px; border-radius: 50%; background: #f3c969; }
  .fab.run .dot { background: #5ee08f; animation: p 1s infinite; } @keyframes p { 50% { opacity: .3 } }
  .panel { width: 380px; max-height: min(680px, calc(100vh - 32px)); background: #fff; color: #1f1a17; border-radius: 12px; box-shadow: 0 12px 40px rgba(0,0,0,.28); display: flex; flex-direction: column; overflow: hidden; font-size: 13px; }
  .head { background: #2a1a1d; color: #fff; padding: 10px 12px; display: flex; align-items: center; gap: 8px; }
  .head b { font-size: 14px; } .head .sp { flex: 1; }
  .mp { font-size: 11px; background: #7a1f2b; padding: 2px 8px; border-radius: 99px; }
  .x { background: none; border: 0; color: #e9dfd8; cursor: pointer; font-size: 16px; padding: 2px 6px; }
  .views { display: flex; background: #3a272b; }
  .views button { flex: 1; background: none; border: 0; color: #d8c9c0; padding: 8px; cursor: pointer; font-size: 13px; border-bottom: 2px solid transparent; }
  .views button.on { color: #fff; border-bottom-color: #f3c969; font-weight: 600; }
  .body { padding: 12px; overflow-y: auto; flex: 1; }
  label { display: block; font-size: 11px; color: #7a6f66; margin: 0 0 4px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
  select, input[type=text], input:not([type]), textarea { width: 100%; border: 1px solid #e0d6cb; border-radius: 8px; padding: 7px 9px; font-size: 13px; background: #fff; color: #1f1a17; }
  textarea { min-height: 54px; resize: vertical; }
  .field { margin-bottom: 10px; }
  .row { display: flex; gap: 6px; align-items: center; }
  .sp { flex: 1; }
  button.b { border: 1px solid #e0d6cb; background: #fff; color: #1f1a17; border-radius: 8px; padding: 7px 11px; font-size: 13px; cursor: pointer; white-space: nowrap; }
  button.b:hover { border-color: #c9b9aa; }
  button.p { background: #7a1f2b; border-color: #7a1f2b; color: #fff; }
  button.ok { background: #2f7d4f; border-color: #2f7d4f; color: #fff; }
  button.stop { background: #b42318; border-color: #b42318; color: #fff; }
  button:disabled { opacity: .5; cursor: default; }
  .tabs { display: flex; gap: 4px; margin-bottom: 8px; }
  .tabs button { flex: 1; border: 1px solid #e0d6cb; background: #faf7f3; border-radius: 8px; padding: 6px; cursor: pointer; font-size: 12px; color: #5b4f46; }
  .tabs button.on { background: #7a1f2b; color: #fff; border-color: #7a1f2b; }
  .list { border: 1px solid #eee5db; border-radius: 8px; max-height: 230px; overflow-y: auto; margin-top: 6px; }
  .item { display: flex; gap: 8px; align-items: center; padding: 7px 8px; border-bottom: 1px solid #f2ebe3; cursor: pointer; }
  .item:last-child { border-bottom: 0; } .item:hover { background: #fcf7f2; }
  .item img, .ph { width: 30px; height: 38px; object-fit: cover; border-radius: 4px; background: #eee; flex: none; }
  .sku { font-family: ui-monospace, Menlo, monospace; font-size: 12px; font-weight: 600; }
  .muted { color: #7a6f66; font-size: 12px; }
  .badge { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 99px; background: #eee; color: #555; text-transform: capitalize; }
  .b-draft { background: #fff3d6; color: #9a6400; } .b-live, .b-exported { background: #e2f3e8; color: #2f7d4f; } .b-var { background: #efe7ff; color: #5b3aa6; }
  .card { border: 1px solid #e7dfd5; border-radius: 10px; padding: 10px; margin: 10px 0; background: #fbf8f4; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
  .chip { border: 1px solid #e0d6cb; background: #fff; border-radius: 99px; padding: 3px 9px; font-size: 12px; cursor: pointer; }
  .chip.on { background: #7a1f2b; color: #fff; border-color: #7a1f2b; }
  .actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
  .msg { padding: 8px 10px; border-radius: 8px; font-size: 12px; margin-bottom: 10px; }
  .msg.err { background: #fde7e5; color: #8f1d14; } .msg.info { background: #eef4ff; color: #23407a; } .msg.ok { background: #e2f3e8; color: #22603c; }
  .res { margin-top: 6px; }
  .res .r { display: flex; gap: 6px; padding: 5px 0; border-bottom: 1px dashed #eee5db; align-items: flex-start; }
  .res .i { width: 16px; flex: none; text-align: center; }
  .res .t { flex: 1; min-width: 0; } .res .t div { overflow-wrap: anywhere; }
  .link { background: none; border: 0; color: #7a1f2b; cursor: pointer; font-size: 12px; text-decoration: underline; padding: 0; }
  .sum { display: flex; gap: 10px; font-size: 12px; margin-top: 8px; flex-wrap: wrap; }
  .chk { display: flex; gap: 6px; align-items: center; font-size: 12px; color: #5b4f46; margin-top: 8px; text-transform: none; letter-spacing: 0; font-weight: 400; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  td, th { padding: 5px 4px; border-bottom: 1px solid #f2ebe3; text-align: left; }
  th { color: #7a6f66; font-weight: 600; font-size: 11px; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .diff { color: #b7791f; font-weight: 700; } .same { color: #2f7d4f; }
  `

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
  const money = (v) => (v == null ? '—' : '₹' + Number(v).toLocaleString('en-IN'))
  const imgUrl = (u) => (u && u.startsWith('/') ? `${S.server || ''}${u}` : u)

  function render() {
    if (!S.open) {
      root.innerHTML = `<style>${css}</style><button class="fab ${S.auto?.running ? 'run' : ''}" data-a="open"><span class="dot"></span>Seller Desk${S.auto?.running ? ' · autopilot' : ''}</button>`
      return
    }
    const acc = S.ctx?.accounts.find((a) => a.id === S.accountId)
    root.innerHTML = `<style>${css}</style><div class="panel">
      <div class="head"><b>Seller Desk</b><span class="mp">${MP_LABEL[MP]}</span>${acc ? `<span class="muted" style="color:#d8c9c0">${esc(acc.name)}</span>` : ''}<span class="sp"></span>
        <button class="x" data-a="close" title="Minimise">–</button></div>
      ${S.connected && !S.teach ? `<div class="views"><button class="${S.view === 'list' ? 'on' : ''}" data-a="view" data-v="list">List sarees</button>
        <button class="${S.view === 'stock' ? 'on' : ''}" data-a="view" data-v="stock">Stock</button>
        <button class="${S.view === 'orders' ? 'on' : ''}" data-a="view" data-v="orders">Orders</button></div>` : ''}
      <div class="body">${S.teach ? teachView() : S.view === 'stock' && S.connected ? stockView() : S.view === 'orders' && S.connected ? ordersView() : mainView()}</div></div>`
  }

  function accountPicker() {
    const accs = S.ctx.accounts
    return `<div class="field"><label>Logged-in account ${S.detected ? '<span class="badge b-live">detected</span>' : ''}</label>
      <select data-a="account">${accs.map((a) => `<option value="${a.id}" ${a.id === S.accountId ? 'selected' : ''}>${esc(a.name)} · ${esc(a.firm_name)}${a.to_list ? ` (${a.to_list} to list)` : ''}</option>`).join('')}</select>
      ${S.detected ? '' : '<div class="muted" style="margin-top:4px">Pick the account you are logged in to. Add its Seller ID in Seller Desk to detect it automatically.</div>'}</div>`
  }

  function guard() {
    if (S.connected === null) return `<div class="muted">Connecting to Seller Desk…</div>`
    if (!S.connected) {
      return `<div class="msg err">Can't reach Seller Desk. Start it on this PC (double-click <b>start.bat</b>), then retry.<br><span class="muted">${esc(S.error)}</span></div>
        <button class="b p" data-a="retry">Retry</button>`
    }
    if (!S.ctx.accounts.length) return `<div class="msg info">No ${MP_LABEL[MP]} accounts in Seller Desk yet. Add them in Firms &amp; accounts.</div>`
    return ''
  }
  const notes = () => `${S.error ? `<div class="msg err">${esc(S.error)}</div>` : ''}${S.info ? `<div class="msg ok">${esc(S.info)}</div>` : ''}`

  function mainView() {
    const g = guard(); if (g) return g
    let h = notes()
    if (S.auto?.running) {
      h += `<div class="msg info"><b>Autopilot</b>: ${S.auto.done} of ${S.auto.total} done. ${esc(S.auto.status || '')}</div>
        <div class="actions"><button class="b stop" data-a="stopAuto">Stop autopilot</button></div>`
    }
    h += accountPicker()
    if (S.product) {
      const p = S.product
      const multi = S.group.length > 1
      h += `<div class="card"><div class="row">${p.image ? `<img src="${esc(imgUrl(p.image))}" style="width:36px;height:46px;object-fit:cover;border-radius:5px">` : '<div class="ph"></div>'}
        <div class="sp"><div class="sku">${esc(p.account_sku)}</div><div class="muted">${esc([p.saree_type, p.fabric, p.color].filter(Boolean).join(' · '))}</div>
        <div>${money(p.price)} ${p.content_approved ? '<span class="badge b-live">SEO approved</span>' : '<span class="badge b-draft">auto text</span>'}</div></div>
        ${S.auto?.running ? '' : '<button class="link" data-a="change">Change</button>'}</div>
        ${multi ? `<div class="chips"><span class="chip ${S.variantIdx < 0 ? 'on' : ''}" data-a="variant" data-i="-1">All ${S.group.length} variants</span>
          ${S.group.map((v, i) => `<span class="chip ${S.variantIdx === i ? 'on' : ''}" data-a="variant" data-i="${i}">${esc(v.color || v.sku)}</span>`).join('')}</div>
          <div class="muted" style="margin-top:4px">${S.variantIdx < 0 ? 'Repeated sections on the page get one variant each, in this order.' : 'Fills this variant only (for forms that show one variant at a time).'}</div>` : ''}
        <label class="chk"><input type="checkbox" data-a="onlyEmpty" ${S.onlyEmpty ? 'checked' : ''}> Only fill empty fields</label>
        <div class="actions">
          <button class="b p" data-a="fill" ${S.busy ? 'disabled' : ''}>${S.busy === 'fill' ? 'Filling…' : 'Fill this page'}</button>
          <button class="b" data-a="images" ${S.busy || !imageCount() ? 'disabled' : ''}>${S.busy === 'images' ? 'Attaching…' : `Attach images (${imageCount()})`}</button>
          <button class="b" data-a="teach" ${S.busy ? 'disabled' : ''}>Teach a field</button>
        </div></div>`
      if (S.results) h += resultsView()
      h += `<div class="actions" style="margin-top:12px"><button class="b ok" data-a="done">I've submitted it ✓</button>
        <span class="muted" style="align-self:center">marks it listed &amp; opens the next</span></div>`
      return h
    }
    h += `<div class="tabs"><button class="${S.tab === 'todo' ? 'on' : ''}" data-a="tab" data-v="todo">To list</button>
        <button class="${S.tab === 'all' ? 'on' : ''}" data-a="tab" data-v="all">All sarees</button></div>
      <input placeholder="Search SKU, fabric, colour" data-a="q" value="${esc(S.q)}">
      <div class="list">${S.products.length ? groupedProducts().map((p) => `
        <div class="item" data-a="pick" data-id="${p.id}">${p.image ? `<img src="${esc(imgUrl(p.image))}">` : '<div class="ph"></div>'}
          <div class="sp"><div class="sku">${esc(p.variant_count > 1 ? p.parent_sku : p.account_sku)}</div><div class="muted">${esc([p.saree_type, p.fabric, p.variant_count > 1 ? '' : p.color].filter(Boolean).join(' · '))}</div>
          ${p.variant_count > 1 ? `<span class="badge b-var">${p.variant_count} colours</span>` : ''}</div>
          <div style="text-align:right">${money(p.price)}<br>${p.status ? `<span class="badge b-${esc(p.status)}">${esc(p.status)}</span>` : '<span class="muted">new</span>'}</div></div>`).join('')
        : `<div class="muted" style="padding:12px">${S.tab === 'todo' ? 'Nothing waiting for this account. In Seller Desk, select sarees → <b>Add to accounts</b>.' : 'No sarees found.'}</div>`}</div>`
    if (S.tab === 'todo' && S.products.length) {
      h += `<label class="chk"><input type="checkbox" data-a="autoSubmit" ${S.autoSubmit ? 'checked' : ''}> Submit automatically when every field filled</label>
        <div class="actions"><button class="b p" data-a="startAuto">▶ Autopilot: list all ${groupedProducts().length}</button></div>
        <div class="muted" style="margin-top:4px">Open the add-product page first. Autopilot fills each saree, ${S.autoSubmit ? 'submits it, ' : 'waits for you to submit, '}then returns here for the next one.</div>`
    }
    return h
  }

  function groupedProducts() {
    const seen = new Set()
    return S.products.filter((p) => {
      if (!p.parent_sku || p.variant_count <= 1) return true
      if (seen.has(p.parent_sku)) return false
      seen.add(p.parent_sku); return true
    })
  }
  const imageCount = () => (currentPayloads() || []).reduce((n, p) => n + p.images.length, 0)

  function resultsView() {
    const r = S.results
    const n = (s) => r.filter((x) => x.status === s).length
    const icon = { filled: '✅', failed: '⚠️', unknown: '❔', empty: '⚪', skipped: '⏭', ignored: '🚫' }
    const shown = r.filter((x) => x.status !== 'ignored')
    return `<div class="sum"><span>✅ ${n('filled')} filled</span><span>⚠️ ${n('failed') + n('empty')} need a look</span><span>❔ ${n('unknown')} unknown</span></div>
      <div class="res">${shown.map((x) => `<div class="r"><span class="i">${icon[x.status]}</span><div class="t">
        <div><b>${esc(x.label)}</b>${x.how === 'taught' ? ' <span class="muted">(taught)</span>' : ''}</div>
        ${x.status === 'filled' ? `<div class="muted">${esc(String(x.value).slice(0, 90))}</div>` : ''}
        ${x.reason ? `<div class="muted">${esc(x.reason)}${x.options?.length ? `: ${esc(x.options.join(', '))}` : ''}</div>` : ''}
        ${x.status === 'unknown' ? '<div class="muted">Not recognised</div>' : ''}
      </div>${x.status !== 'filled' ? `<button class="link" data-a="teachRes" data-i="${r.indexOf(x)}">Teach</button>` : ''}</div>`).join('')}</div>`
  }

  function stockView() {
    const g = guard(); if (g) return g
    let h = notes() + accountPicker()
    const scan = S.stockScan
    const rows = S.stock.filter((r) => !S.q || `${r.account_sku} ${r.color || ''}`.toLowerCase().includes(S.q.toLowerCase()))
    h += `<div class="muted" style="margin-bottom:8px">Open your inventory / listings page on ${MP_LABEL[MP]} (show as many rows per page as possible), then:</div>
      <div class="actions" style="margin-top:0">
        <button class="b p" data-a="syncStock" ${S.busy ? 'disabled' : ''}>${S.busy === 'sync' ? 'Syncing…' : 'Sync stock on this page'}</button>
        <button class="b" data-a="readStock" ${S.busy ? 'disabled' : ''}>Only read</button></div>
      <label class="chk"><input type="checkbox" data-a="clickSave" ${S.clickSave ? 'checked' : ''}> Click the row's Save/Update button after changing</label>`
    if (scan) {
      h += `<div class="sum"><span>🔎 ${scan.found} of ${S.stock.length} SKUs on this page</span><span class="${scan.diff ? 'diff' : 'same'}">${scan.diff} differ</span>${scan.updated != null ? `<span>✏️ ${scan.updated} updated</span>` : ''}</div>`
    }
    h += `<input placeholder="Filter SKU or colour" data-a="q" value="${esc(S.q)}" style="margin-top:10px">
      <div class="list" style="max-height:300px"><table><thead><tr><th>SKU here</th><th class="num">Master</th><th class="num">On ${MP_LABEL[MP]}</th></tr></thead><tbody>
      ${rows.map((r) => {
        const d = r.target != null && r.seen != null && r.target !== r.seen
        return `<tr><td><span class="sku">${esc(r.account_sku)}</span>${r.color ? `<div class="muted">${esc(r.color)}</div>` : ''}</td>
          <td class="num">${r.target ?? '—'}</td><td class="num ${d ? 'diff' : r.seen != null ? 'same' : ''}">${r.seen ?? '—'}${r.onPage ? ' 👁' : ''}</td></tr>`
      }).join('') || '<tr><td colspan="3" class="muted">No sarees listed on this account yet.</td></tr>'}</tbody></table></div>
      <div class="muted" style="margin-top:6px">Master stock is edited in Seller Desk → Inventory. 👁 = seen on this page.</div>`
    return h
  }

  const PAGE_STATUS = [['', 'Detect from the page'], ['Pending', 'Pending / ready to ship'], ['Shipped', 'Shipped'], ['Delivered', 'Delivered'],
    ['Cancelled', 'Cancelled'], ['RTO', 'Courier return (RTO)'], ['Customer return', 'Customer return']]
  function ordersView() {
    const g = guard(); if (g) return g
    const o = S.orderScan
    return notes() + accountPicker() + `
      <div class="muted" style="margin-bottom:8px">Open an orders or returns page on ${MP_LABEL[MP]} (any tab: pending, shipped, cancelled, returns). Show as many rows per page as you can, then capture. Repeat for each tab.</div>
      <div class="field"><label>Status for rows that don't show one</label><select data-a="pageStatus">
        ${PAGE_STATUS.map(([v, l]) => `<option value="${v}" ${S.pageStatus === v ? 'selected' : ''}>${l}${!v && S.tabHint ? ` (tab: ${esc(S.tabHint)})` : ''}</option>`).join('')}</select></div>
      <div class="actions" style="margin-top:0"><button class="b p" data-a="captureOrders" ${S.busy ? 'disabled' : ''}>${S.busy === 'orders' ? 'Capturing…' : 'Capture orders on this page'}</button></div>
      ${o ? `<div class="sum"><span>🧾 ${o.rows} orders found</span><span>➕ ${o.created} new</span><span>🔄 ${o.updated} updated</span></div>
        <div class="list" style="max-height:260px"><table><thead><tr><th>Order</th><th>Status</th><th>Date</th></tr></thead><tbody>
        ${o.sample.map((r) => `<tr><td class="sku">${esc(r.sub_order_id || r.order_id)}${r.sku ? `<div class="muted">${esc(r.sku)}</div>` : ''}</td><td>${esc(r.status_text || S.pageStatus || S.tabHint || '—')}</td><td class="muted">${esc(r.order_date || '')}</td></tr>`).join('')}
        </tbody></table></div>` : ''}
      <div class="muted" style="margin-top:8px">Cancellation and return charges come from the payment reports: upload them in Seller Desk → Orders. The master Excel updates automatically.</div>`
  }

  async function captureOrders() {
    S.busy = 'orders'; S.error = ''; S.info = ''; render()
    try {
      const skus = await api(`/api/ext/known-skus?account_id=${S.accountId}`)
      const rows = E.scanOrders(MP, skus)
      if (!rows.length) throw new Error(`No ${MP_LABEL[MP]} order IDs found on this page. Open the orders or returns page (and the right account).`)
      const pageStatus = S.pageStatus || S.tabHint || null
      const res = await api('/api/ext/orders-seen', 'POST', { account_id: S.accountId, page_status: pageStatus, rows })
      S.orderScan = { ...res, sample: rows.slice(0, 50) }
      S.info = `Saved to the master orders list${res.master_saved ? ' and Excel' : ''}`
    } catch (e) { S.error = e.message }
    S.busy = ''; render()
  }

  function teachView() {
    const t = S.teach
    if (t.picking) return `<div class="msg info">Click the field on the page you want to teach. Press <b>Esc</b> to cancel.</div><button class="b" data-a="cancelTeach">Cancel</button>`
    const groups = [...new Set(S.ctx.sources.map((s) => s.group))]
    const vals = (currentPayloads() || [])[0]?.values || {}
    const vm = Object.entries(t.value_map || {}).map(([a, b]) => `${a} = ${b}`).join('\n')
    return `<div class="field"><label>Field label on this page</label><input data-a="tLabel" value="${esc(t.label)}">
        <div class="muted" style="margin-top:4px">Saved for every ${MP_LABEL[MP]} account, both firms.</div></div>
      <div class="field"><label>Fill it with</label><select data-a="tSource">
        <option value="" ${!t.source ? 'selected' : ''}>— Ignore this field —</option>
        ${groups.map((g) => `<optgroup label="${esc(g)}">${S.ctx.sources.filter((s) => s.group === g).map((s) => `<option value="${s.key}" ${s.key === t.source ? 'selected' : ''}>${esc(s.label)}${vals[s.key] != null ? ` — ${esc(String(vals[s.key]).slice(0, 30))}` : ''}</option>`).join('')}</optgroup>`).join('')}
      </select></div>
      ${t.source === 'const.custom' ? `<div class="field"><label>Value for every listing</label><input data-a="tValue" value="${esc(t.value || '')}"></div>` : ''}
      <div class="field"><label>Translate values (optional)</label><textarea data-a="tMap" placeholder="Your value = value on ${MP_LABEL[MP]}\nUnstitched Blouse Piece = Separate Blouse Piece">${esc(t.mapText ?? vm)}</textarea></div>
      <div class="actions"><button class="b p" data-a="saveTeach">Save &amp; fill</button><button class="b" data-a="cancelTeach">Cancel</button></div>`
  }

  // ---------------------------------------------------------------- account detection
  function detectAccount(accounts) {
    const text = (document.body?.innerText || '').slice(0, 200000).toLowerCase()
    const hits = accounts.filter((a) => (a.seller_id && text.includes(String(a.seller_id).toLowerCase())) ||
      (a.store_name && text.includes(String(a.store_name).toLowerCase())))
    return hits.length === 1 ? hits[0].id : null
  }

  // ---------------------------------------------------------------- data
  async function connect() {
    S.connected = null; S.error = ''; render()
    try {
      const ping = await send({ type: 'ping' })
      S.server = ping.server
      S.ctx = await api(`/api/ext/context?marketplace=${MP}`)
      E.setSynonyms(S.ctx.synonyms)
      const detected = detectAccount(S.ctx.accounts)
      const saved = await store.get(`account_${MP}`)
      S.detected = !!detected
      S.accountId = detected || S.ctx.accounts.find((a) => a.id === saved)?.id || S.ctx.accounts[0]?.id || null
      if (detected) store.set(`account_${MP}`, detected)
      S.connected = true
      await loadProducts()
    } catch (e) { S.connected = false; S.error = e.message }
    render()
  }
  let qTimer
  async function loadProducts() {
    if (!S.accountId) return
    try {
      S.products = await api(`/api/ext/products?account_id=${S.accountId}&only=${S.tab}&q=${encodeURIComponent(S.q)}`)
      // nothing queued for this account: show all sarees instead of an empty list (not during autopilot)
      if (S.tab === 'todo' && !S.products.length && !S.q && !S.auto?.running && !S._autoSwitched) {
        S._autoSwitched = true; S.tab = 'all'
        return loadProducts()
      }
    } catch (e) { S.error = e.message }
  }
  async function loadStock() {
    if (!S.accountId) return
    try { S.stock = await api(`/api/ext/stock?account_id=${S.accountId}`) } catch (e) { S.error = e.message }
  }
  async function pick(id) {
    S.product = S.products.find((p) => p.id === id); S.results = null; S.error = ''; S.info = ''
    S.variantIdx = -1
    render()
    try {
      S.payloads = await api(`/api/ext/payload-group?product_id=${id}&account_id=${S.accountId}`)
      const byId = Object.fromEntries(S.products.map((p) => [p.id, p]))
      S.group = S.payloads.map((pl) => ({ sku: pl.values['listing.sku'], color: pl.values['product.color'], id: pl.product.id, p: byId[pl.product.id] }))
    } catch (e) { S.error = e.message }
    render()
  }
  async function refreshLearned() { S.ctx = await api(`/api/ext/context?marketplace=${MP}`) }

  // ---------------------------------------------------------------- listing actions
  async function doFill() {
    if (!S.payloads) return
    S.busy = 'fill'; S.error = ''; S.info = ''; render()
    try {
      const pls = currentPayloads()
      const tabs = E.productTabs()
      if (pls.length > 1 && tabs.length >= 2) {
        // Meesho-style catalog: one tab per product. Fill each tab with its own colour variant.
        S.results = []
        for (let i = 0; i < Math.min(pls.length, tabs.length); i++) {
          await E.openProductTab(i)
          const res = await E.fill(pls[i], S.ctx.learned, { onlyEmpty: S.onlyEmpty })
          const tag = ` · ${pls[i].values['product.color'] || 'product ' + (i + 1)}`
          res.forEach((r) => { r.label += tag })
          S.results.push(...res)
        }
        await E.openProductTab(0)
        if (pls.length > tabs.length) S.error = `${pls.length - tabs.length} variant(s) have no product tab. Add their photos first (Add Product).`
      } else {
        S.results = await E.fill(pls, S.ctx.learned, { onlyEmpty: S.onlyEmpty })
      }
    } catch (e) { S.error = e.message }
    S.busy = ''; render()
    return S.results
  }
  async function doImages() {
    S.busy = 'images'; S.error = ''; render()
    let ok = false
    try {
      const files = []
      for (const pl of currentPayloads()) {
        for (const [i, url] of pl.images.entries()) {
          const r = await send({ type: 'image', url })
          if (!r.ok) throw new Error(`Image ${i + 1} of ${pl.values['listing.sku']}: ${r.error}`)
          const ext = (r.type.split('/')[1] || 'jpg').replace('jpeg', 'jpg').replace('svg+xml', 'svg')
          files.push(E.b64ToFile(r.b64, r.type, `${pl.values['listing.sku']}-${i + 1}.${ext}`))
        }
      }
      const res = await E.attachImages(files)
      if (!res.ok) throw new Error(res.reason)
      S.info = `${res.count} image(s) attached`
      ok = true
    } catch (e) { S.error = e.message }
    S.busy = ''; render()
    return ok
  }
  async function markDone(ids) {
    for (const id of ids) await api('/api/ext/done', 'POST', { product_id: id, account_id: S.accountId })
  }
  async function doDone() {
    try {
      const ids = (S.variantIdx < 0 ? S.group : [S.group[S.variantIdx]]).map((g) => g.id)
      await markDone(ids)
      E.clearMarks()
      if (S.auto?.running) { await autoNext(true); return }
      S.product = null; S.payloads = null; S.results = null
      await refreshLearned(); await loadProducts()
      S.info = `Marked ${ids.length} listing(s) as submitted`
      render()
      const next = groupedProducts()[0]
      if (next && S.tab === 'todo') await pick(next.id)
    } catch (e) { S.error = e.message; render() }
  }

  // ---------------------------------------------------------------- autopilot (survives page reloads)
  async function saveAuto() { await store.set('autopilot', S.auto) }
  async function startAuto() {
    const items = groupedProducts().map((p) => p.id)
    S.auto = { running: true, marketplace: MP, accountId: S.accountId, queue: items, done: 0, total: items.length, startUrl: location.href, submit: S.autoSubmit, status: 'Starting…' }
    await saveAuto()
    await autoStep()
  }
  async function stopAuto(msg) {
    if (S.auto) S.auto.running = false
    await store.set('autopilot', null)
    S.info = msg || 'Autopilot stopped'
    render()
  }
  function formReady() { return E.findControls().length >= 4 }
  async function autoStep() {
    const a = S.auto
    if (!a?.running) return
    if (!a.queue.length) { await stopAuto(`Autopilot finished: ${a.done} listed`); S.auto = null; await loadProducts(); render(); return }
    a.status = 'Waiting for the add-product form…'; render()
    const ok = await waitUntil(formReady, 20000)
    if (!ok) { await stopAuto('Autopilot paused: no listing form on this page. Open the add-product page and start again.'); return }
    if (!S.products.find((p) => p.id === a.queue[0])) { S.tab = 'all'; await loadProducts(); S.tab = 'todo' }
    await pick(a.queue[0])
    a.status = `Filling ${S.product?.account_sku || ''}`; render()
    const results = await doFill()
    if (imageCount()) await doImages()
    const problems = (results || []).filter((r) => r.status === 'failed' || r.status === 'empty')
    if (a.submit && !problems.length && !S.error) {
      const btn = submitButton()
      if (!btn) { a.status = 'Filled. No Submit button found — submit it yourself, then click “I’ve submitted it”.'; await saveAuto(); render(); return }
      a.status = 'Submitting…'; render()
      btn.click()
      await sleep(2500)
      const errs = visibleErrors()
      if (errs.length) { a.status = `The site reported: ${errs.slice(0, 3).join('; ')}. Fix and submit, then click “I’ve submitted it”.`; await saveAuto(); render(); return }
      await autoNext(true)
      return
    }
    a.status = problems.length ? `Filled with ${problems.length} field(s) to check. Fix them, submit on ${MP_LABEL[MP]}, then click “I’ve submitted it”.` : `Filled. Review and submit on ${MP_LABEL[MP]}, then click “I’ve submitted it”.`
    await saveAuto(); render()
  }
  async function autoNext(alreadyMarked) {
    const a = S.auto
    const ids = S.group.map((g) => g.id)
    if (!alreadyMarked || a.submit) await markDone(ids).catch(() => {})
    a.queue.shift(); a.done++
    a.status = 'Opening the form for the next saree…'
    S.product = null; S.payloads = null; S.results = null
    await saveAuto(); render()
    if (!a.queue.length) { await autoStep(); return }
    if (location.href !== a.startUrl) { location.href = a.startUrl; return }   // continues after reload
    location.reload()
  }
  function submitButton() {
    return [...document.querySelectorAll('button, input[type=submit], [role=button]')].find((b) =>
      !host.contains(b) && SUBMIT_RE.test((b.textContent || b.value || '').trim()) && !b.disabled)
  }
  function visibleErrors() {
    return [...document.querySelectorAll('[role=alert], .error, [class*="error" i], [class*="invalid" i]')]
      .filter((e) => !host.contains(e) && e.offsetParent && e.textContent.trim().length > 3 && e.textContent.trim().length < 140)
      .map((e) => e.textContent.trim())
  }
  async function waitUntil(fn, timeout) {
    const end = Date.now() + timeout
    while (Date.now() < end) { if (fn()) return true; await sleep(400) }
    return fn()
  }

  // ---------------------------------------------------------------- stock actions
  async function scanStock(update) {
    S.busy = update ? 'sync' : 'read'; S.error = ''; S.info = ''; render()
    try {
      await loadStock()
      const items = S.stock.map((r) => ({ product_id: r.product_id, keys: [r.account_sku, r.sku, r.listing_ref] }))
      const found = E.scanStock(items)
      const seenRows = found.filter((f) => f.stock != null).map((f) => ({ key: S.stock.find((r) => r.product_id === f.product_id).account_sku, stock: f.stock }))
      if (seenRows.length) await api('/api/ext/stock-seen', 'POST', { account_id: S.accountId, rows: seenRows })
      const byId = Object.fromEntries(S.stock.map((r) => [r.product_id, r]))
      let diff = 0; let updated = 0; const failed = []
      for (const f of found) {
        const r = byId[f.product_id]
        r.onPage = true
        if (f.stock != null) r.seen = f.stock
        if (r.target == null || f.stock === r.target) continue
        diff++
        if (!update) continue
        const res = await E.setStock(f.row, r.target, S.clickSave)
        if (res.ok) {
          updated++
          r.seen = r.target
          await api('/api/ext/stock-set', 'POST', { product_id: r.product_id, account_id: S.accountId, stock: r.target })
        } else failed.push(`${r.account_sku}: ${res.reason}`)
        await sleep(150)
      }
      S.stockScan = { found: found.length, diff: update ? diff - updated : diff, updated: update ? updated : null }
      if (!found.length) S.error = 'None of this account’s SKUs were found on this page. Open the inventory / listings page, or check the account selected above.'
      else if (failed.length) S.error = failed.slice(0, 5).join('\n')
      else S.info = update ? (updated ? `Updated ${updated} SKU(s) to master stock` : 'Everything on this page already matches') : `Read stock for ${found.length} SKU(s)`
    } catch (e) { S.error = e.message }
    S.busy = ''; render()
  }

  // ---------------------------------------------------------------- teach
  async function startTeach(fromResult) {
    if (fromResult) {
      S.teach = { el: fromResult.el, label: fromResult.label.replace(/ · [^·]+$/, ''), source: fromResult.source || '', value: '', value_map: {} }
      const known = S.ctx.learned.find((l) => l.label_norm === E.normalise(S.teach.label))
      if (known) Object.assign(S.teach, { source: known.source, value: known.value, value_map: known.value_map || {} })
      render(); return
    }
    S.teach = { picking: true }; render()
    const picked = await E.pickField()
    if (!picked) { S.teach = null; render(); return }
    const known = S.ctx.learned.find((l) => l.label_norm === E.normalise(picked.label))
    S.teach = { el: picked.el, label: picked.label, source: known?.source ?? E.guess(picked.label) ?? '', value: known?.value || '', value_map: known?.value_map || {} }
    render()
  }
  async function saveTeach() {
    const t = S.teach
    const value_map = {}
    String(t.mapText ?? Object.entries(t.value_map || {}).map(([a, b]) => `${a} = ${b}`).join('\n')).split('\n').forEach((line) => {
      const [a, ...b] = line.split('=')
      if (a?.trim() && b.length) value_map[a.trim()] = b.join('=').trim()
    })
    try {
      await api(`/api/ext/fields/${MP}`, 'PUT', { label: t.label, source: t.source, value: t.value || null, value_map })
      await refreshLearned()
      const entry = { source: t.source, value: t.value, value_map }
      S.teach = null
      if (t.el && t.source && S.payloads) {
        const hit = S.results?.find((x) => x.el === t.el)
        const m = hit?.label.match(/ · variant (\d+)$/)
        const pl = currentPayloads()[m ? Number(m[1]) - 1 : 0]
        const r = await E.fillOne(t.el, pl, entry)
        if (hit) Object.assign(hit, { status: r.ok ? 'filled' : 'failed', how: 'taught', source: t.source, value: r.chosen || pl.values[t.source] || t.value, reason: r.reason, options: r.options })
      }
    } catch (e) { S.error = e.message; S.teach = null }
    render()
  }

  // ---------------------------------------------------------------- events
  root.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-a]')
    if (!t) return
    const a = t.dataset.a
    if (a === 'open') { S.open = true; store.set('open', true); render(); if (S.connected !== true) connect() }
    else if (a === 'close') { S.open = false; store.set('open', false); render() }
    else if (a === 'retry') connect()
    else if (a === 'view') { S.view = t.dataset.v; S.q = ''; S.error = ''; S.info = ''; if (S.view === 'stock') await loadStock(); if (S.view === 'orders') S.tabHint = E.activeTabText(); render() }
    else if (a === 'tab') { S.tab = t.dataset.v; S._autoSwitched = true; await loadProducts(); render() }
    else if (a === 'pick') pick(Number(t.dataset.id))
    else if (a === 'variant') { S.variantIdx = Number(t.dataset.i); S.results = null; E.clearMarks(); render() }
    else if (a === 'change') { S.product = null; S.payloads = null; S.results = null; E.clearMarks(); await loadProducts(); render() }
    else if (a === 'fill') doFill()
    else if (a === 'images') doImages()
    else if (a === 'teach') startTeach()
    else if (a === 'teachRes') startTeach(S.results[Number(t.dataset.i)])
    else if (a === 'cancelTeach') { S.teach = null; render() }
    else if (a === 'saveTeach') saveTeach()
    else if (a === 'done') doDone()
    else if (a === 'onlyEmpty') S.onlyEmpty = t.checked
    else if (a === 'autoSubmit') { S.autoSubmit = t.checked; render() }
    else if (a === 'clickSave') S.clickSave = t.checked
    else if (a === 'startAuto') startAuto()
    else if (a === 'stopAuto') { await stopAuto(); S.auto = null; render() }
    else if (a === 'syncStock') scanStock(true)
    else if (a === 'readStock') scanStock(false)
    else if (a === 'captureOrders') captureOrders()
  })
  root.addEventListener('change', async (e) => {
    const a = e.target.dataset.a
    if (a === 'account') {
      S.accountId = Number(e.target.value); S.detected = false; store.set(`account_${MP}`, S.accountId)
      S.product = null; S.payloads = null; S.results = null; S.tab = 'todo'; S.stockScan = null; S._autoSwitched = false
      await loadProducts(); if (S.view === 'stock') await loadStock(); render()
    } else if (a === 'tSource') { S.teach.source = e.target.value; render() }
    else if (a === 'pageStatus') S.pageStatus = e.target.value
  })
  root.addEventListener('input', (e) => {
    const a = e.target.dataset.a
    if (a === 'q') {
      S.q = e.target.value
      clearTimeout(qTimer)
      qTimer = setTimeout(async () => {
        if (S.view === 'list') await loadProducts()
        render()
        const box = root.querySelector('[data-a=q]'); box?.focus(); box?.setSelectionRange(S.q.length, S.q.length)
      }, 250)
    } else if (a === 'tLabel') S.teach.label = e.target.value
    else if (a === 'tValue') S.teach.value = e.target.value
    else if (a === 'tMap') S.teach.mapText = e.target.value
  })
  ;['keydown', 'keyup', 'keypress'].forEach((t) => root.addEventListener(t, (e) => e.stopPropagation()))

  // ---------------------------------------------------------------- start
  ;(async () => {
    S.open = await store.get('open', false)
    const auto = await store.get('autopilot', null)
    if (auto?.running && auto.marketplace === MP) {
      S.auto = auto; S.open = true; S.autoSubmit = auto.submit
      render(); await connect()
      S.accountId = auto.accountId; S.tab = 'todo'; await loadProducts()
      autoStep()
      return
    }
    render()
    if (S.open) connect()
  })()
})()

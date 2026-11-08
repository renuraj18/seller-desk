/* Seller Desk fill engine: finds form fields on seller panels (incl. shadow DOM), works out their
 * labels, matches them to Seller Desk data and enters values the way a person would, so React/Angular
 * forms and custom dropdowns register the change. Exposed as globalThis.SDEngine. */
(() => {
  const HOST_ID = 'seller-desk-ext-host'

  const CTRL = [
    'input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image])',
    'textarea', 'select', '[aria-haspopup=listbox]', '[role=combobox]:not(input)',
    '[contenteditable=""]', '[contenteditable=true]',
  ].join(',')

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  async function waitFor(fn, timeout = 1500, step = 50) {
    const end = Date.now() + timeout
    while (Date.now() < end) {
      const v = fn()
      if (v && (!Array.isArray(v) || v.length)) return v
      await sleep(step)
    }
    return fn()
  }

  // ------------------------------------------------------------- text helpers (match backend fields.py)
  function normalise(text) {
    let s = String(text ?? '').toLowerCase()
    s = s.replace(/\[[^\]]*\]/g, '')
    s = s.replace(/\(.*?(mandatory|optional).*?\)/g, '')
    s = s.replace(/[^a-z0-9]/g, '')
    if (s.length > 8) s = s.replace(/value$/, '')
    return s
  }
  function clean(t) {
    const s = String(t || '')
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '') // zero-width characters (MUI outline legends, etc.)
      .replace(/\u00A0/g, ' ')
    if (!/[a-z0-9]/i.test(s)) return ''
    return s
      .replace(/\b\d+\s*\/\s*\d+\b/g, '') // 0/100 counters
      .replace(/[*✱]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/[:\-–]\s*$/, '')
      .trim()
  }

  let SYNONYMS = []
  function setSynonyms(list) { SYNONYMS = list || [] }
  function guess(label) {
    const h = normalise(label)
    if (!h) return null
    let best = null; let bestScore = 0
    for (const [syn, key] of SYNONYMS) {
      let score = 0
      if (h === syn) score = 100 + syn.length
      else if (syn.length >= 5 && h.includes(syn)) score = syn.length * (syn.length / h.length)
      else continue
      if (score > bestScore) { best = key; bestScore = score }
    }
    return bestScore >= 2.5 ? best : null
  }

  // ------------------------------------------------------------- DOM discovery
  function deepAll(root, sel, out = []) {
    root.querySelectorAll(sel).forEach((e) => out.push(e))
    root.querySelectorAll('*').forEach((e) => { if (e.shadowRoot && e.id !== HOST_ID) deepAll(e.shadowRoot, sel, out) })
    return out
  }
  const inPanel = (el) => {
    const root = el.getRootNode()
    return root instanceof ShadowRoot && root.host?.id === HOST_ID
  }
  function visible(el) {
    if (!el.isConnected) return false
    const r = el.getClientRects()
    if (!r.length) return false
    const st = getComputedStyle(el)
    return st.visibility !== 'hidden' && st.display !== 'none'
  }
  const isTextInput = (el) => el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'

  function kindOf(el) {
    if (el.tagName === 'SELECT') return 'select'
    if (el.isContentEditable && !isTextInput(el)) return 'editable'
    if (isTextInput(el)) {
      if (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete') || el.hasAttribute('list')) {
        return el.readOnly ? 'click' : 'combo'
      }
      return el.readOnly ? 'click' : 'text'
    }
    return 'click'
  }

  function findControls() {
    const all = deepAll(document, CTRL).filter((el) => !inPanel(el) && visible(el) && !el.disabled)
    // drop wrappers whose own input is also listed (role=combobox div around an input)
    const set = new Set(all)
    return all.filter((el) => !(el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA' &&
      [...el.querySelectorAll('input,textarea,select')].some((c) => set.has(c))))
  }

  // ------------------------------------------------------------- labels
  function textAround(container, el) {
    const before = []; const after = []
    const skip = (n) => {
      for (let p = n.parentElement; p && p !== container; p = p.parentElement) {
        if (p === el || p.matches('select,option,textarea,[role=listbox],[role=option],script,style,button,legend,fieldset,[role=tooltip],[data-testid=tooltip]')) return true
      }
      return false
    }
    const tw = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      const t = n.textContent.trim()
      if (!t || skip(n) || el.contains(n)) continue
      const pos = el.compareDocumentPosition(n)
      if (pos & Node.DOCUMENT_POSITION_PRECEDING) before.push(t)
      else after.push(t)
    }
    const b = clean(before.join(' '))
    if (b) return b
    return clean(after.join(' '))
  }

  function labelOf(el) {
    const root = el.getRootNode()
    const host = root instanceof ShadowRoot ? root.host : null
    const byId = (id) => (root.getElementById ? root.getElementById(id) : null) || document.getElementById(id)
    const lb = el.getAttribute('aria-labelledby')
    if (lb) {
      const t = clean(lb.split(/\s+/).map(byId).filter(Boolean).map((n) => n.textContent).join(' '))
      if (t) return t
    }
    const al = clean(el.getAttribute('aria-label'))
    if (al && normalise(al) !== 'search') return al
    if (el.id) {
      const l = root.querySelector(`label[for="${CSS.escape(el.id)}"]`)
      if (l && clean(l.textContent)) return clean(l.textContent)
    }
    const wrap = el.closest('label')
    if (wrap) { const t = textAround(wrap, el); if (t) return t }
    if (host) {
      if (host.getAttribute('label')) return clean(host.getAttribute('label'))
      const l = root.querySelector('label')
      if (l && clean(l.textContent)) return clean(l.textContent)
    }
    // table / grid cell: use the column header
    const cell = (host || el).closest('td, [role=gridcell], [role=cell]')
    if (cell) {
      const h = headerFor(cell)
      if (h) return h
    }
    // walk up while the ancestor wraps only this control
    const start = host || el
    let a = start.parentElement
    for (let i = 0; i < 5 && a && a !== document.body; i++, a = a.parentElement) {
      const controls = deepAll(a, CTRL).filter((c) => c !== el && !el.contains(c) && !c.contains(el) && visible(c))
      if (controls.length) break
      const t = textAround(a, start)
      if (t && t.length <= 80) return t
      if (t) break
    }
    const above = headerAbove(host || el)
    if (above) return above
    return clean(el.getAttribute('placeholder') || el.getAttribute('name') || el.getAttribute('title') || '')
  }

  /** Grids built from divs (e.g. Meesho's price table): use the nearest short text directly above the field. */
  function headerAbove(el) {
    const r = el.getBoundingClientRect()
    if (!r.width) return ''
    const cx = r.left + r.width / 2
    let best = ''; let bestGap = 220
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      const t = clean(n.textContent)
      if (!t || t.length > 50 || !/[a-z]/i.test(t)) continue
      const p = n.parentElement
      if (!p || inPanel(p) || p.closest('button, [role=option], [role=listbox], .MuiPopover-root, label')) continue
      const pr = p.getBoundingClientRect()
      if (!pr.width || pr.bottom > r.top + 2) continue
      if (cx < pr.left - 8 || cx > pr.right + 8) continue
      if (pr.right - pr.left > r.width * 3) continue          // a paragraph spanning the page is not a column title
      const gap = r.top - pr.bottom
      if (gap < bestGap) {
        // nothing else (another control) in between
        bestGap = gap
        best = t
      }
    }
    return best
  }

  function headerFor(cell) {
    const row = cell.parentElement
    if (!row) return ''
    const idx = [...row.children].indexOf(cell)
    const table = cell.closest('table, [role=grid], [role=table]')
    if (!table) return ''
    const headRow = table.querySelector('thead tr, [role=row]:has([role=columnheader])') ||
      [...table.querySelectorAll('tr')].find((tr) => tr.querySelector('th'))
    if (!headRow || headRow === row) return ''
    const h = headRow.children[idx]
    return h ? clean(h.textContent) : ''
  }

  function currentValue(el) {
    if (el.tagName === 'SELECT') return el.value
    if (isTextInput(el)) return el.value
    return ''
  }

  // ------------------------------------------------------------- entering values
  function fire(el, type) {
    el.dispatchEvent(new Event(type, { bubbles: true, composed: true }))
  }
  function setNative(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
      : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
    setter.call(el, value)
  }
  function realClick(el) {
    const o = { bubbles: true, cancelable: true, composed: true, view: window }
    el.dispatchEvent(new PointerEvent('pointerdown', o))
    el.dispatchEvent(new MouseEvent('mousedown', o))
    el.dispatchEvent(new PointerEvent('pointerup', o))
    el.dispatchEvent(new MouseEvent('mouseup', o))
    el.dispatchEvent(new MouseEvent('click', o))
  }
  function typeText(el, value) {
    el.focus()
    setNative(el, '')
    fire(el, 'input')
    setNative(el, String(value))
    el.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, data: String(value), inputType: 'insertText' }))
    fire(el, 'change')
  }

  const numOf = (s) => String(s).replace(/[^0-9.]/g, '').replace(/\.0+$/, '')
  const words = (s) => String(s ?? '').toLowerCase().replace(/[​-‍﻿]/g, '').split(/[^a-z0-9.]+/).filter(Boolean)
  // spellings / names that differ between Seller Desk and marketplaces
  const ALIASES = {
    'unstitchedblousepiece': ['separateblousepiece', 'unstitchedblouse', 'blousepiece'],
    'withblousepiece': ['separateblousepiece', 'runningblouse'],
    'kanjivaram': ['kanjeevaram', 'kanchivaram', 'kanchipuram', 'kanjivaramsilk', 'kanchipuramsilk'],
    'kanchivaram': ['kanjeevaram', 'kanjivaram', 'kanchipuram'],
    'kanchipuram': ['kanjeevaram', 'kanjivaram', 'kanchivaram'],
    'kanjivaramsilk': ['kanjeevaram', 'kanchipuramsilk', 'kanjivaram'],
    'lavender': ['lavendar', 'lilac'],
    'violet': ['purple', 'lavendar'],
    'wine': ['maroon', 'burgundy'],
    'navyblue': ['navy', 'blue'],
    'offwhite': ['cream', 'white'],
    'multicolour': ['multicolor'], 'multicolor': ['multicolour'],
    'grey': ['gray'], 'gray': ['grey'],
    'saree': ['sarees'], 'sarees': ['saree'],
    '1': ['single', 'packof1', 'one'],
    'drycleanonly': ['dryclean'], 'handwash': ['handwashonly'],
    'artsilk': ['artsilksilkblend', 'silkblend'],
  }
  function bestOption(options, value) {
    const v = normalise(value)
    if (!v) return null
    const items = options.map((o) => {
      const text = clean(o.textContent || o.label || o.value)
      return { o, t: normalise(text), w: words(text) }
    }).filter((x) => x.t)
    const exact = (key) => items.find((x) => x.t === key)
    let hit = exact(v)
    if (hit) return hit.o
    for (const alt of ALIASES[v] || []) { hit = exact(alt); if (hit) return hit.o }
    // numbers must match exactly ("1" never picks "Pack of 10"); allow units: 5 -> "5%", 5.5 -> "5.5 m"
    if (/^[0-9.]+$/.test(v)) {
      hit = items.find((x) => numOf(x.t) === numOf(v) && x.t.replace(/[0-9.]/g, '').length <= 7)
      return hit ? hit.o : null
    }
    // whole-word matching: every word of the option must be a word of the value ("stitched" != "unstitched")
    const vw = new Set(words(value))
    const sub = items.filter((x) => x.w.length && x.w.every((w) => vw.has(w)))
    if (sub.length) {
      sub.sort((a, b) => b.w.length - a.w.length || words(value).indexOf(a.w[0]) - words(value).indexOf(b.w[0]))
      return sub[0].o
    }
    // value words inside a longer option ("Maroon" -> "Maroon Red"): only when the value is a single word or two
    if (vw.size <= 2) {
      const sup = items.filter((x) => [...vw].every((w) => x.w.includes(w)))
      if (sup.length) { sup.sort((a, b) => a.w.length - b.w.length); return sup[0].o }
    }
    return null
  }

  const OPTION_SEL = '[role=option], [role=listbox] li, [role=menu] li, [role=menu] [role=menuitem], li[data-value], .dropdown-item'
  const POPUP_SEL = '.MuiPopover-root, .MuiPopper-root, .MuiAutocomplete-popper, [role=listbox], [role=menu], [role=dialog], .ant-select-dropdown, .rc-virtual-list'
  const popups = () => deepAll(document, POPUP_SEL).filter((p) => !inPanel(p) && visible(p))
  function visibleOptions(scope) {
    const root = scope || document
    return deepAll(root, OPTION_SEL).filter((o) => !inPanel(o) && visible(o) &&
      (o.textContent || '').trim().length > 0 && (o.textContent || '').trim().length < 80)
  }
  /** Leaf text rows inside a popup that has no proper option elements (e.g. checkbox lists with Apply). */
  function textOptions(pop) {
    return [...pop.querySelectorAll('p, span, div, label')].filter((e) => {
      if (!visible(e) || e.closest('button')) return false
      const t = (e.textContent || '').trim()
      return t && t.length < 60 && ![...e.children].some((c) => (c.textContent || '').trim() === t)
    })
  }
  async function closePopups() {
    for (let i = 0; i < 4; i++) {
      const open = popups().filter((p) => p.matches('.MuiPopover-root, .MuiPopper-root, .MuiAutocomplete-popper, [role=listbox], [role=menu]'))
      if (!open.length) return
      document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      for (const p of open) {
        const bd = p.querySelector('.MuiBackdrop-root')
        if (bd) realClick(bd)
      }
      if (i > 0) document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      await sleep(200)
    }
  }
  const searchBoxes = (scope) => deepAll(scope || document, 'input[type=search], input[placeholder*="earch" i], input[aria-autocomplete]')
    .filter((i) => visible(i) && !inPanel(i))
  const APPLY_RE = /^(apply|done|ok|save|select|confirm)$/i

  async function chooseFromList(trigger, value, typeInto) {
    await closePopups()
    const popsBefore = new Set(popups())
    const before = new Set(visibleOptions())
    const searchBefore = new Set(searchBoxes())
    trigger.focus?.()
    realClick(trigger)
    if (typeInto) typeText(typeInto, value)
    // wait for the list (some lists load lazily)
    let pop = null; let opts = []
    const end = Date.now() + 3500
    while (Date.now() < end) {
      await sleep(120)
      pop = popups().filter((p) => !popsBefore.has(p)).pop() || null
      opts = pop ? visibleOptions(pop) : visibleOptions().filter((o) => !before.has(o))
      if (!opts.length && typeInto) opts = visibleOptions()
      if (opts.length || (pop && textOptions(pop).length && Date.now() > end - 2800)) break
    }
    // a search box inside the list narrows long lists (Meesho "Type" has ~90 entries)
    let pick = bestOption(opts, value)
    if (!pick && !typeInto) {
      const own = pop ? searchBoxes(pop)[0] : searchBoxes().find((i) => !searchBefore.has(i))
      if (own) {
        // try the value, then its known alternative spellings (Kanjivaram -> Kanjeevaram)
        for (const q of [String(value), ...(ALIASES[normalise(value)] || [])]) {
          typeText(own, q)
          await sleep(500)
          opts = pop ? visibleOptions(pop) : visibleOptions()
          pick = bestOption(opts, value)
          if (pick) break
        }
        if (!pick) { typeText(own, ''); await sleep(300); opts = pop ? visibleOptions(pop) : visibleOptions() }
      }
    }
    // checkbox lists without option roles (Meesho "Size": Free Size + Apply)
    let viaText = false
    if (!pick && pop && !opts.length) {
      const rows = textOptions(pop)
      pick = bestOption(rows, value)
      viaText = !!pick
      if (!opts.length) opts = rows
    }
    if (pick) {
      pick.scrollIntoView?.({ block: 'nearest' })
      realClick(viaText ? (pick.parentElement || pick) : pick)
      await sleep(200)
      const apply = pop && [...pop.querySelectorAll('button')].find((b) => APPLY_RE.test(b.textContent.trim()))
      if (apply) { realClick(apply); await sleep(300) }
      await closePopups()
      return { ok: true, chosen: clean(pick.textContent) }
    }
    const sample = opts.slice(0, 12).map((o) => clean(o.textContent)).filter(Boolean)
    await closePopups()
    if (typeInto) { typeInto.blur(); fire(typeInto, 'blur') }
    return { ok: false, reason: opts.length ? 'no matching option' : 'list did not open', options: sample }
  }

  async function enter(el, kind, value) {
    const v = String(value)
    if (kind === 'text') {
      typeText(el, v)
      el.blur(); fire(el, 'blur')
      await sleep(20)
      return el.value === v || el.value.replace(/,/g, '') === v ? { ok: true } : { ok: true, note: 'value changed by the site' }
    }
    if (kind === 'select') {
      const opt = bestOption([...el.options], v)
      if (!opt) return { ok: false, reason: 'no matching option', options: [...el.options].map((o) => o.text).slice(0, 12) }
      setNative(el, opt.value)
      fire(el, 'input'); fire(el, 'change')
      return { ok: true, chosen: opt.text }
    }
    if (kind === 'editable') {
      el.focus()
      document.execCommand('selectAll', false)
      document.execCommand('insertText', false, v)
      return { ok: true }
    }
    if (kind === 'combo') return chooseFromList(el, v, el)
    // click-to-open dropdown (may open its own search box — handled in chooseFromList)
    return chooseFromList(el, v, null)
  }

  function mark(el, ok) {
    const root = el.getRootNode()
    const target = root instanceof ShadowRoot && root.host.id !== HOST_ID ? root.host : el
    target.style.outline = ok ? '2px solid #2f9e5b' : '2px solid #e0a100'
    target.style.outlineOffset = '1px'
  }
  function clearMarks() {
    deepAll(document, '[style*="outline"]').forEach((e) => {
      if (!inPanel(e) && /2px solid (rgb\(47, 158, 91\)|rgb\(224, 161, 0\)|#2f9e5b|#e0a100)/.test(e.style.outline)) e.style.outline = ''
    })
  }

  // ------------------------------------------------------------- main fill
  function applyMap(value, map) {
    if (value == null || !map) return value
    const k = String(value)
    if (k in map) return map[k]
    const nk = normalise(k)
    for (const [from, to] of Object.entries(map)) if (normalise(from) === nk) return to
    return value
  }

  function plan(learned = []) {
    const byLabel = Object.fromEntries(learned.map((l) => [l.label_norm, l]))
    return findControls().map((el) => {
      const label = labelOf(el)
      const norm = normalise(label)
      const taught = byLabel[norm]
      let source = null; let how = null; let entry = null
      if (taught) { source = taught.source; how = 'taught'; entry = taught }
      else if (!/^search/.test(norm)) { source = guess(label); how = source ? 'auto' : null }
      return { el, label, norm, kind: kindOf(el), source, how, entry }
    })
  }

  async function fill(payloadOrList, learned, opts = {}) {
    if (!opts._keepMarks) clearMarks()
    const payloads = Array.isArray(payloadOrList) ? payloadOrList : [payloadOrList]
    const results = []
    const used = new Set()
    let fields = plan(learned)
    if (opts._only) fields = fields.filter((f) => opts._only.has(f.el))
    // a label that repeats on the page = one section per variant (e.g. Meesho catalog with several products)
    const seen = {}
    const total = {}
    fields.forEach((f) => { total[f.norm] = (total[f.norm] || 0) + 1 })
    for (const f of fields) {
      const occ = seen[f.norm] = (seen[f.norm] ?? -1) + 1
      const idx = payloads.length > 1 && total[f.norm] > 1 ? occ : 0
      const payload = payloads[idx]
      const tag = payloads.length > 1 && total[f.norm] > 1 ? ` · variant ${idx + 1}` : ''
      const base = { label: (f.label || '(no label)') + tag, source: f.source, how: f.how, el: f.el }
      if (!payload) { results.push({ ...base, status: 'skipped', reason: 'More sections than variants' }); continue }
      if (f.how === 'taught' && !f.source) { results.push({ ...base, status: 'ignored' }); continue }
      if (!f.source) { results.push({ ...base, status: 'unknown' }); continue }
      let value = f.source === 'const.custom' ? f.entry?.value : payload.values[f.source]
      value = applyMap(value, f.entry?.value_map)
      if (value == null || value === '') { results.push({ ...base, status: 'empty', reason: 'No value in Seller Desk' }); continue }
      // the same source should not fill two different fields (e.g. two 'price' boxes) unless taught
      const useKey = `${idx}:${f.source}`
      if (used.has(useKey) && f.how === 'auto' && !/^image\.|^gen\.bullet/.test(f.source)) {
        results.push({ ...base, status: 'unknown', reason: 'Looks like a field already filled; teach it if needed' }); continue
      }
      if (opts.onlyEmpty && currentValue(f.el)) { results.push({ ...base, status: 'skipped', reason: 'Already has a value' }); continue }
      try {
        f.el.scrollIntoView?.({ block: 'center' })
        const r = await enter(f.el, f.kind, value)
        mark(f.el, r.ok)
        used.add(useKey)
        results.push({ ...base, value: r.chosen || String(value), status: r.ok ? 'filled' : 'failed', reason: r.reason, options: r.options })
      } catch (e) {
        mark(f.el, false)
        results.push({ ...base, value: String(value), status: 'failed', reason: String(e.message || e) })
      }
      await sleep(opts.delay ?? 40)
    }
    // fields that appeared because of earlier choices (e.g. Meesho's price table after Size)
    if (!opts._second) {
      await sleep(400)
      const done = new Set(results.map((r) => r.el))
      const fresh = plan(learned).filter((f) => !done.has(f.el))
      if (fresh.length) {
        const more = await fill(payloadOrList, learned, { ...opts, _second: true, _only: new Set(fresh.map((f) => f.el)), _keepMarks: true })
        results.push(...more)
      }
    }
    if (!opts._second) window.scrollTo({ top: 0, behavior: 'smooth' })
    return results
  }

  async function fillOne(el, payload, entry) {
    let value = entry.source === 'const.custom' ? entry.value : payload.values[entry.source]
    value = applyMap(value, entry.value_map)
    if (value == null || value === '') return { ok: false, reason: 'No value in Seller Desk' }
    const r = await enter(el, kindOf(el), value)
    mark(el, r.ok)
    return r
  }

  // ------------------------------------------------------------- variant tabs (Meesho: Product 1, Product 2 …)
  function productTabs() {
    const out = []
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      const m = n.textContent.trim().match(/^(product|variant|item)\s+(\d+)$/i)
      if (!m || !n.parentElement || inPanel(n.parentElement) || !visible(n.parentElement)) continue
      const tab = n.parentElement.closest('[role=tab], button, a, li') || n.parentElement.parentElement || n.parentElement
      out[Number(m[2]) - 1] = tab
    }
    return out.filter(Boolean)
  }
  async function openProductTab(i) {
    const tabs = productTabs()
    if (!tabs[i]) return false
    realClick(tabs[i])
    await sleep(900)
    return true
  }

  // ------------------------------------------------------------- images
  function b64ToFile(b64, type, name) {
    const bin = atob(b64)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    return new File([bytes], name, { type })
  }
  function fileInputs() {
    return deepAll(document, 'input[type=file]').filter((i) => !inPanel(i) && !i.disabled &&
      (!i.accept || /image|jpe?g|png|webp/i.test(i.accept)))
  }
  async function attachImages(files) {
    const inputs = fileInputs()
    if (!inputs.length) return { ok: false, reason: 'No image upload box found on this page. Open the images step first.' }
    const multi = inputs.find((i) => i.multiple)
    if (multi) {
      const dt = new DataTransfer(); files.forEach((f) => dt.items.add(f))
      multi.files = dt.files; fire(multi, 'input'); fire(multi, 'change')
      return { ok: true, count: files.length }
    }
    // one input per image slot (front, back, …)
    let n = 0
    for (let i = 0; i < Math.min(inputs.length, files.length); i++) {
      const dt = new DataTransfer(); dt.items.add(files[i])
      inputs[i].files = dt.files; fire(inputs[i], 'input'); fire(inputs[i], 'change')
      n++
      await sleep(300)
    }
    return { ok: true, count: n }
  }

  // ------------------------------------------------------------- stock on inventory / listings pages
  const STOCK_WORDS = /\b(stock|inventory|quantity|qty|available)\b/i

  /** Find the page row for each key (SKU, ASIN, FSN). Returns Map key -> row element. */
  function findRows(keys) {
    const wanted = new Set(keys.filter(Boolean).map((k) => String(k).trim().toLowerCase()))
    const found = new Map()
    const roots = [document, ...deepAll(document, '*').filter((e) => e.shadowRoot && e.id !== HOST_ID).map((e) => e.shadowRoot)]
    for (const r of roots) {
      const tw = document.createTreeWalker(r, NodeFilter.SHOW_TEXT)
      for (let n = tw.nextNode(); n; n = tw.nextNode()) {
        const raw = n.textContent.trim()
        if (!raw || raw.length > 80) continue
        const tokens = [raw, ...raw.split(/[\s:|,]+/)].map((t) => t.toLowerCase())
        const key = tokens.find((t) => wanted.has(t))
        if (!key || found.has(key) || !n.parentElement || inPanel(n.parentElement)) continue
        found.set(key, rowOf(n.parentElement, wanted))
      }
    }
    return found
  }
  function rowOf(el, wanted) {
    const tr = el.closest('tr, [role=row]')
    if (tr) return tr
    // grow upwards until the container holds an input or a stock number, but never two keys
    let best = el
    for (let a = el.parentElement, i = 0; a && a !== document.body && i < 8; a = a.parentElement, i++) {
      const text = a.textContent.toLowerCase()
      let keys = 0
      for (const k of wanted) if (text.includes(k)) keys++
      if (keys > 1) break
      best = a
      if (a.querySelector('input') || STOCK_WORDS.test(a.textContent)) {
        // one more level only if this one has no input yet
        if (a.querySelector('input')) break
      }
    }
    return best
  }
  function stockInput(row) {
    const inputs = deepAll(row, 'input:not([type=hidden]):not([type=checkbox]):not([type=radio])').filter((i) => visible(i) && !i.disabled)
    if (!inputs.length) return null
    const labelled = inputs.find((i) => STOCK_WORDS.test(labelOf(i)) || STOCK_WORDS.test(i.name || '') || STOCK_WORDS.test(i.placeholder || ''))
    return labelled || inputs.find((i) => i.type === 'number' || i.inputMode === 'numeric') || (inputs.length === 1 ? inputs[0] : null)
  }
  function readStock(row) {
    const inp = stockInput(row)
    if (inp && inp.value !== '' && !Number.isNaN(Number(inp.value))) return Number(inp.value)
    const cell = [...row.querySelectorAll('td, [role=gridcell], [role=cell]')].find((c) => STOCK_WORDS.test(headerFor(c)))
    if (cell) {
      const m = cell.textContent.match(/-?\d+/)
      if (m) return Number(m[0])
    }
    const m = row.textContent.match(/(?:stock|inventory|quantity|qty|available)[^0-9\-]{0,15}(-?\d+)/i)
    return m ? Number(m[1]) : null
  }
  function scanStock(items) {
    // items: [{product_id, keys:[...]}] -> [{product_id, key, stock, row}]
    const rows = findRows(items.flatMap((i) => i.keys))
    const out = []
    for (const it of items) {
      for (const k of it.keys) {
        const row = k && rows.get(String(k).trim().toLowerCase())
        if (row) { out.push({ product_id: it.product_id, key: k, row, stock: readStock(row) }); break }
      }
    }
    return out
  }
  async function setStock(row, value, clickSave) {
    const inp = stockInput(row)
    if (!inp) {
      // some pages show the number with an edit (pencil) button first
      const edit = [...row.querySelectorAll('button, [role=button], a')].find((b) => /edit|update|✎|pencil/i.test(b.textContent + (b.getAttribute('aria-label') || '') + (b.title || '')))
      if (edit) { realClick(edit); await sleep(400) }
    }
    const input = stockInput(row)
    if (!input) return { ok: false, reason: 'No stock box in this row' }
    typeText(input, String(value))
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    input.blur(); fire(input, 'blur')
    mark(input, true)
    if (clickSave) {
      await sleep(150)
      const save = [...row.querySelectorAll('button, [role=button]')].find((b) => /^(save|update|submit|done|✓|ok)$/i.test(b.textContent.trim()))
      if (save) { realClick(save); await sleep(500) } else return { ok: true, note: 'No Save button in the row — save on the page' }
    }
    return { ok: true }
  }

  // ------------------------------------------------------------- orders on orders / returns pages
  const ORDER_RE = {
    amazon: /\b\d{3}-\d{7}-\d{7}\b/g,
    flipkart: /\bOD\d{15,21}\b/g,
    meesho: /\b\d{8,}_\d{1,3}\b/g,
  }
  const STATUS_RE = /(rto[\w ]{0,20}|return to origin|courier return|undelivered|customer return|return (requested|initiated|completed|received|approved)|returned|cancell?ed( by \w+)?|delivered|out for delivery|in transit|shipped|dispatched|picked up|handed over|ready to ship|pending|on hold|unshipped|new order|label (downloaded|generated)|manifested)/i
  const DATE_RE = /\b(\d{1,2}[\s\-/.](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-/.,]+\d{2,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\/\d{1,2}\/\d{2,4})\b/i

  function activeTabText() {
    const sel = deepAll(document, '[role=tab][aria-selected=true], .active[role=tab], [class*="tab"][class*="active" i], [class*="Tab"][class*="selected" i]')
      .filter((e) => !inPanel(e) && visible(e))
    return sel.map((e) => clean(e.textContent)).find((t) => t && t.length < 40) || ''
  }

  function orderRow(el, re) {
    const tr = el.closest('tr, [role=row]')
    if (tr) return tr
    let best = el
    for (let a = el.parentElement, i = 0; a && a !== document.body && i < 10; a = a.parentElement, i++) {
      const ids = new Set((a.textContent.match(re) || []))
      if (ids.size > 1) break
      best = a
    }
    return best
  }

  function scanOrders(marketplace, knownSkus = []) {
    const re = ORDER_RE[marketplace] || ORDER_RE.meesho
    const skus = new Set(knownSkus.map((s) => String(s).toLowerCase()))
    const out = new Map()
    const roots = [document, ...deepAll(document, '*').filter((e) => e.shadowRoot && e.id !== HOST_ID).map((e) => e.shadowRoot)]
    for (const r of roots) {
      const tw = document.createTreeWalker(r, NodeFilter.SHOW_TEXT)
      for (let n = tw.nextNode(); n; n = tw.nextNode()) {
        const ids = n.textContent.match(re)
        if (!ids || !n.parentElement || inPanel(n.parentElement) || !visible(n.parentElement)) continue
        for (const id of ids) {
          if (out.has(id)) continue
          // labels and ids can be glued together in textContent ("Order ID214567890_1"): count without \b
          const row = orderRow(n.parentElement, new RegExp(re.source.replace(/\\b/g, ''), 'g'))
          const text = row.innerText || row.textContent || ''
          const words = text.split(/[\s,|:]+/).map((w) => w.toLowerCase())
          const sku = words.find((w) => skus.has(w))
          const st = text.match(STATUS_RE)
          const dt = text.match(DATE_RE)
          const amt = text.match(/₹\s?([\d,]+(?:\.\d+)?)/)
          const awb = text.match(/\b(?:awb|tracking(?: id| no\.?)?)[\s:#]*([A-Z0-9]{8,22})\b/i)
          let orderId = id; let sub = ''
          if (marketplace === 'meesho' && /_\d+$/.test(id)) { sub = id; orderId = id.replace(/_\d+$/, '') }
          out.set(id, {
            order_id: orderId, sub_order_id: sub, sku: sku ? knownSkus.find((k) => k.toLowerCase() === sku) : null,
            status_text: st ? clean(st[0]) : null, order_date: dt ? dt[0] : null,
            sale_amount: amt ? Number(amt[1].replace(/,/g, '')) : null, awb: awb ? awb[1] : null,
          })
        }
      }
    }
    return [...out.values()]
  }

  // ------------------------------------------------------------- teach: pick a field on the page
  function pickField() {
    return new Promise((resolve) => {
      const box = document.createElement('div')
      Object.assign(box.style, { position: 'fixed', pointerEvents: 'none', border: '2px dashed #7a1f2b', background: 'rgba(122,31,43,.08)', zIndex: 2147483646, borderRadius: '4px', transition: 'all .05s' })
      document.documentElement.appendChild(box)
      const controlFrom = (e) => {
        for (const n of e.composedPath()) {
          if (!(n instanceof Element)) continue
          if (n.id === HOST_ID) return null
          if (n.matches(CTRL)) return n
          if (n.tagName === 'LABEL' && n.control) return n.control
          const inner = n.querySelector?.(CTRL)
          if (inner && n.querySelectorAll(CTRL).length === 1) return inner
          if (n.shadowRoot) { const s = n.shadowRoot.querySelector(CTRL); if (s) return s }
        }
        return null
      }
      const move = (e) => {
        const c = controlFrom(e)
        if (!c) { box.style.display = 'none'; return }
        const r = c.getBoundingClientRect()
        Object.assign(box.style, { display: 'block', left: `${r.left - 3}px`, top: `${r.top - 3}px`, width: `${r.width + 6}px`, height: `${r.height + 6}px` })
      }
      const done = (val) => {
        document.removeEventListener('mousemove', move, true)
        document.removeEventListener('click', click, true)
        document.removeEventListener('keydown', key, true)
        box.remove()
        resolve(val)
      }
      const click = (e) => {
        const c = controlFrom(e)
        if (!c) return
        e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation()
        done({ el: c, label: labelOf(c), kind: kindOf(c) })
      }
      const key = (e) => { if (e.key === 'Escape') done(null) }
      document.addEventListener('mousemove', move, true)
      document.addEventListener('click', click, true)
      document.addEventListener('keydown', key, true)
    })
  }

  globalThis.SDEngine = { productTabs, openProductTab, closePopups, bestOption, headerAbove, scanOrders, activeTabText, scanStock, setStock, normalise, guess, setSynonyms, findControls, labelOf, kindOf, plan, fill, fillOne, attachImages, b64ToFile, pickField, clearMarks, HOST_ID }
})()

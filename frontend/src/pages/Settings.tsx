import { useEffect, useState } from 'react'
import { api, type Row } from '../api'
import { PageHead, toast, useLoad } from '../components/ui'

export default function Settings() {
  const { data } = useLoad<Row>(() => api.get('/api/settings'))
  const [s, setS] = useState<Row>({})
  useEffect(() => { if (data) setS(data) }, [data])
  const save = async () => {
    try { setS(await api.put('/api/settings', s)); toast.ok('Settings saved') } catch (e) { toast.err(e) }
  }
  return (
    <>
      <PageHead title="Settings" />
      <div className="card" style={{ maxWidth: 620 }}>
        <h2>AI drafting</h2>
        <p className="small muted">Create an API key at console.anthropic.com (API keys). Anthropic bills usage per call; check current prices on their pricing page.</p>
        <div className="field"><label>Anthropic API key</label>
          <input type="password" autoComplete="off" value={s.anthropic_api_key || ''} placeholder="sk-ant-…"
            onFocus={(e) => e.target.value.startsWith('•') && setS({ ...s, anthropic_api_key: '' })}
            onChange={(e) => setS({ ...s, anthropic_api_key: e.target.value })} />
          <div className="help">Stored encrypted on this PC.</div></div>
        <div className="field"><label>Model</label><input value={s.ai_model || ''} onChange={(e) => setS({ ...s, ai_model: e.target.value })} />
          <div className="help">Default claude-sonnet-5-5. Use claude-haiku-5-5 for cheaper bulk drafts.</div></div>
        <div className="field"><label>Meesho description languages</label><input value={s.meesho_languages || ''} onChange={(e) => setS({ ...s, meesho_languages: e.target.value })} placeholder="English, Tamil, Hindi, Telugu, Malayalam, Kannada" />
          <div className="help">AI descriptions for Meesho mix English with these languages (up to 1400 characters, with keyword tags at the end). Write just “English” to keep descriptions in English only. With many languages each gets one short sentence to fit the 1400 limit.</div></div>
        <button className="primary" onClick={save}>Save</button>
      </div>
      <div className="card" style={{ maxWidth: 620 }}>
        <h2>Backups</h2>
        <p className="small">All data lives in the <code>data</code> folder next to the app: <code>seller_desk.db</code>, <code>secret.key</code>, templates and generated files. Back up the whole folder. Without <code>secret.key</code> the saved marketplace credentials can't be read, so keep it with the database and never upload it to GitHub.</p>
      </div>
    </>
  )
}

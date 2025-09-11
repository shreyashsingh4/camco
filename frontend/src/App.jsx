import { useState, useMemo } from 'react'
import { apiGet, apiPost } from './api'

export default function App() {
  const [health, setHealth] = useState(null)
  const [message, setMessage] = useState('')
  const [jobId, setJobId] = useState('')
  const [plans, setPlans] = useState([])
  const [overrideRegion, setOverrideRegion] = useState('')
  const [error, setError] = useState(null)

  async function checkHealth() {
    resetMsgs()
    try {
      const data = await apiGet('/health')
      setHealth(data)
      setMessage('Backend is reachable ✅')
    } catch (e) {
      setError(e.message)
    }
  }

  async function seedRegions() {
    resetMsgs(); setMessage('Seeding regions...')
    try {
      await apiPost('/api/signals', {
        region: 'us-east-1', provider: 'aws',
        carbon_gco2_per_kwh: 350, usd_per_cpu_hour: 0.032, usd_per_gpu_hour: 2.1,
        latency_to_data_ms: 90
      })
      await apiPost('/api/signals', {
        region: 'westeurope', provider: 'azure',
        carbon_gco2_per_kwh: 220, usd_per_cpu_hour: 0.036, usd_per_gpu_hour: 2.3,
        latency_to_data_ms: 130
      })
      await apiPost('/api/signals', {
        region: 'us-central1', provider: 'gcp',
        carbon_gco2_per_kwh: 180, usd_per_cpu_hour: 0.031, usd_per_gpu_hour: 2.0,
        latency_to_data_ms: 110
      })
      setMessage('Seeded 3 regions ✅')
    } catch (e) {
      setError(e.message)
    }
  }

  async function submitSampleJob() {
    resetMsgs(); setMessage('Submitting job...')
    try {
      const res = await apiPost('/api/jobs', {
        name: 'daily_etl',
        cpu_hours: 100,
        gpu_hours: 0,
        deadline_minutes: 240,
        latency_budget_ms: 120,
        data_region: 'us-central1',
        cost_cap_usd: 35,
        carbon_weight: 0.7,
        cost_weight: 0.3
      })
      setJobId(res.job_id)
      setPlans([])
      setOverrideRegion('')
      setMessage(`Job created: ${res.job_id} ✅`)
    } catch (e) {
      setError(e.message)
    }
  }

  async function loadPlans() {
    if (!jobId) { setError('No job_id yet. Submit a job first.'); return }
    resetMsgs(); setMessage('Loading plans...')
    try {
      const data = await apiGet(`/api/jobs/${jobId}`)
      setPlans(data.plans || [])
      setMessage('Loaded plans ✅')
    } catch (e) {
      setError(e.message)
    }
  }

  const feasibleOptions = useMemo(
    () => plans.filter(p => p.feasible).map(p => p.region),
    [plans]
  )

  async function doOverride() {
    if (!jobId) { setError('No job_id.'); return }
    if (!overrideRegion) { setError('Pick a region to override to.'); return }
    resetMsgs(); setMessage(`Overriding to ${overrideRegion}...`)
    try {
      // POST /api/override/{job_id}?region=...
      await apiPost(`/api/override/${jobId}?region=${encodeURIComponent(overrideRegion)}&rationale=demo-switch`, {})
      // reload plans to reflect the change
      await loadPlans()
      setMessage(`Overridden to ${overrideRegion} ✅`)
    } catch (e) {
      setError(e.message)
    }
  }

  async function downloadReport() {
    if (!jobId) { setError('No job_id.'); return }
    resetMsgs(); setMessage('Generating report...')
    try {
      // First ensure the report exists (optional)
      await apiGet(`/api/reports/${jobId}`)

      // Now fetch the file bytes with header, then trigger a download
      const res = await fetch(`/api/reports/${jobId}/file`, {
        headers: { 'X-API-Key': 'devkey' }
      })
      if (!res.ok) throw new Error(`Download failed: ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `reports_${jobId}.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setMessage('Report downloaded ✅')
    } catch (e) {
      setError(e.message)
    }
  }

  function resetMsgs() { setMessage(''); setError(null) }

  return (
    <div style={{ fontFamily: 'ui-sans-serif, system-ui', padding: 24, maxWidth: 980 }}>
      <h1>CAMCO – Tiny Frontend</h1>

      <div style={{ display:'flex', gap: 12, flexWrap:'wrap', marginBottom: 16 }}>
        <button onClick={checkHealth} style={btn}>Check Backend Health</button>
        <button onClick={seedRegions} style={btn}>Seed Regions</button>
        <button onClick={submitSampleJob} style={btn}>Submit Sample Job</button>
        <button onClick={loadPlans} style={btn} disabled={!jobId}>Load Plans</button>
      </div>

      {jobId && (
        <div style={{ display:'flex', gap:12, alignItems:'center', flexWrap:'wrap', marginBottom: 8 }}>
          <strong>job_id:</strong> <span>{jobId}</span>
          <select value={overrideRegion} onChange={e => setOverrideRegion(e.target.value)} style={select}>
            <option value="">-- pick feasible region --</option>
            {feasibleOptions.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <button onClick={doOverride} style={btn} disabled={!overrideRegion}>Override</button>
          <button onClick={downloadReport} style={btn}>Generate & Download PDF</button>
        </div>
      )}

      {message && <p style={{ color:'#0a0' }}>{message}</p>}
      {error && <pre style={err}>{error}</pre>}

      {health && (
        <pre style={pre}>{JSON.stringify(health, null, 2)}</pre>
      )}

      {plans.length > 0 && (
        <table style={table}>
          <thead>
            <tr>
              <th>Region</th>
              <th>CO₂e (kg)</th>
              <th>Cost ($)</th>
              <th>Feasible</th>
              <th>Score</th>
              <th>Chosen</th>
            </tr>
          </thead>
          <tbody>
            {plans.map(p => (
              <tr key={p.region}>
                <td>{p.region}</td>
                <td>{p.co2e_kg.toFixed(3)}</td>
                <td>{p.cost_usd.toFixed(3)}</td>
                <td>{String(p.feasible)}</td>
                <td>{p.score.toFixed(6)}</td>
                <td>{p.chosen ? '✅' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

const btn = { padding:'8px 12px', cursor:'pointer', borderRadius:8, border:'1px solid #ccc', background:'#f5f5f5' }
const select = { padding:'6px 8px', borderRadius:8, border:'1px solid #ccc', background:'#fff' }
const pre = { background:'#111', color:'#0f0', padding:12, marginTop:12, borderRadius:8, maxHeight:240, overflow:'auto' }
const err = { background:'#300', color:'#f77', padding:12, marginTop:12, borderRadius:8 }
const table = { width:'100%', borderCollapse:'collapse', marginTop:16, border:'1px solid #ddd' }

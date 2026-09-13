'use client';

import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { PageTitle, Table, Loading, ErrorState, Badge, Button } from '../../components/ui';
import { dateTime } from '../../lib/format';

const types = [
  ['payments', 'Payments'],
  ['settlements', 'Settlements'],
  ['refunds', 'Refunds'],
  ['bank_transactions', 'Bank transactions'],
];

export default function Ingestion() {
  const [data, setData] = useState<any>(null);
  const [type, setType] = useState('payments');
  const [provider, setProvider] = useState('razorpay');
  const [file, setFile] = useState<File | null>(null);
  const [selected, setSelected] = useState<any>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const load = () => api<any>('/data-onboarding/uploads').then(setData).catch((e) => setError(e.message));
  useEffect(() => { void load(); }, []);

  async function upload() {
    if (!file) { setError('Choose a CSV or XLSX file first.'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const body = new FormData();
      body.append('file', file);
      body.append('data_type', type);
      body.append('provider', provider);
      const value = await api<any>('/data-onboarding/uploads', { method: 'POST', body });
      setSelected(value); setMapping(value.mapping || {}); setMessage('File uploaded and validated. Review the mapping before importing.');
      setFile(null); await load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function validate() {
    if (!selected) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const value = await api<any>(`/data-onboarding/uploads/${selected.id}/validate`, { method: 'POST', body: JSON.stringify({ mapping }) });
      setSelected(value); setMessage(value.validation?.valid ? 'Validation passed. The file is ready to import.' : 'Validation found errors. Fix the mapping and validate again.'); await load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function importFile() {
    if (!selected) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const value = await api<any>(`/data-onboarding/uploads/${selected.id}/import`, { method: 'POST' });
      setSelected(value); setMessage(`Import complete: ${value.import_result?.created ?? 0} records created, ${value.import_result?.duplicates ?? 0} duplicates.`); await load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function reconcile() {
    setBusy(true); setError(''); setMessage('');
    try { await api('/reconciliation/run', { method: 'POST' }); setMessage('Reconciliation completed. Open Reconciliation or Exceptions to review the result.'); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }

  if (error && !data) return <ErrorState message={error} onRetry={load} />;
  if (!data) return <Loading />;
  const validation = selected?.validation || {};
  const headers = selected?.headers || [];
  const fields = Object.keys(selected?.mapping || mapping || {});

  return <>
    <PageTitle title="Data onboarding" description="Upload customer data, confirm the mapping, import it safely, then run the existing reconciliation engine." />

    <section className="panel" style={{ marginBottom: 16 }}>
      <h3>1. Upload data</h3>
      <p className="muted">CSV and XLSX are supported. Files are limited to 5 MB and 10,000 rows for the pilot workflow.</p>
      <div className="filters">
        <label>Data type<select value={type} onChange={(e) => setType(e.target.value)} disabled={busy}>{types.map(([v, l]) => <option value={v} key={v}>{l}</option>)}</select></label>
        <label>Provider<input value={provider} onChange={(e) => setProvider(e.target.value)} disabled={busy} placeholder="razorpay" /></label>
        <label>File<input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => setFile(e.target.files?.[0] || null)} disabled={busy} /></label>
      </div>
      <Button disabled={busy || !file} onClick={upload}>{busy ? 'Working…' : 'Upload & validate'}</Button>
    </section>

    {selected && <section className="panel" style={{ marginBottom: 16 }}>
      <h3>2. Review mapping</h3>
      <p className="muted"><b>{selected.filename}</b> · {selected.row_count} rows · <Badge value={selected.status} /></p>
      <div className="filters">
        {fields.map((field) => <label key={field}>{field}<select value={mapping[field] || ''} onChange={(e) => setMapping({ ...mapping, [field]: e.target.value })}>
          <option value="">— not mapped —</option>{headers.map((header: string) => <option value={header} key={header}>{header}</option>)}
        </select></label>)}
      </div>
      <Button disabled={busy} onClick={validate}>Validate mapping</Button>
      <div className="financial" style={{ marginTop: 16 }}>
        <div className="metric"><span>Rows</span><b>{validation.rows ?? selected.row_count}</b></div>
        <div className="metric"><span>Valid</span><b>{validation.valid_rows ?? '—'}</b></div>
        <div className="metric"><span>Warnings</span><b>{validation.warning_rows ?? '—'}</b></div>
        <div className="metric"><span>Errors</span><b>{validation.error_rows ?? '—'}</b></div>
      </div>
      {validation.errors?.length > 0 && <div className="error" style={{ marginTop: 12 }}>{validation.errors.map((x: string) => <div key={x}>{x}</div>)}</div>}
      {validation.warnings?.length > 0 && <div className="notice" style={{ marginTop: 12 }}>{validation.warnings.map((x: string) => <div key={x}>{x}</div>)}</div>}
    </section>}

    {selected && validation.valid && selected.status !== 'IMPORTED' && <section className="panel" style={{ marginBottom: 16 }}>
      <h3>3. Import and reconcile</h3>
      <p className="muted">Importing uses the existing server-side normalization and financial ingestion rules. Nothing is calculated in the browser.</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><Button disabled={busy} onClick={importFile}>Import {selected.row_count} records</Button><Button disabled={busy} onClick={reconcile}>Run reconciliation</Button></div>
    </section>}

    {selected?.status === 'IMPORTED' && <section className="panel" style={{ marginBottom: 16 }}>
      <h3>4. Ready for reconciliation</h3>
      <p className="muted">Import completed. Run the deterministic reconciliation engine to create matched results and exceptions.</p>
      <Button disabled={busy} onClick={reconcile}>Run reconciliation</Button>
    </section>}

    {message && <div className="notice" style={{ marginBottom: 16 }}>{message}</div>}
    {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

    <section>
      <h3>Recent uploads</h3>
      <Table><thead><tr><th>File</th><th>Type</th><th>Provider</th><th>Rows</th><th>Status</th><th>Created</th></tr></thead><tbody>{data.items.map((x: any) => <tr key={x.id}><td>{x.filename}</td><td>{x.data_type.replaceAll('_', ' ')}</td><td>{x.provider || '—'}</td><td>{x.row_count}</td><td><Badge value={x.status} /></td><td>{dateTime(x.created_at)}</td></tr>)}</tbody></Table>
    </section>
  </>;
}

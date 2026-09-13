'use client';

import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { PageTitle, Loading, ErrorState, Button, Badge } from '../../components/ui';
import Link from 'next/link';
import { useAuth } from '../../lib/auth';

const labels: Record<string, string> = {
  D2C_ECOMMERCE: 'D2C / E-commerce',
  SAAS: 'SaaS',
  MARKETPLACE: 'Marketplace',
  EDTECH: 'EdTech',
  HEALTHCARE: 'Healthcare',
  OTHER: 'Other',
  UNDER_10K: 'Under 10K / month',
  '10K_100K': '10K–100K / month',
  '100K_1M': '100K–1M / month',
  '1M_5M': '1M–5M / month',
  OVER_5M: 'Over 5M / month',
  RAZORPAY: 'Razorpay',
  STRIPE: 'Stripe',
  CASHFREE: 'Cashfree',
  PAYU: 'PayU',
};

export default function OnboardingPage() {
  const { user } = useAuth();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState({ business_type: 'D2C_ECOMMERCE', monthly_transaction_band: 'UNDER_10K', primary_provider: 'RAZORPAY' });

  const load = () => api<any>('/onboarding').then((value) => {
    setData(value);
    setProfile({
      business_type: value.profile.business_type || 'D2C_ECOMMERCE',
      monthly_transaction_band: value.profile.monthly_transaction_band || 'UNDER_10K',
      primary_provider: value.profile.primary_provider || 'RAZORPAY',
    });
  }).catch((e) => setError(e.message));

  useEffect(() => { void load(); }, []);

  async function saveProfile() {
    setBusy(true); setError(''); setMessage('');
    try {
      const value = await api<any>('/onboarding/profile', { method: 'PUT', body: JSON.stringify(profile) });
      setData(value);
      setMessage('Business profile saved.');
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function complete() {
    setBusy(true); setError(''); setMessage('');
    try {
      const value = await api<any>('/onboarding/complete', { method: 'POST' });
      setData(value);
      setMessage('Onboarding completed. Your workspace is ready for normal operations.');
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }

  if (error && !data) return <ErrorState message={error} onRetry={load} />;
  if (!data) return <Loading />;

  const admin = user?.role === 'ADMIN';
  return <>
    <PageTitle title="Customer onboarding" description="Set up the workspace, connect your first data, run reconciliation, and make the account ready for daily finance operations." actions={<Badge value={data.status} />} />

    <section className="cards" style={{ marginBottom: 16 }}>
      <div className="panel">
        <h3>Workspace</h3>
        <p className="muted">{data.merchant?.name || 'RCAA customer'} · {data.merchant?.email || '—'}</p>
        <div className="notice">Financial truth stays in the backend. This setup page only configures customer preferences and shows readiness.</div>
      </div>
      <div className="panel">
        <h3>Data readiness</h3>
        <div className="financial">
          <div className="metric"><span>Payments</span><b>{data.counts.payments}</b></div>
          <div className="metric"><span>Settlements</span><b>{data.counts.settlements}</b></div>
          <div className="metric"><span>Bank records</span><b>{data.counts.bank_transactions}</b></div>
        </div>
      </div>
    </section>

    <section className="panel" style={{ marginBottom: 16 }}>
      <h3>Your first reconciliation</h3><p className="muted">Recommended path: <b>{data.recommended_path === 'RAZORPAY_CONNECTOR' ? 'Connect Razorpay automatically' : 'Import your finance files'}</b></p>{data.recommended_path === 'RAZORPAY_CONNECTOR' && <p><Link className="link" href="/connectors">Connect Razorpay →</Link></p>}
      <h3>Setup progress</h3>
      <div className="timeline" style={{ marginTop: 16 }}>
        {data.steps.map((step: any, index: number) => <div key={step.key}>
          <strong>{index + 1}. {step.title}</strong>
          <p className="muted" style={{ margin: '5px 0' }}>{step.description}</p>
          <Badge value={step.complete ? 'COMPLETE' : 'PENDING'} />
        </div>)}
      </div>
    </section>

    <section className="panel" style={{ marginBottom: 16 }}>
      <h3>Business profile</h3>
      <p className="muted">Used to configure the customer workspace and support the onboarding team. It doesn't change financial calculations.</p>
      <div className="filters">
        <label>Business type<select disabled={!admin || busy} value={profile.business_type} onChange={(e) => setProfile({ ...profile, business_type: e.target.value })}>
          {['D2C_ECOMMERCE','SAAS','MARKETPLACE','EDTECH','HEALTHCARE','OTHER'].map((x) => <option key={x} value={x}>{labels[x]}</option>)}
        </select></label>
        <label>Monthly transactions<select disabled={!admin || busy} value={profile.monthly_transaction_band} onChange={(e) => setProfile({ ...profile, monthly_transaction_band: e.target.value })}>
          {['UNDER_10K','10K_100K','100K_1M','1M_5M','OVER_5M'].map((x) => <option key={x} value={x}>{labels[x]}</option>)}
        </select></label>
        <label>Primary provider<select disabled={!admin || busy} value={profile.primary_provider} onChange={(e) => setProfile({ ...profile, primary_provider: e.target.value })}>
          {['RAZORPAY','STRIPE','CASHFREE','PAYU','OTHER'].map((x) => <option key={x} value={x}>{labels[x]}</option>)}
        </select></label>
      </div>
      {admin && <Button disabled={busy} onClick={saveProfile}>{busy ? 'Saving…' : 'Save profile'}</Button>}
      {!admin && <p className="muted">Only an administrator can change onboarding settings.</p>}
    </section>

    <section className="panel">
      <h3>Finish onboarding</h3>
      <p className="muted">The account can be marked complete after the profile is saved, payment and settlement data exist, and at least one successful reconciliation has run.</p>
      {data.complete ? <div className="notice">Onboarding is complete. Continue with Exceptions and Cases for daily operations.</div> : <Button disabled={!admin || busy || !data.ready_to_complete} onClick={complete}>{busy ? 'Completing…' : 'Complete onboarding'}</Button>}
      {message && <p className="muted">{message}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  </>;
}

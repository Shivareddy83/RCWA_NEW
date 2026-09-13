'use client';

import { FormEvent, useState } from 'react';
import Link from 'next/link';
import { api } from '../../lib/api';

export default function Register() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [merchantId, setMerchantId] = useState('');
  const [bootstrapToken, setBootstrapToken] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');

    if (password.length < 10) {
      setError('Password must be at least 10 characters.');
      return;
    }

    setBusy(true);
    try {
      await api('/auth/register', {
        method: 'POST',
        headers: { 'X-Bootstrap-Token': bootstrapToken },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          password,
          merchant_id: merchantId.trim(),
          role: 'ADMIN',
        }),
      });
      setSuccess(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Registration failed.');
    } finally {
      setBusy(false);
    }
  }

  if (success) {
    return (
      <main className="login">
        <div className="login-card">
          <div className="brandmark">R</div>
          <h1>Administrator created</h1>
          <p>Your RCAA administrator account is ready. Sign in to continue.</p>
          <Link className="btn primary full" href="/login">
            Go to sign in
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={submit}>
        <div className="brandmark">R</div>
        <h1>Create administrator</h1>
        <p>
          Create the first administrator for an existing merchant. The backend
          validates the merchant and bootstrap authorization.
        </p>

        {error && <div className="notice error">{error}</div>}

        <label className="field">
          Email
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
          />
        </label>

        <label className="field">
          Password
          <input
            required
            minLength={10}
            maxLength={128}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </label>

        <label className="field">
          Merchant ID
          <input
            required
            value={merchantId}
            onChange={(e) => setMerchantId(e.target.value)}
            placeholder="Existing merchant identifier"
          />
        </label>

        <label className="field">
          Bootstrap token
          <input
            required
            value={bootstrapToken}
            onChange={(e) => setBootstrapToken(e.target.value)}
            autoComplete="off"
            placeholder="Local/deployment bootstrap token"
          />
        </label>

        <button className="btn primary full" type="submit" disabled={busy}>
          {busy ? 'Creating…' : 'Create administrator'}
        </button>

        <p className="muted">
          Already have an account?{' '}
          <Link className="link" href="/login">
            Sign in
          </Link>
        </p>
      </form>
    </main>
  );
}

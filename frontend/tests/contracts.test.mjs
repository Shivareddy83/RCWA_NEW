import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

import {money,dateTime,shortId} from '../lib/format.ts';
import {
  canOperate,
  canInvestigate,
  canManageUsers,
  canRetryJobs,
} from '../lib/permissions.ts';
import {pageQuery} from '../lib/pagination.ts';
import {
  setToken,
  getToken,
  clearToken,
  api,
  baseUrl,
} from '../lib/api.ts';

const source = async (file) =>
  readFile(new URL(file, import.meta.url), 'utf8');


test(
  'registration route exists and targets backend registration',
  async () => {
    const s = await source('../app/register/page.tsx');

    assert.match(s, /\/auth\/register/);
    assert.match(s, /X-Bootstrap-Token/);
    assert.match(s, /role:\s*['"]ADMIN['"]/);
  },
);


test(
  'browser API requests use the same-origin production route',
  async () => {
    const s = await source('../lib/api.ts');
    assert.match(s, /typeof window !== 'undefined'/);
    assert.match(s, /return '\/api\/v1'/);
  },
);


test(
  'API 401 invalidates the browser session and emits an auth-expired event',
  async () => {
    const s = await source('../lib/api.ts');

    assert.match(s, /rcaa:auth-expired/);
    assert.match(s, /window\.dispatchEvent/);
  },
);


test(
  'authentication token state is in memory and clears on logout',
  () => {
    setToken('test-token');

    assert.equal(getToken(), 'test-token');

    clearToken();

    assert.equal(getToken(), null);
  },
);


test(
  'role-based action visibility blocks read-only roles',
  () => {
    assert.equal(canOperate('VIEWER'), false);
    assert.equal(canOperate('ANALYST'), false);
    assert.equal(canOperate('OPS'), true);
    assert.equal(canOperate('ADMIN'), true);
  },
);


test(
  'investigation and administration roles are separated',
  () => {
    assert.equal(canInvestigate('ANALYST'), true);
    assert.equal(canInvestigate('VIEWER'), false);
    assert.equal(canManageUsers('ADMIN'), true);
    assert.equal(canManageUsers('OPS'), false);
  },
);


test(
  'job retry visibility is limited to operational roles',
  () => {
    assert.equal(canRetryJobs('VIEWER'), false);
    assert.equal(canRetryJobs('ANALYST'), false);
    assert.equal(canRetryJobs('OPS'), true);
    assert.equal(canRetryJobs('ADMIN'), true);
  },
);


test(
  'financial formatting preserves decimal strings without binary floating point',
  () => {
    assert.equal(money('970'), '₹970.00');
    assert.equal(money('0.10'), '₹0.10');
    assert.equal(money('0.29'), '₹0.29');
  },
);


test(
  'negative financial values are formatted safely',
  () => {
    assert.equal(money('-10.5'), '-₹10.50');
    assert.equal(money('-0.29'), '-₹0.29');
  },
);


test(
  'large and Decimal-like financial values stay exact for display',
  () => {
    assert.equal(
      money('999999999999999999.99'),
      '₹999,999,999,999,999,999.99',
    );

    assert.equal(money('0010.20'), '₹10.20');
  },
);


test(
  'empty and non-financial values are safe',
  () => {
    assert.equal(money(null), '—');
    assert.equal(money(undefined), '—');
    assert.equal(money('not-a-number'), 'not-a-number');
  },
);


test(
  'date and id formatting handle missing values',
  () => {
    assert.equal(dateTime(null), '—');
    assert.equal(shortId(null), '');
    assert.equal(
      shortId('1234567890123456'),
      '12345678…3456',
    );
  },
);


test(
  'pagination creates bounded backend query parameters',
  () => {
    assert.equal(
      pageQuery(2, 50, {status: 'OPEN'}),
      'page=2&limit=50&status=OPEN',
    );

    assert.equal(
      pageQuery(0, 999, {}),
      'page=1&limit=50',
    );
  },
);


test(
  'API 401 clears the in-memory session and returns a safe error',
  async () => {
    setToken('expired-token');

    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          detail: 'secret backend detail',
        }),
        {
          status: 401,
          headers: {
            'content-type': 'application/json',
          },
        },
      );

    await assert.rejects(
      api('/x'),
      (error) =>
        error.status === 401 &&
        error.message === 'Session expired or unauthorized.',
    );

    assert.equal(getToken(), null);
  },
);


test(
  'API 403 returns a safe permission error',
  async () => {
    globalThis.fetch = async () =>
      new Response('{}', {
        status: 403,
      });

    await assert.rejects(
      api('/x'),
      (error) =>
        error.status === 403 &&
        error.message ===
          'You do not have permission for this action.',
    );
  },
);


test(
  'API 404 returns a safe not-found error',
  async () => {
    globalThis.fetch = async () =>
      new Response('{}', {
        status: 404,
      });

    await assert.rejects(
      api('/x'),
      (error) =>
        error.status === 404 &&
        error.message === 'Resource not found.',
    );
  },
);


test(
  'API 422 returns a safe validation error',
  async () => {
    globalThis.fetch = async () =>
      new Response('{}', {
        status: 422,
      });

    await assert.rejects(
      api('/x'),
      (error) =>
        error.status === 422 &&
        error.message ===
          'The request could not be validated.',
    );
  },
);


test(
  'API 429 returns a safe rate-limit error',
  async () => {
    globalThis.fetch = async () =>
      new Response('{}', {
        status: 429,
      });

    await assert.rejects(
      api('/x'),
      (error) =>
        error.status === 429 &&
        error.message ===
          'Too many requests. Please try again shortly.',
    );
  },
);


test(
  'API 500/5xx returns a generic safe error',
  async () => {
    globalThis.fetch = async () =>
      new Response('{}', {
        status: 503,
      });

    await assert.rejects(
      api('/x'),
      (error) =>
        error.status === 503 &&
        error.message ===
          'The backend is temporarily unavailable. Please try again.',
    );
  },
);


test(
  'case investigation contract contains backend AI endpoint and safety sections',
  async () => {
    const s = await source('../app/cases/[id]/page.tsx');

    for (
      const term of [
        '/ai/investigate',
        'Facts',
        'Deterministic findings',
        'Hypotheses',
        'Recommendations',
        'Uncertainty',
        'Evidence references',
      ]
    ) {
      assert.match(
        s,
        new RegExp(
          term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
        ),
      );
    }
  },
);


test(
  'deterministic RCA contract renders backend RCA fields',
  async () => {
    const s = await source('../app/cases/[id]/page.tsx');

    assert.match(s, /Deterministic RCA/);
    assert.match(
      s,
      /root_cause_code\|\|rca\.root_cause/,
    );
    assert.match(s, /recommended_action/);
  },
);


test(
  'empty and error states exist on major reusable resource flow',
  async () => {
    const s = await source('../components/resource.tsx');

    assert.match(s, /ErrorState/);
    assert.match(s, /Loading/);
    assert.match(s, /Empty/);
    assert.match(s, /items\.length===0/);
  },
);
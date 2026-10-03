// Execute the shipped github-script body with fake API responses and timers.
// workflow-lint provides Python + PyYAML; Node's test runner needs no npm deps.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const workflow = JSON.parse(execFileSync('python3', ['-c', `
import json
import pathlib
import yaml
print(json.dumps(yaml.safe_load(pathlib.Path('.github/workflows/integration-scope.yml').read_text())))
`], { cwd: root, encoding: 'utf8' }));
const job = workflow.jobs['integration-scope'];
const step = job.steps.find(item => item.name === 'Wait only for required specialized CI evidence');
const script = step.with.script;
const sha = '8f2cb43b109692b699243f462ef04afb9bbd7a77';

function run(id, conclusion = 'success', overrides = {}) {
  return {
    id,
    name: 'docker-build',
    head_sha: sha,
    status: conclusion === null ? 'in_progress' : 'completed',
    conclusion,
    started_at: '2026-10-03T01:47:14Z',
    ...overrides,
  };
}

async function poll(snapshots, { required = ['docker-build'], attempts = 2, interval = 1, errors = [] } = {}) {
  const failures = [];
  const messages = [];
  const warnings = [];
  const requests = [];
  const waits = [];
  let thrown = null;
  const listForRef = Symbol('checks.listForRef');
  const sandbox = {
    process: { env: {
      REQUIRED_JSON: JSON.stringify(required),
      CANDIDATE_SHA: sha,
      EVIDENCE_WAIT_ATTEMPTS: String(attempts),
      EVIDENCE_WAIT_INTERVAL_MS: String(interval),
    } },
    core: {
      info: message => messages.push(message),
      warning: message => warnings.push(message),
      setFailed: message => failures.push(message),
    },
    context: { repo: { owner: 'Agent-StrongHold', repo: 'Project-mAIstro' } },
    github: {
      rest: { checks: { listForRef } },
      paginate: async (endpoint, options) => {
        assert.equal(endpoint, listForRef);
        assert.equal(options.ref, sha);
        assert.equal(options.owner, 'Agent-StrongHold');
        assert.equal(options.repo, 'Project-mAIstro');
        assert.equal(options.per_page, 100);
        requests.push(options);
        if (requests.length <= errors.length) throw errors[requests.length - 1];
        return structuredClone(snapshots[Math.min(requests.length - 1 - errors.length, snapshots.length - 1)]);
      },
    },
    setTimeout: (resolve, milliseconds) => { waits.push(milliseconds); resolve(); },
  };
  try {
    await vm.runInNewContext(`(async () => {\n${script}\n})()`, sandbox);
  } catch (error) {
    thrown = error;
  }
  return { failures, messages, warnings, requests, waits, thrown };
}

// The exact fault that killed integration-scope in run 37156509599: an
// undici HeadersTimeoutError from checks.listForRef, carrying no HTTP status.
const headersTimeout = Object.assign(new Error('Headers Timeout Error'), { code: 'UND_ERR_HEADERS_TIMEOUT' });

function permutations(values) {
  if (values.length === 0) return [[]];
  return values.flatMap((value, index) =>
    permutations(values.filter((_, position) => index !== position)).map(rest => [value, ...rest]));
}

const succeeded = result => {
  assert.deepEqual(result.failures, []);
  assert.ok(result.messages.includes('all integration-scope specialized evidence succeeded'));
};

test('newest successful check wins over superseded cancelled checks in every API order', async () => {
  // The three same-SHA docker-build check IDs returned for PR #1830.
  const runs = [run(111100476011), run(111099951982, 'cancelled'), run(111099374049, 'cancelled')];
  for (const ordering of permutations(runs)) succeeded(await poll([ordering]));
});

test('newest pending check waits for its own success, never reuses older success or cancellation', async () => {
  for (const status of ['queued', 'in_progress', 'waiting']) {
    for (const oldConclusion of ['success', 'cancelled', 'failure']) {
      const pending = run(30, null, { status, started_at: null });
      const previous = run(20, oldConclusion);
      for (const ordering of permutations([pending, previous])) {
        const result = await poll([ordering, [run(30), previous]]);
        succeeded(result);
        assert.equal(result.requests.length, 2);
        assert.deepEqual(result.waits, [1]);
      }
    }
  }
});

test('latest unsuccessful completed check fails even when an older check succeeded', async () => {
  for (const conclusion of ['failure', 'cancelled', 'skipped', 'timed_out', 'action_required', 'stale', 'neutral', null]) {
    const newest = run(30, conclusion, { status: 'completed' });
    for (const ordering of permutations([newest, run(20)])) {
      const result = await poll([ordering]);
      assert.deepEqual(result.failures, [
        `docker-build is required by integration scope but concluded ${conclusion || '<none>'}`,
      ]);
      assert.equal(result.requests.length, 1);
      assert.deepEqual(result.waits, []);
    }
  }
});

test('check ID resolves equal timestamps and older delayed starts or late completions', async () => {
  const newest = run(30, 'failure', { started_at: null });
  const older = run(20, 'success', {
    started_at: '2026-10-03T02:00:00Z', completed_at: '2026-10-03T03:00:00Z',
  });
  for (const ordering of permutations([newest, older])) {
    const result = await poll([ordering]);
    assert.deepEqual(result.failures, ['docker-build is required by integration scope but concluded failure']);
  }
});

test('missing and unfinished required checks time out within the unchanged polling budget', async () => {
  for (const runs of [[], [run(30, null)], [run(30, 'success', { name: 'unrelated' })]]) {
    const result = await poll([runs], { attempts: 3, interval: 50 });
    assert.deepEqual(result.failures, ['timed out waiting for required specialized CI evidence']);
    assert.equal(result.requests.length, 3);
    assert.deepEqual(result.waits, [50, 50, 50]);
  }
});

test('all required names must succeed; unrelated checks cannot satisfy them', async () => {
  const required = ['docker-build', 'postgres (pg17)', 'postgres (pg18)'];
  const runs = required.map((name, index) => run(30 + index, 'success', { name }));
  succeeded(await poll([[...runs, run(99, 'failure', { name: 'unrelated' })]], { required }));
  const result = await poll([runs.slice(0, -1)], { required });
  assert.deepEqual(result.failures, ['timed out waiting for required specialized CI evidence']);
  assert.ok(result.messages.some(message => message.includes('still waiting for postgres (pg18)')));
});

test('empty scope returns without querying while malformed budgets still fail closed', async () => {
  const result = await poll([], { required: [] });
  assert.deepEqual(result.failures, []);
  assert.deepEqual(result.requests, []);
  for (const options of [{ attempts: 0 }, { attempts: 'invalid' }, { interval: 0 }, { interval: 'invalid' }]) {
    const invalid = await poll([], options);
    assert.deepEqual(invalid.failures, ['invalid Integration Scope polling budget']);
    assert.deepEqual(invalid.requests, []);
  }
});

test('transient API faults keep polling and still succeed when evidence later appears', async () => {
  const result = await poll([[run(30)]], { errors: [headersTimeout], attempts: 3, interval: 1 });
  succeeded(result);
  assert.equal(result.requests.length, 2);
  assert.deepEqual(result.waits, [1]);
  assert.ok(result.warnings.some(message =>
    message.includes('transient API error') && message.includes('Headers Timeout Error')));

  // A 5xx HttpError is equally transient: retried, not fatal.
  const serverError = Object.assign(new Error('Internal Server Error'), { status: 502 });
  const retried = await poll([[run(30)]], { errors: [serverError], attempts: 2, interval: 1 });
  succeeded(retried);
  assert.equal(retried.requests.length, 2);
});

test('persistent transient faults consume the same budget and still fail closed', async () => {
  const result = await poll([[]], {
    errors: [headersTimeout, headersTimeout, headersTimeout], attempts: 3, interval: 50,
  });
  assert.deepEqual(result.failures, ['timed out waiting for required specialized CI evidence']);
  assert.equal(result.requests.length, 3);
  assert.deepEqual(result.waits, [50, 50, 50]);
});

test('permanent client errors fail fast instead of burning the evidence budget', async () => {
  for (const status of [400, 401, 403, 404, 422]) {
    const notFound = Object.assign(new Error('permanent'), { status });
    const result = await poll([[run(30)]], { errors: [notFound, notFound], attempts: 3 });
    assert.ok(result.thrown, `status ${status} must be rethrown`);
    assert.equal(result.thrown.status, status);
    assert.deepEqual(result.failures, []);
    assert.equal(result.requests.length, 1);
    assert.deepEqual(result.waits, []);
  }
});

test('workflow preserves read-only permissions, exact PR/merge-group SHA, and polling budget', () => {
  assert.deepEqual(workflow.permissions, { checks: 'read', contents: 'read' });
  assert.equal(step.env.CANDIDATE_SHA, '${{ github.event.pull_request.head.sha || github.event.merge_group.head_sha }}');
  assert.equal(job['timeout-minutes'], 90);
  assert.equal(job.env.EVIDENCE_WAIT_ATTEMPTS, '170');
  assert.equal(job.env.EVIDENCE_WAIT_INTERVAL_MS, '30000');
});

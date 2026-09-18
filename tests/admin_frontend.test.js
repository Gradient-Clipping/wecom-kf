const assert = require('node:assert/strict');
const test = require('node:test');
const { jobProgressModel } = require('../src/wecom_kf/admin_assets/console.js');

test('reports trusted challenge progress as a percent', () => {
  const model = jobProgressModel({ kind: 'solve', status: 'running', progress: {
    passed_challenges: 3, total_challenges: 8, current: '第 3 关', unknown: false, has_error: false,
  }});
  assert.equal(model.known, true);
  assert.equal(model.percent, 37);
  assert.equal(model.current, '第 3 关');
  assert.equal(model.failed, false);
});

test('does not invent a percent when totals are unknown', () => {
  const model = jobProgressModel({ kind: 'solve', status: 'running', progress: {
    passed_challenges: 3, total_challenges: null, unknown: true, has_error: null,
  }});
  assert.equal(model.known, false);
  assert.equal(model.percent, null);
  assert.match(model.summary, /未知/);
});

test('exposes errors without treating ended as successful', () => {
  const model = jobProgressModel({ kind: 'solve', status: 'ended', progress: {
    passed_challenges: 8, total_challenges: 8, has_error: true, failures: ['超时'],
  }});
  assert.equal(model.percent, 100);
  assert.equal(model.failed, true);
  assert.equal(model.error, '执行出错');
});

test('account validation has no fake homework progress', () => {
  const model = jobProgressModel({ kind: 'verify', status: 'ended', progress: null });
  assert.equal(model.known, false);
  assert.equal(model.percent, null);
  assert.match(model.summary, /无做题进度/);
});

test('uses Shuori task units when challenge totals are unavailable', () => {
  const model = jobProgressModel({ kind: 'solve', status: 'running', progress: {
    passed_units: 1, total_units: 3, current: '任务：数据库作业', unknown: false, has_error: false,
  }});
  assert.equal(model.known, true);
  assert.equal(model.percent, 33);
  assert.equal(model.summary, '单元已通过 1 / 3');
});

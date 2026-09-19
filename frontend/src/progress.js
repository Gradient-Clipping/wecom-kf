// Pure view model: no inferred success, synthetic percent, or HTML from the API.
export function jobProgressModel(job = {}) {
  const p = job.progress || {}, solve = job.kind === 'solve';
  const count = v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && Number.isInteger(v);
  const pairs = [['关卡', p.passed_challenges, p.total_challenges], ['作业', p.passed_homeworks, p.total_homeworks], ['单元', p.passed_units, p.total_units]];
  const pair = p.unknown === true ? null : pairs.find(([, done, total]) => count(done) && count(total) && total > 0 && done <= total);
  const failures = Array.isArray(p.failures) ? p.failures.filter(v => typeof v === 'string' && v.trim()) : null;
  const reportedUnknown = p.unknown === true || p.unknown === false ? p.unknown : (pair ? false : null);
  const failed = job.status === 'failed' || p.has_error === true || !!failures?.length;
  return {
    solve, known: solve && !!pair, done: pair?.[1], total: pair?.[2],
    percent: pair ? Math.floor(pair[1] / pair[2] * 100) : null,
    summary: !solve ? '账号验证 · 无做题进度' : pair ? `${pair[0]}已通过 ${pair[1]} / ${pair[2]}` : '进度未知 · 等待上报',
    current: typeof p.current === 'string' && p.current.trim() ? p.current : (job.status === 'queued' ? '排队等待执行' : '当前步骤未上报'),
    unknown: reportedUnknown, failed, error: job.status === 'failed' ? '任务出错' : p.has_error === true ? '执行出错' : failures?.length ? `存在 ${failures.length} 条失败记录` : p.has_error === false ? '暂无错误记录' : '错误状态未上报',
    failures: failures || []
  };
}

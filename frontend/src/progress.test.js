import { describe, expect, it } from 'vitest'
import { jobProgressModel } from './progress.js'

describe('jobProgressModel', () => {
  it('renders only progress reported by the backend', () => {
    const model = jobProgressModel({
      kind: 'solve',
      status: 'running',
      progress: { passed_challenges: 3, total_challenges: 5, current: '提交第 4 题' },
    })

    expect(model.known).toBe(true)
    expect(model.percent).toBe(60)
    expect(model.summary).toBe('关卡已通过 3 / 5')
    expect(model.current).toBe('提交第 4 题')
  })

  it('does not invent a percentage when the backend has no progress', () => {
    const model = jobProgressModel({ kind: 'solve', status: 'running', progress: {} })

    expect(model.known).toBe(false)
    expect(model.percent).toBeNull()
    expect(model.unknown).toBeNull()
  })

  it('keeps failure details available to the operator', () => {
    const model = jobProgressModel({
      kind: 'solve',
      status: 'failed',
      progress: { failures: ['验证码失败', '上游超时'] },
    })

    expect(model.failed).toBe(true)
    expect(model.error).toBe('任务出错')
    expect(model.failures).toEqual(['验证码失败', '上游超时'])
  })
})

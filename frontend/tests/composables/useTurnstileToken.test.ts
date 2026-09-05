import { describe, it, expect, beforeEach } from 'vitest'
import { useTurnstileToken } from '../../app/composables/useTurnstileToken'

describe('useTurnstileToken', () => {
  beforeEach(() => {
    const { clearToken } = useTurnstileToken()
    clearToken()
  })

  it('initializes with undefined token and isReady false', () => {
    const { token, isReady } = useTurnstileToken()
    expect(token.value).toBeUndefined()
    expect(isReady.value).toBe(false)
  })

  it('updates token and isReady when setToken is called', () => {
    const { token, isReady, setToken } = useTurnstileToken()
    setToken('cf-sample-token-123')
    expect(token.value).toBe('cf-sample-token-123')
    expect(isReady.value).toBe(true)
  })

  it('clears token when clearToken is called', () => {
    const { token, isReady, setToken, clearToken } = useTurnstileToken()
    setToken('cf-sample-token-123')
    expect(isReady.value).toBe(true)

    clearToken()
    expect(token.value).toBeUndefined()
    expect(isReady.value).toBe(false)
  })

  it('exposes isEnabled boolean computed property reflecting configuration', () => {
    const { isEnabled } = useTurnstileToken()
    expect(typeof isEnabled.value).toBe('boolean')
  })
})

import { describe, expect, it } from 'vitest'
import { DEFAULT_ERROR_MESSAGE, getErrorMessage, isServerError } from '~/utils/error'

describe('utils/error', () => {
  describe('isServerError', () => {
    it('returns true for 5xx statusCode, status, or response.status', () => {
      expect(isServerError({ statusCode: 500 })).toBe(true)
      expect(isServerError({ status: 502 })).toBe(true)
      expect(isServerError({ response: { status: 503 } })).toBe(true)
      expect(isServerError({ statusCode: 504 })).toBe(true)
    })

    it('returns false for 4xx, missing status, and non-objects', () => {
      expect(isServerError({ statusCode: 400 })).toBe(false)
      expect(isServerError({ status: 409 })).toBe(false)
      expect(isServerError({ response: { status: 401 } })).toBe(false)
      expect(isServerError(new Error('network down'))).toBe(false)
      expect(isServerError(null)).toBe(false)
      expect(isServerError('boom')).toBe(false)
    })
  })

  describe('getErrorMessage', () => {
    it('returns fallback for ofetch 500 FetchError instead of raw HTTP string', () => {
      const fetchErr = Object.assign(
        new Error('[POST] "https://api.negolah.my/payment/checkout": 500 Internal Server Error'),
        {
          statusCode: 500,
          status: 500,
          data: { detail: 'Checkout failed. Please try again.' }
        }
      )

      expect(getErrorMessage(fetchErr, 'Unable to start transaction')).toBe('Unable to start transaction')
      expect(getErrorMessage(fetchErr)).toBe(DEFAULT_ERROR_MESSAGE)
    })

    it('returns fallback for 502/503/504 errors via status or response.status even with detail', () => {
      expect(getErrorMessage({ status: 502, data: { detail: 'Bad Gateway' } })).toBe(DEFAULT_ERROR_MESSAGE)
      expect(getErrorMessage({ response: { status: 503 }, data: { detail: 'Service Unavailable' } })).toBe(
        DEFAULT_ERROR_MESSAGE
      )
      expect(getErrorMessage({ statusCode: 504 })).toBe(DEFAULT_ERROR_MESSAGE)
    })

    it('returns trimmed data.detail for 4xx client errors', () => {
      const err401 = Object.assign(
        new Error('[POST] "https://api.negolah.my/auth/login": 401 Unauthorized'),
        { statusCode: 401, data: { detail: '  Invalid email or password  ' } }
      )
      expect(getErrorMessage(err401)).toBe('Invalid email or password')

      expect(getErrorMessage({ statusCode: 400, data: { detail: 'Order not found' } })).toBe('Order not found')
      expect(getErrorMessage({ statusCode: 409, data: { detail: 'Item is no longer available' } })).toBe(
        'Item is no longer available'
      )
      expect(getErrorMessage({ data: { detail: 'Price below minimum' } })).toBe('Price below minimum')
    })

    it('returns fallback when data.detail is not a non-empty string (e.g. FastAPI 422 array)', () => {
      expect(getErrorMessage({ statusCode: 422, data: { detail: [{ msg: 'field required' }] } })).toBe(
        DEFAULT_ERROR_MESSAGE
      )
      expect(getErrorMessage({ statusCode: 400, data: { detail: '   ' } })).toBe(DEFAULT_ERROR_MESSAGE)
      expect(getErrorMessage({ statusCode: 404, data: {} })).toBe(DEFAULT_ERROR_MESSAGE)
    })

    it('returns fallback for unhandled JS errors, network failures, and primitives', () => {
      expect(getErrorMessage(new Error('[POST] "https://api.negolah.my/x": <no response> Failed to fetch'))).toBe(
        DEFAULT_ERROR_MESSAGE
      )
      expect(getErrorMessage(new TypeError('Cannot read properties of undefined'))).toBe(DEFAULT_ERROR_MESSAGE)
      expect(getErrorMessage({ message: 'raw message' }, 'Custom fallback')).toBe('Custom fallback')
      expect(getErrorMessage('plain string', 'Custom fallback')).toBe('Custom fallback')
      expect(getErrorMessage(null)).toBe(DEFAULT_ERROR_MESSAGE)
      expect(getErrorMessage(undefined)).toBe(DEFAULT_ERROR_MESSAGE)
    })
  })
})

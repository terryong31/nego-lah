import { describe, expect, it, beforeEach } from 'vitest'
import { setupZodI18n } from '~/plugins/zod-i18n'
import {
  loginSchema,
  registerSchema,
  shippingAddressSchema,
  adminItemSchema
} from '~/utils/schemas'

describe('Zod Human-Readable i18n Validation', () => {
  beforeEach(() => {
    setupZodI18n('en')
  })

  it('formats invalid email error in human readable English', () => {
    setupZodI18n('en')
    const result = loginSchema.safeParse({ email: 'not-an-email', password: 'password123' })
    expect(result.success).toBe(false)
    if (!result.success) {
      const msg = result.error.issues[0]?.message
      expect(msg).toContain('valid email')
      expect(msg).not.toContain('invalid_format')
    }
  })

  it('formats invalid email error in human readable Bahasa Melayu', () => {
    setupZodI18n('ms')
    const result = loginSchema.safeParse({ email: 'bad-email', password: 'password123' })
    expect(result.success).toBe(false)
    if (!result.success) {
      const msg = result.error.issues[0]?.message
      expect(msg).toContain('alamat emel yang sah')
    }
  })

  it('formats invalid email error in human readable Simplified Chinese', () => {
    setupZodI18n('zh')
    const result = loginSchema.safeParse({ email: 'bad-email', password: 'password123' })
    expect(result.success).toBe(false)
    if (!result.success) {
      const msg = result.error.issues[0]?.message
      expect(msg).toContain('电子邮箱地址')
    }
  })

  it('formats string too small error with human readable character count', () => {
    setupZodI18n('en')
    const result = loginSchema.safeParse({ email: 'test@example.com', password: '123' })
    expect(result.success).toBe(false)
    if (!result.success) {
      const msg = result.error.issues[0]?.message
      expect(msg).toContain('at least 8 characters')
    }

    setupZodI18n('ms')
    const resultMs = loginSchema.safeParse({ email: 'test@example.com', password: '123' })
    if (!resultMs.success) {
      expect(resultMs.error.issues[0]?.message).toContain('sekurang-kurangnya 8 aksara')
    }

    setupZodI18n('zh')
    const resultZh = loginSchema.safeParse({ email: 'test@example.com', password: '123' })
    if (!resultZh.success) {
      expect(resultZh.error.issues[0]?.message).toContain('至少需要 8 个字符')
    }
  })

  it('formats required field error in friendly human readable words', () => {
    setupZodI18n('en')
    const result = loginSchema.safeParse({ email: '', password: '' })
    expect(result.success).toBe(false)
    if (!result.success) {
      const messages = result.error.issues.map(i => i.message)
      expect(messages.some(m => m.includes('required') || m.includes('at least'))).toBe(true)
    }
  })

  it('validates register passwords match with localized refinement error', () => {
    setupZodI18n('en')
    const result = registerSchema.safeParse({
      email: 'test@example.com',
      password: 'password123',
      confirmPassword: 'password456'
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.error.issues[0]?.message).toContain('Passwords don\'t match')
    }

    setupZodI18n('ms')
    const resultMs = registerSchema.safeParse({
      email: 'test@example.com',
      password: 'password123',
      confirmPassword: 'password456'
    })
    if (!resultMs.success) {
      expect(resultMs.error.issues[0]?.message).toContain('tidak sepadan')
    }

    setupZodI18n('zh')
    const resultZh = registerSchema.safeParse({
      email: 'test@example.com',
      password: 'password123',
      confirmPassword: 'password456'
    })
    if (!resultZh.success) {
      expect(resultZh.error.issues[0]?.message).toContain('两次输入的密码不一致')
    }
  })

  it('validates shipping Malaysian phone number and address constraints', () => {
    setupZodI18n('en')
    const invalidPhone = shippingAddressSchema.safeParse({
      recipient_name: 'Terry',
      phone: '12345',
      address: 'Too short'
    })
    expect(invalidPhone.success).toBe(false)
    if (!invalidPhone.success) {
      expect(invalidPhone.error.issues.some(i => i.message.includes('Malaysian phone number'))).toBe(true)
    }

    const validShipping = shippingAddressSchema.safeParse({
      recipient_name: 'Terry Ong',
      phone: '0123456789',
      address: '123 Jalan Ampang, Kuala Lumpur, 50450 Malaysia'
    })
    expect(validShipping.success).toBe(true)
  })

  it('validates admin item creation schema price constraints', () => {
    setupZodI18n('en')
    const invalidPrice = adminItemSchema.safeParse({
      name: 'Item Title',
      description: 'A detailed item description with plenty of characters.',
      condition: 'Good',
      price: -10
    })
    expect(invalidPrice.success).toBe(false)
  })
})

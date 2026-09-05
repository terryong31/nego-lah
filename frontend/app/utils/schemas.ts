import { z } from 'zod'

// ----------------------------------------------------
// 1. Auth Schemas
// ----------------------------------------------------
export const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8)
})

export type LoginForm = z.infer<typeof loginSchema>

export const registerSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  confirmPassword: z.string().min(8)
}).refine(data => data.password === data.confirmPassword, {
  params: { code: 'passwordsMismatch' },
  path: ['confirmPassword']
})

export type RegisterForm = z.infer<typeof registerSchema>

export const forgotPasswordSchema = z.object({
  email: z.string().email()
})

export type ForgotPasswordForm = z.infer<typeof forgotPasswordSchema>

export const resetPasswordSchema = z.object({
  password: z.string().min(8),
  confirmPassword: z.string().min(8)
}).refine(data => data.password === data.confirmPassword, {
  params: { code: 'passwordsMismatch' },
  path: ['confirmPassword']
})

export type ResetPasswordForm = z.infer<typeof resetPasswordSchema>

// ----------------------------------------------------
// 2. Profile Schemas
// ----------------------------------------------------
export const profileDetailsSchema = z.object({
  displayName: z.string().min(2).max(50).optional().or(z.literal(''))
})

export type ProfileDetailsForm = z.infer<typeof profileDetailsSchema>

export const emailChangeSchema = z.object({
  email: z.string().email()
})

export type EmailChangeForm = z.infer<typeof emailChangeSchema>

export const passwordChangeSchema = z.object({
  currentPassword: z.string().min(8),
  newPassword: z.string().min(8),
  confirmPassword: z.string().min(8)
}).refine(data => data.newPassword === data.confirmPassword, {
  params: { code: 'passwordsMismatch' },
  path: ['confirmPassword']
})

export type PasswordChangeForm = z.infer<typeof passwordChangeSchema>

// ----------------------------------------------------
// 3. Admin Schemas
// ----------------------------------------------------
export const adminLoginSchema = z.object({
  identifier: z.string().min(3),
  password: z.string().min(8),
  otp: z.string().optional()
})

export type AdminLoginForm = z.infer<typeof adminLoginSchema>

export const adminItemSchema = z.object({
  name: z.string().min(1, { message: 'required' }).max(100),
  description: z.string().max(2000).optional().or(z.literal('')),
  condition: z.string().optional().or(z.literal('')),
  price: z.number().positive(),
  min_price: z.number().positive().optional(),
  translations: z.record(z.string(), z.any()).optional()
}).refine(data => !data.min_price || data.min_price <= data.price, {
  params: { code: 'minPriceMax' },
  path: ['min_price']
})

export type AdminItemForm = z.infer<typeof adminItemSchema>

export const adminUserBanSchema = z.object({
  reason: z.string().min(3).max(500)
})

export type AdminUserBanForm = z.infer<typeof adminUserBanSchema>

// ----------------------------------------------------
// 4. Shipping & Checkout Schemas
// ----------------------------------------------------
export const shippingAddressSchema = z.object({
  recipient_name: z.string().min(2).max(100),
  phone: z.string().refine(val => /^(\+?6?01)[0-46-9]-*[0-9]{7,8}$/.test(val), {
    params: { code: 'phoneInvalid' }
  }),
  address: z.string().min(10).max(300),
  notes: z.string().max(500).optional()
})

export type ShippingAddressForm = z.infer<typeof shippingAddressSchema>

// ----------------------------------------------------
// 5. Chat Input Schema
// ----------------------------------------------------
export const chatInputSchema = z.object({
  message: z.string().min(1).max(2000)
})

export type ChatInputForm = z.infer<typeof chatInputSchema>

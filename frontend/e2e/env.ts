export const API = (process.env.E2E_API_URL || 'http://localhost:8000').replace(/\/$/, '')
export const EMAIL = process.env.E2E_EMAIL
export const PASSWORD = process.env.E2E_PASSWORD

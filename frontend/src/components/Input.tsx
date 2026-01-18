import type { InputHTMLAttributes } from 'react'
import { forwardRef, useState } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
    label?: string
    error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
    ({ label, error, className = '', type = 'text', ...props }, ref) => {
        const [showPassword, setShowPassword] = useState(false)
        const isPassword = type === 'password'
        const inputType = isPassword ? (showPassword ? 'text' : 'password') : type

        return (
            <div className="w-full">
                {label && (
                    <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">
                        {label}
                    </label>
                )}
                <div className="relative">
                    <input
                        ref={ref}
                        type={inputType}
                        className={`
                            w-full px-4 py-2.5 
                            bg-[var(--bg-tertiary)] border border-[var(--border)] 
                            rounded-lg text-[var(--text-primary)] 
                            placeholder:text-[var(--text-muted)]
                            focus:outline-none focus:border-[var(--input-focus-border)] focus:ring-1 focus:ring-[var(--input-focus-border)]
                            disabled:opacity-50 disabled:cursor-not-allowed
                            ${error ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : ''}
                            ${className}
                        `}
                        {...props}
                    />
                    {isPassword && (
                        <button
                            type="button"
                            onClick={() => setShowPassword(!showPassword)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                        >
                            {showPassword ? (
                                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                                    <line x1="1" y1="1" x2="23" y2="23" />
                                </svg>
                            ) : (
                                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                                    <circle cx="12" cy="12" r="3" />
                                </svg>
                            )}
                        </button>
                    )}
                </div>
                {error && (
                    <p className="mt-1.5 text-sm text-red-500">{error}</p>
                )}
            </div>
        )
    }
)

Input.displayName = 'Input'

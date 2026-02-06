import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { Card } from '../components/Card'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'

export function ResetPassword() {
    const [password, setPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [success, setSuccess] = useState(false)
    const navigate = useNavigate()
    const { session, isPasswordRecovery } = useAuth()

    useEffect(() => {
        // Check for errors in URL hash (e.g., expired token)
        const hash = window.location.hash
        if (hash.includes('error=')) {
            const params = new URLSearchParams(hash.substring(1))
            const errorDesc = params.get('error_description')
            if (errorDesc) {
                setError(decodeURIComponent(errorDesc.replace(/\+/g, ' ')))
            } else {
                setError('The reset link is invalid or has expired. Please request a new one.')
            }
            setIsLoading(false)
            return
        }

        // Check if we have a valid session for password reset
        const checkSession = async () => {
            // Wait a moment for auth to process
            await new Promise(resolve => setTimeout(resolve, 500))

            const { data: { session: currentSession } } = await supabase.auth.getSession()

            if (currentSession || isPasswordRecovery) {
                setError(null)
            } else {
                setError('Invalid or expired reset link. Please request a new password reset.')
            }
            setIsLoading(false)
        }

        checkSession()
    }, [session, isPasswordRecovery])

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError(null)

        // Validate passwords match
        if (password !== confirmPassword) {
            setError('Passwords do not match')
            return
        }

        // Validate password length
        if (password.length < 6) {
            setError('Password must be at least 6 characters')
            return
        }

        setIsLoading(true)

        try {
            const { error } = await supabase.auth.updateUser({
                password: password
            })

            if (error) {
                setError(error.message)
            } else {
                setSuccess(true)
                // Redirect to home after 2 seconds
                setTimeout(() => navigate('/'), 2000)
            }
        } catch {
            setError('An unexpected error occurred')
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex items-center justify-center p-4">
            {/* Stars Background */}
            <div className="stars-container">
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="stars"></div>
            </div>

            <div className="relative z-10 w-full max-w-sm animate-slide-up flex flex-col items-start">
                {/* Back arrow with text */}
                <button
                    onClick={() => navigate('/')}
                    className="flex items-center gap-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group mb-4"
                    aria-label="Back to home"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M19 12H5M12 19l-7-7 7-7" />
                    </svg>
                    <span className="text-sm font-medium relative">
                        Back to Home
                        <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover:w-full" />
                    </span>
                </button>

                <Card className="w-full backdrop-blur-sm shadow-xl">
                    <div className="mb-6 animate-fade-in">
                        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
                            Reset Password
                        </h1>
                        <p className="text-sm text-[var(--text-secondary)] mt-1">
                            Enter your new password below
                        </p>
                    </div>

                    {error && (
                        <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
                            {error}
                        </div>
                    )}

                    {success ? (
                        <div className="p-4 bg-green-900/20 border border-green-800 rounded-lg text-green-400 text-center">
                            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-3">
                                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                                <polyline points="22 4 12 14.01 9 11.01" />
                            </svg>
                            <p className="font-medium">Password updated successfully!</p>
                            <p className="text-sm mt-1 text-[var(--text-muted)]">Redirecting to home...</p>
                        </div>
                    ) : (
                        <form onSubmit={handleSubmit} className="space-y-4">
                            <div>
                                <Input
                                    type="password"
                                    label="New Password"
                                    placeholder="Enter new password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    disabled={isLoading}
                                />
                            </div>

                            <div>
                                <Input
                                    type="password"
                                    label="Confirm Password"
                                    placeholder="Confirm new password"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    required
                                    disabled={isLoading}
                                />
                            </div>

                            <div className="pt-2">
                                <Button type="submit" variant="filled" fullWidth disabled={isLoading}>
                                    {isLoading ? 'Updating...' : 'Update Password'}
                                </Button>
                            </div>
                        </form>
                    )}

                    <p className="text-sm text-zinc-500 text-center mt-6">
                        Remember your password?{' '}
                        <button
                            type="button"
                            onClick={() => navigate('/login')}
                            className="text-blue-400 hover:text-blue-300 underline"
                        >
                            Login
                        </button>
                    </p>
                </Card>
            </div>
        </div>
    )
}
    
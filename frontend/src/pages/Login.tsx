import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { Card } from '../components/Card'
import { useAuth } from '../context/AuthContext'
import { signInWithEmail, signUpWithEmail, resetPassword } from '../lib/supabase'

interface LoginProps {
    onBack: () => void
}

export function Login({ onBack }: LoginProps) {
    const { signInWithGoogle, user, loading } = useAuth()
    const [isLoginMode, setIsLoginMode] = useState(true)
    const [email, setEmail] = useState('')
    const [password, setPassword] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [success, setSuccess] = useState<string | null>(null)
    const navigate = useNavigate()

    // Redirect if already logged in - use useEffect to avoid setState during render
    useEffect(() => {
        if (user && !loading) {
            navigate('/')
        }
    }, [user, loading, navigate])

    const handleEmailSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setIsLoading(true)
        setError(null)
        setSuccess(null)

        try {
            if (isLoginMode) {
                const { data, error } = await signInWithEmail(email, password)
                if (error) {
                    // Check if email not confirmed
                    if (error.message.includes('Email not confirmed')) {
                        setError('Please confirm your email before logging in. Check your inbox for the confirmation link.')
                    } else {
                        setError(error.message)
                    }
                } else if (data?.user && !data.user.email_confirmed_at) {
                    // User exists but email not confirmed
                    setError('Please confirm your email before logging in. Check your inbox for the confirmation link.')
                }
            } else {
                const { error } = await signUpWithEmail(email, password)
                if (error) {
                    setError(error.message)
                } else {
                    setSuccess('Account created! Check your email to confirm before logging in.')
                    setIsLoginMode(true)
                    setPassword('')
                }
            }
        } catch {
            setError('An unexpected error occurred')
        } finally {
            setIsLoading(false)
        }
    }

    const handleGoogleLogin = async () => {
        setIsLoading(true)
        setError(null)
        try {
            await signInWithGoogle()
        } catch {
            setError('Failed to sign in with Google')
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
                    onClick={onBack}
                    className="flex items-center gap-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group mb-4"
                    aria-label="Back to store"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M19 12H5M12 19l-7-7 7-7" />
                    </svg>
                    <span className="text-sm font-medium relative">
                        Return to menu
                        <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover:w-full" />
                    </span>
                </button>

                <Card className="w-full backdrop-blur-sm shadow-xl">
                    <div className="mb-6 animate-fade-in">
                        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
                            {isLoginMode ? 'Login' : 'Create Account'}
                        </h1>
                        <p className="text-sm text-[var(--text-secondary)] mt-1">
                            {isLoginMode
                                ? 'Enter your credentials to continue'
                                : 'Fill in your details to register'}
                        </p>
                    </div>

                    {error && (
                        <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
                            {error}
                        </div>
                    )}

                    {success && (
                        <div className="mb-4 p-3 bg-green-900/20 border border-green-800 rounded-lg text-green-400 text-sm">
                            {success}
                        </div>
                    )}

                    <form onSubmit={handleEmailSubmit} className="space-y-4">
                        <div>
                            <Input
                                type="email"
                                label="Email"
                                placeholder="you@example.com"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                disabled={isLoading}
                            />
                        </div>

                        <div>
                            <Input
                                type="password"
                                label="Password"
                                placeholder="Your password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                disabled={isLoading}
                            />
                            {isLoginMode && (
                                <button
                                    type="button"
                                    onClick={async () => {
                                        if (!email) {
                                            setError('Please enter your email address first')
                                            return
                                        }
                                        setIsLoading(true)
                                        setError(null)
                                        const { error } = await resetPassword(email)
                                        setIsLoading(false)
                                        if (error) {
                                            setError(error.message)
                                        } else {
                                            setSuccess('Password reset email sent! Check your inbox.')
                                        }
                                    }}
                                    className="text-xs text-[var(--text-muted)] hover:text-[var(--accent)] mt-2 relative group"
                                    disabled={isLoading}
                                >
                                    Forgot password?
                                    <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--accent)] transition-all duration-300 group-hover:w-full" />
                                </button>
                            )}
                        </div>

                        <div className="pt-2">
                            <Button type="submit" variant="filled" fullWidth disabled={isLoading}>
                                {isLoading ? 'Please wait...' : (isLoginMode ? 'Login' : 'Create Account')}
                            </Button>
                        </div>
                    </form>

                    {/* Divider */}
                    <div className="flex items-center gap-4 my-6">
                        <div className="flex-1 h-px bg-[var(--border)]"></div>
                        <span className="text-xs text-[var(--text-muted)]">OR</span>
                        <div className="flex-1 h-px bg-[var(--border)]"></div>
                    </div>

                    {/* Google Login */}
                    <Button
                        variant="filled"
                        onClick={handleGoogleLogin}
                        fullWidth
                        disabled={isLoading}
                        className="flex items-center justify-center gap-3"
                    >
                        <svg width="18" height="18" viewBox="0 0 24 24">
                            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                        </svg>
                        Continue with Google
                    </Button>

                    {/* Toggle mode */}
                    <p className="text-sm text-zinc-500 text-center mt-6">
                        {isLoginMode ? "Don't have an account? " : "Already have an account? "}
                        <button
                            type="button"
                            onClick={() => {
                                setIsLoginMode(!isLoginMode)
                                setError(null)
                                setSuccess(null)
                            }}
                            className="text-blue-400 hover:text-blue-300 underline"
                        >
                            {isLoginMode ? 'Register' : 'Login'}
                        </button>
                    </p>
                </Card>
            </div>
        </div>
    )
}

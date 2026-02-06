import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { User, Session } from '@supabase/supabase-js'
import { supabase, signInWithGoogle, signOut } from '../lib/supabase'

const API_URL = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '/api' : 'http://127.0.0.1:8000')

interface AuthContextType {
    user: User | null
    session: Session | null
    loading: boolean
    isPasswordRecovery: boolean
    isBanned: boolean
    banError: string | null
    signInWithGoogle: () => Promise<void>
    signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    const [session, setSession] = useState<Session | null>(null)
    const [loading, setLoading] = useState(true)
    const [isPasswordRecovery, setIsPasswordRecovery] = useState(false)
    const [isBanned, setIsBanned] = useState(false)
    const [banError, setBanError] = useState<string | null>(null)

    // Check if user is banned
    const checkBanStatus = async (userId: string): Promise<boolean> => {
        try {
            const response = await fetch(`${API_URL}/user/${userId}/ban-status`)
            if (response.ok) {
                const data = await response.json()
                return data.is_banned === true
            }
        } catch (error) {
            console.error('Failed to check ban status:', error)
        }
        return false
    }

    useEffect(() => {
        // Get initial session
        supabase.auth.getSession().then(async ({ data: { session } }) => {
            if (session?.user) {
                // Check ban status for existing session
                const banned = await checkBanStatus(session.user.id)
                if (banned) {
                    setIsBanned(true)
                    setBanError('Your account has been banned. Please contact support.')
                    await signOut()
                    setSession(null)
                    setUser(null)
                    setLoading(false)
                    return
                }
            }
            setSession(session)
            setUser(session?.user ?? null)
            setLoading(false)
        })

        // Listen for auth changes
        const { data: { subscription } } = supabase.auth.onAuthStateChange(
            async (event, session) => {
                console.log('Auth event:', event)

                // Handle password recovery specially
                if (event === 'PASSWORD_RECOVERY') {
                    setIsPasswordRecovery(true)
                    setSession(session)
                    setUser(session?.user ?? null)
                    setLoading(false)

                    // Redirect to reset-password page if not already there
                    if (window.location.pathname !== '/reset-password') {
                        window.location.href = '/reset-password'
                    }
                    return
                }

                // Check ban status on sign in
                if (event === 'SIGNED_IN' && session?.user) {
                    const banned = await checkBanStatus(session.user.id)
                    if (banned) {
                        setIsBanned(true)
                        setBanError('Your account has been banned. Please contact support.')
                        await signOut()
                        setSession(null)
                        setUser(null)
                        setLoading(false)
                        return
                    }
                }

                // For other events, handle normally
                setSession(session)
                setUser(session?.user ?? null)
                setLoading(false)
                setIsBanned(false)
                setBanError(null)

                // Clear password recovery flag on sign out
                if (event === 'SIGNED_OUT') {
                    setIsPasswordRecovery(false)
                }
            }
        )

        return () => subscription.unsubscribe()
    }, [])

    const handleSignInWithGoogle = async () => {
        await signInWithGoogle()
    }

    const handleSignOut = async () => {
        await signOut()
        setUser(null)
        setSession(null)
        setIsPasswordRecovery(false)
        setIsBanned(false)
        setBanError(null)
    }

    return (
        <AuthContext.Provider value={{
            user,
            session,
            loading,
            isPasswordRecovery,
            isBanned,
            banError,
            signInWithGoogle: handleSignInWithGoogle,
            signOut: handleSignOut
        }}>
            {children}
        </AuthContext.Provider>
    )
}

export function useAuth() {
    const context = useContext(AuthContext)
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider')
    }
    return context
}

import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { User, Session } from '@supabase/supabase-js'
import { supabase, signInWithGoogle, signOut } from '../lib/supabase'

interface AuthContextType {
    user: User | null
    session: Session | null
    loading: boolean
    isPasswordRecovery: boolean
    signInWithGoogle: () => Promise<void>
    signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    const [session, setSession] = useState<Session | null>(null)
    const [loading, setLoading] = useState(true)
    const [isPasswordRecovery, setIsPasswordRecovery] = useState(false)

    useEffect(() => {
        // Get initial session
        supabase.auth.getSession().then(({ data: { session } }) => {
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

                // For other events, handle normally
                setSession(session)
                setUser(session?.user ?? null)
                setLoading(false)

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
    }

    return (
        <AuthContext.Provider value={{
            user,
            session,
            loading,
            isPasswordRecovery,
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

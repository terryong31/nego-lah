import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase environment variables')
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

// Auth helpers
export async function signInWithGoogle() {
    const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
            redirectTo: `${window.location.origin}/`
        }
    })
    return { data, error }
}

export async function signInWithEmail(email: string, password: string) {
    const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password
    })
    return { data, error }
}

export async function signUpWithEmail(email: string, password: string) {
    const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: {
            emailRedirectTo: `${window.location.origin}/`
        }
    })
    return { data, error }
}

export async function signOut() {
    const { error } = await supabase.auth.signOut()
    return { error }
}

export async function getCurrentUser() {
    const { data: { user } } = await supabase.auth.getUser()
    return user
}

export async function getSession() {
    const { data: { session } } = await supabase.auth.getSession()
    return session
}

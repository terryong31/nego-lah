import { useState, useCallback } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

interface AuthState {
    token: string | null
    isAuthenticated: boolean
    isLoading: boolean
    error: string | null
}

export function useAuth() {
    const [state, setState] = useState<AuthState>({
        token: localStorage.getItem('token'),
        isAuthenticated: !!localStorage.getItem('token'),
        isLoading: false,
        error: null
    })

    const login = useCallback(async (email: string, password: string) => {
        setState(prev => ({ ...prev, isLoading: true, error: null }))

        try {
            const res = await fetch(`${API_URL}/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: email, password })
            })

            const data = await res.json()

            if (res.ok) {
                localStorage.setItem('token', data.access_token)
                setState({
                    token: data.access_token,
                    isAuthenticated: true,
                    isLoading: false,
                    error: null
                })
                return true
            } else {
                setState(prev => ({
                    ...prev,
                    isLoading: false,
                    error: data.detail || 'Login failed'
                }))
                return false
            }
        } catch {
            setState(prev => ({
                ...prev,
                isLoading: false,
                error: 'Connection error'
            }))
            return false
        }
    }, [])

    const register = useCallback(async (email: string, password: string) => {
        setState(prev => ({ ...prev, isLoading: true, error: null }))

        try {
            const res = await fetch(`${API_URL}/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: email, password })
            })

            const data = await res.json()

            if (res.ok) {
                setState(prev => ({ ...prev, isLoading: false, error: null }))
                return true
            } else {
                setState(prev => ({
                    ...prev,
                    isLoading: false,
                    error: data.detail || 'Registration failed'
                }))
                return false
            }
        } catch {
            setState(prev => ({
                ...prev,
                isLoading: false,
                error: 'Connection error'
            }))
            return false
        }
    }, [])

    const logout = useCallback(() => {
        localStorage.removeItem('token')
        setState({
            token: null,
            isAuthenticated: false,
            isLoading: false,
            error: null
        })
    }, [])

    const clearError = useCallback(() => {
        setState(prev => ({ ...prev, error: null }))
    }, [])

    return {
        ...state,
        login,
        register,
        logout,
        clearError
    }
}

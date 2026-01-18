import { useState, useEffect } from 'react'

type Theme = 'dark' | 'light'

export function useTheme() {
    const [theme, setTheme] = useState<Theme>(() => {
        if (typeof window !== 'undefined') {
            const saved = localStorage.getItem('theme') as Theme
            return saved || 'dark'
        }
        return 'dark'
    })

    useEffect(() => {
        const root = document.documentElement
        if (theme === 'light') {
            root.classList.add('light')
            root.classList.remove('dark')
        } else {
            root.classList.add('dark')
            root.classList.remove('light')
        }
        localStorage.setItem('theme', theme)
    }, [theme])

    const toggleTheme = () => {
        setTheme(prev => prev === 'dark' ? 'light' : 'dark')
    }

    return { theme, toggleTheme, setTheme }
}

interface ThemeToggleProps {
    className?: string
}

export function ThemeToggle({ className = '' }: ThemeToggleProps) {
    const { theme, setTheme } = useTheme()

    const handleToggle = async () => {
        const newTheme = theme === 'dark' ? 'light' : 'dark'

        // Check if View Transitions API is supported
        if (!document.startViewTransition) {
            // Fallback: just change theme instantly
            setTheme(newTheme)
            return
        }

        // Use View Transitions API for smooth wipe effect
        document.documentElement.classList.add('theme-transition')
        const transition = document.startViewTransition(() => {
            setTheme(newTheme)
        })

        try {
            await transition.finished
        } finally {
            document.documentElement.classList.remove('theme-transition')
        }
    }

    return (
        <button
            onClick={handleToggle}
            className={`p-2 rounded-lg transition-colors cursor-pointer ${className}`}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
            {theme === 'dark' ? (
                // Sun icon for switching to light
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="5" />
                    <line x1="12" y1="1" x2="12" y2="3" />
                    <line x1="12" y1="21" x2="12" y2="23" />
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                    <line x1="1" y1="12" x2="3" y2="12" />
                    <line x1="21" y1="12" x2="23" y2="12" />
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                </svg>
            ) : (
                // Moon icon for switching to dark
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
            )}
        </button>
    )
}

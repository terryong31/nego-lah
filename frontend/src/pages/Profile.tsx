import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { Card } from '../components/Card'
import { useAuth } from '../context/AuthContext'
import { supabase } from '../lib/supabase'

export function Profile() {
    const { user, loading } = useAuth()
    const navigate = useNavigate()
    const fileInputRef = useRef<HTMLInputElement>(null)

    const [displayName, setDisplayName] = useState('')
    const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
    const [isUpdating, setIsUpdating] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [success, setSuccess] = useState<string | null>(null)

    useEffect(() => {
        if (user) {
            setDisplayName(user.user_metadata?.full_name || user.email?.split('@')[0] || '')
            setAvatarUrl(user.user_metadata?.avatar_url || null)
        }
    }, [user])

    if (loading) {
        return (
            <div className="min-h-screen bg-[var(--bg-primary)] flex items-center justify-center">
                <div className="w-8 h-8 border-2 border-zinc-700 border-t-white rounded-full animate-spin" />
            </div>
        )
    }

    if (!user) {
        navigate('/login')
        return null
    }

    const handleAvatarClick = () => {
        fileInputRef.current?.click()
    }

    const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        setIsUpdating(true)
        setError(null)

        try {
            // Upload to Supabase Storage - images bucket, users subfolder
            const fileExt = file.name.split('.').pop()
            const fileName = `users/${user.id}/avatar.${fileExt}`

            const { error: uploadError } = await supabase.storage
                .from('images')
                .upload(fileName, file, { upsert: true })

            if (uploadError) throw uploadError

            // Get public URL
            const { data: { publicUrl } } = supabase.storage
                .from('images')
                .getPublicUrl(fileName)

            // Update user metadata
            const { error: updateError } = await supabase.auth.updateUser({
                data: { avatar_url: publicUrl }
            })

            if (updateError) throw updateError

            setAvatarUrl(publicUrl)
            setSuccess('Avatar updated!')
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to upload avatar')
        } finally {
            setIsUpdating(false)
        }
    }

    const handleUpdateProfile = async (e: React.FormEvent) => {
        e.preventDefault()
        setIsUpdating(true)
        setError(null)
        setSuccess(null)

        try {
            const { error } = await supabase.auth.updateUser({
                data: { full_name: displayName }
            })

            if (error) throw error
            setSuccess('Profile updated successfully!')
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to update profile')
        } finally {
            setIsUpdating(false)
        }
    }

    return (
        <div className="min-h-screen bg-[var(--bg-primary)]">
            {/* Stars Background */}
            <div className="stars-container">
                <div className="stars"></div>
            </div>

            {/* Header */}
            <header className="border-b border-[var(--border)] bg-[var(--header-bg)] backdrop-blur-sm sticky top-0 z-10 relative">
                <div className="max-w-2xl mx-auto px-4 py-4 flex items-center gap-4">
                    <button
                        onClick={() => navigate('/')}
                        className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                        aria-label="Back"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                    </button>
                    <h1 className="text-xl font-semibold text-[var(--text-primary)]">Profile</h1>
                </div>
            </header>

            {/* Main Content */}
            <main className="max-w-2xl mx-auto px-4 py-8 relative z-10">
                <Card className="bg-[var(--card-bg)] border-[var(--border)]">
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

                    {/* Avatar Section */}
                    <div className="flex flex-col items-center mb-8">
                        <button
                            onClick={handleAvatarClick}
                            className="relative group"
                            disabled={isUpdating}
                        >
                            {avatarUrl ? (
                                <img
                                    src={avatarUrl}
                                    alt="Profile"
                                    className="w-24 h-24 rounded-full object-cover border-2 border-[var(--border)]"
                                />
                            ) : (
                                <div className="w-24 h-24 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center text-2xl font-semibold text-[var(--text-secondary)]">
                                    {displayName?.charAt(0).toUpperCase() || 'U'}
                                </div>
                            )}
                            <div className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                                    <circle cx="12" cy="13" r="4" />
                                </svg>
                            </div>
                        </button>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept="image/*"
                            onChange={handleAvatarChange}
                            className="hidden"
                        />
                        <p className="text-sm text-[var(--text-muted)] mt-2">
                            Click to change avatar
                        </p>
                    </div>

                    {/* Profile Form */}
                    <form onSubmit={handleUpdateProfile} className="space-y-4">
                        <Input
                            label="Display Name"
                            value={displayName}
                            onChange={(e) => setDisplayName(e.target.value)}
                            disabled={isUpdating}
                        />

                        <div>
                            <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">
                                Email
                            </label>
                            <p className="px-4 py-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-[var(--text-muted)]">
                                {user.email}
                            </p>
                            <p className="text-xs text-[var(--text-muted)] mt-1">
                                Email cannot be changed
                            </p>
                        </div>

                        <div className="pt-4">
                            <Button type="submit" fullWidth disabled={isUpdating} variant="filled">
                                {isUpdating ? 'Saving...' : 'Save Changes'}
                            </Button>
                        </div>
                    </form>
                </Card>
            </main>
        </div>
    )
}

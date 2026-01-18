import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import { Card } from '../components/Card'
import { Button } from '../components/Button'
import { Input } from '../components/Input'

export function ProfileSetup() {
    const { user } = useAuth()
    const navigate = useNavigate()
    const [displayName, setDisplayName] = useState('')
    const [avatarFile, setAvatarFile] = useState<File | null>(null)
    const [avatarPreview, setAvatarPreview] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)

    const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (file) {
            setAvatarFile(file)
            setAvatarPreview(URL.createObjectURL(file))
        }
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!user) return

        setIsLoading(true)
        setError(null)

        try {
            let avatarUrl = null

            // Upload avatar if selected
            if (avatarFile) {
                const fileExt = avatarFile.name.split('.').pop()
                const fileName = `${user.id}-${Date.now()}.${fileExt}`
                const { error: uploadError } = await supabase.storage
                    .from('avatars')
                    .upload(fileName, avatarFile)

                if (uploadError) throw uploadError

                const { data: { publicUrl } } = supabase.storage
                    .from('avatars')
                    .getPublicUrl(fileName)
                avatarUrl = publicUrl
            }

            // Update user profile in Supabase
            const updates: { avatar_url?: string; full_name?: string } = {}
            if (avatarUrl) updates.avatar_url = avatarUrl
            if (displayName.trim()) updates.full_name = displayName.trim()

            if (Object.keys(updates).length > 0) {
                const { error: updateError } = await supabase.auth.updateUser({
                    data: updates
                })
                if (updateError) throw updateError
            }

            // Navigate to home with success message
            navigate('/?confirmed=true')
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to update profile')
        } finally {
            setIsLoading(false)
        }
    }

    const handleSkip = () => {
        navigate('/?confirmed=true')
    }

    return (
        <div className="min-h-screen bg-[var(--bg-primary)] flex items-center justify-center p-4">
            {/* Background effects */}
            <div className="fixed inset-0 overflow-hidden pointer-events-none">
                <div className="stars"></div>
            </div>

            <Card className="w-full max-w-md relative z-10">
                <div className="mb-6 text-center">
                    <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-green-500/20 flex items-center justify-center">
                        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-green-500">
                            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                            <polyline points="22 4 12 14.01 9 11.01" />
                        </svg>
                    </div>
                    <h1 className="text-xl font-semibold text-[var(--text-primary)]">Email Confirmed!</h1>
                    <p className="text-sm text-[var(--text-secondary)] mt-1">
                        Set up your profile to get started
                    </p>
                </div>

                {error && (
                    <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
                        {error}
                    </div>
                )}

                <form onSubmit={handleSubmit} className="space-y-4">
                    {/* Avatar Upload */}
                    <div className="flex flex-col items-center gap-3">
                        <div
                            onClick={() => fileInputRef.current?.click()}
                            className="w-20 h-20 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center cursor-pointer hover:opacity-80 transition-opacity overflow-hidden border-2 border-dashed border-[var(--border)]"
                        >
                            {avatarPreview ? (
                                <img src={avatarPreview} alt="Preview" className="w-full h-full object-cover" />
                            ) : (
                                <span className="text-[var(--text-muted)] text-sm">Add Photo</span>
                            )}
                        </div>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept="image/*"
                            onChange={handleAvatarChange}
                            className="hidden"
                        />
                        <p className="text-xs text-[var(--text-muted)]">Optional</p>
                    </div>

                    {/* Display Name */}
                    <Input
                        type="text"
                        label="Display Name"
                        placeholder="How should we call you?"
                        value={displayName}
                        onChange={(e) => setDisplayName(e.target.value)}
                        disabled={isLoading}
                    />
                    <p className="text-xs text-[var(--text-muted)] -mt-2">Optional</p>

                    {/* Buttons */}
                    <div className="flex gap-3 pt-2">
                        <Button
                            type="button"
                            variant="ghost"
                            onClick={handleSkip}
                            disabled={isLoading}
                            className="flex-1"
                        >
                            Skip
                        </Button>
                        <Button
                            type="submit"
                            variant="filled"
                            disabled={isLoading}
                            className="flex-1"
                        >
                            {isLoading ? 'Saving...' : 'Continue'}
                        </Button>
                    </div>
                </form>
            </Card>
        </div>
    )
}

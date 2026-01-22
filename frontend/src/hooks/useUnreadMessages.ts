import { useState, useEffect } from 'react'
import { supabase } from '../lib/supabase'

/**
 * Hook to track unread messages for a user.
 * Listens to Supabase realtime for new messages and marks as read when chat is opened.
 */
export function useUnreadMessages(userId: string | null) {
    const [hasUnread, setHasUnread] = useState(false)

    useEffect(() => {
        if (!userId) return

        // Subscribe to new messages on this user's channel
        const channel = supabase
            .channel(`unread:${userId}`)
            .on(
                'broadcast',
                { event: 'new_message' },
                (payload) => {
                    const msg = payload.payload
                    // Only mark as unread if message is from admin or system (not from user themselves)
                    if (msg.source === 'admin' || msg.source === 'system' || msg.source === 'ai') {
                        setHasUnread(true)
                    }
                }
            )
            .subscribe()

        return () => {
            supabase.removeChannel(channel)
        }
    }, [userId])

    const markAsRead = () => {
        setHasUnread(false)
    }

    return { hasUnread, markAsRead }
}

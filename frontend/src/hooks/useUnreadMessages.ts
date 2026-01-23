import { useState, useEffect, useRef } from 'react'
import { supabase } from '../lib/supabase'

/**
 * Hook to track unread messages for a user.
 * Listens to Supabase realtime for new messages and marks as read when chat is opened.
 * Uses a separate channel name to avoid conflict with useChat's subscription.
 */
export function useUnreadMessages(userId: string | null) {
    const [hasUnread, setHasUnread] = useState(false)
    const channelRef = useRef<ReturnType<typeof supabase.channel> | null>(null)

    useEffect(() => {
        if (!userId) {
            return
        }

        // Use unique channel name for notifications (separate from chat channel)
        const channelName = `notifications:${userId}`

        // Create and subscribe to channel
        const channel = supabase.channel(channelName)
        channelRef.current = channel

        channel
            .on(
                'broadcast',
                { event: 'new_message' },
                (payload) => {
                    const msg = payload.payload
                    // Only mark as unread if message is from admin or system or AI
                    if (msg && (msg.source === 'admin' || msg.source === 'system' || msg.source === 'ai')) {
                        console.log('[Notification] Received message, setting unread:', msg)
                        setHasUnread(true)
                    }
                }
            )
            .subscribe((status) => {
                console.log('[Notification] Channel subscription status:', status)
            })

        return () => {
            console.log('[Notification] Cleaning up channel:', channelName)
            if (channelRef.current) {
                supabase.removeChannel(channelRef.current)
                channelRef.current = null
            }
        }
    }, [userId])

    const markAsRead = () => {
        setHasUnread(false)
    }

    return { hasUnread, markAsRead }
}

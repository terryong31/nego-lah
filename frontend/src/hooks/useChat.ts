import { useState, useCallback, useEffect, useRef } from 'react'
import { supabase } from '../lib/supabase' // For real-time subscriptions only

const API_URL = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '/api' : 'http://127.0.0.1:8000')

interface Attachment {
    name: string
    type: string
    url: string  // blob URL for display
}

interface Message {
    id: string
    role: 'user' | 'assistant' | 'system'
    content: string
    timestamp: Date
    attachments?: Attachment[]
    source?: 'ai' | 'admin' | 'system' | 'human'
}

interface ChatState {
    messages: Message[]
    isLoading: boolean
    error: string | null
}

export function useChat(userId: string) {
    const [state, setState] = useState<ChatState>({
        messages: [],
        isLoading: false,
        error: null
    })
    const [currentItemId, setCurrentItemId] = useState<string | null>(null)
    const [historyLoaded, setHistoryLoaded] = useState(false)
    const [historyLoading, setHistoryLoading] = useState(true) // True until first load completes
    const isTypingRef = useRef(false) // Track if typing animation is in progress

    // Load conversation history on mount
    useEffect(() => {
        async function loadHistory() {
            if (historyLoaded) return
            setHistoryLoading(true)

            try {
                // Fetch from backend API which includes system messages
                const response = await fetch(`${API_URL}/chat/history/${userId}`)
                if (response.ok) {
                    const data = await response.json()
                    if (data.messages && Array.isArray(data.messages)) {
                        // Convert backend format to frontend Message format
                        // Split AI messages on paragraph breaks to match live typing behavior
                        const messages: Message[] = []

                        data.messages.forEach((msg: { role: string; content: string; source?: string }, idx: number) => {
                            // Map backend roles to frontend roles: 'human' -> 'user', 'ai' -> 'assistant'
                            const frontendRole = msg.role === 'human' ? 'user' :
                                msg.role === 'ai' ? 'assistant' :
                                    msg.role as 'user' | 'assistant' | 'system'

                            // For AI/assistant messages, split on double newlines
                            if (msg.role === 'ai' && msg.content && msg.content.includes('\n\n')) {
                                const paragraphs = msg.content.split('\n\n').filter((p: string) => p.trim())
                                paragraphs.forEach((paragraph: string, pIdx: number) => {
                                    messages.push({
                                        id: `history-${idx}-${pIdx}`,
                                        role: 'assistant',
                                        content: paragraph.trim(),
                                        timestamp: new Date(),
                                        source: (msg.source || 'ai') as 'ai' | 'admin' | 'system' | 'human'
                                    })
                                })
                            } else {
                                messages.push({
                                    id: `history-${idx}`,
                                    role: frontendRole,
                                    content: msg.content,
                                    timestamp: new Date(),
                                    source: msg.source as 'ai' | 'admin' | 'system' | 'human' | undefined
                                })
                            }
                        })

                        setState(prev => ({ ...prev, messages }))
                    }
                }
            } catch {
                // No history found or error - that's fine, start fresh
            }
            setHistoryLoaded(true)
            setHistoryLoading(false)
        }

        if (userId && !userId.startsWith('guest-')) {
            loadHistory()
        } else {
            setHistoryLoaded(true)
            setHistoryLoading(false)
        }
    }, [userId, historyLoaded])

    // NOTE: Messages are saved by backend (memory.py) - no frontend persistence needed

    const sendMessage = useCallback(async (message: string, itemId?: string, attachments?: File[]) => {
        // Create attachment objects with blob URLs for display
        const attachmentObjects: Attachment[] = attachments?.map(file => ({
            name: file.name,
            type: file.type,
            url: URL.createObjectURL(file)
        })) || []

        const userMessage: Message = {
            id: crypto.randomUUID(),
            role: 'user',
            content: message,
            timestamp: new Date(),
            attachments: attachmentObjects.length > 0 ? attachmentObjects : undefined
        }

        // Check AI status from backend BEFORE showing placeholder
        let aiEnabled = true
        try {
            const response = await fetch(`${API_URL}/chat/settings/${userId}`)
            if (response.ok) {
                const data = await response.json()
                aiEnabled = data.ai_enabled ?? true
            }
        } catch {
            // Default to AI enabled if check fails
        }

        const assistantMessageId = crypto.randomUUID()
        const assistantPlaceholder: Message = {
            id: assistantMessageId,
            role: 'assistant',
            content: '',
            timestamp: new Date(),
            source: 'ai'
        }

        // Add user message, and only add assistant placeholder if AI is enabled
        if (aiEnabled) {
            setState(prev => ({
                ...prev,
                messages: [...prev.messages, userMessage, assistantPlaceholder],
                isLoading: true,
                error: null
            }))
        } else {
            // AI disabled - just add user message, no loading state
            setState(prev => ({
                ...prev,
                messages: [...prev.messages, userMessage],
                isLoading: false,
                error: null
            }))
        }

        if (itemId) {
            setCurrentItemId(itemId)
        }

        let assistantMessageAdded = aiEnabled


        try {
            // Use FormData if there are attachments
            let res: Response
            if (attachments && attachments.length > 0) {
                const formData = new FormData()
                formData.append('user_id', userId)
                formData.append('message', message)
                if (itemId || currentItemId) {
                    formData.append('item_id', itemId || currentItemId || '')
                }
                attachments.forEach((file) => {
                    formData.append('files', file)
                })

                res = await fetch(`${API_URL}/chat/stream`, {
                    method: 'POST',
                    body: formData
                })
            } else {
                res = await fetch(`${API_URL}/chat/stream`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: userId,
                        message,
                        item_id: itemId || currentItemId
                    })
                })
            }

            // Broadcast message to Admin
            await supabase.channel(`chat:${userId}`).send({
                type: 'broadcast',
                event: 'new_message',
                payload: {
                    role: 'human',
                    content: message,
                    source: 'human',
                    timestamp: new Date().toISOString()
                }
            })

            if (res.ok && res.body) {
                const reader = res.body.getReader()
                const decoder = new TextDecoder()

                try {
                    while (true) {
                        const { done, value } = await reader.read()
                        if (done) break

                        const chunk = decoder.decode(value, { stream: true })
                        const lines = chunk.split('\n')

                        for (const line of lines) {
                            if (line.startsWith('data: ')) {
                                try {
                                    const data = JSON.parse(line.slice(6))

                                    // Handle completion
                                    if (data.done) {
                                        const fullContent = (data.content || '') as string

                                        // If content is empty (e.g. AI disabled), we typically get done: true with empty content
                                        // If we haven't added assistant message yet, and content is empty, do nothing.
                                        if (!assistantMessageAdded && !fullContent) {
                                            continue
                                        }

                                        // Stop loading immediately
                                        setState(prev => ({ ...prev, isLoading: false }))

                                        // Pre-split content into paragraphs for natural bubble separation
                                        const paragraphs = fullContent.includes('\n\n')
                                            ? fullContent.split('\n\n').filter((p: string) => p.trim())
                                            : [fullContent]

                                        const typingSpeed = 15 // ms per char
                                        let paragraphIndex = 0
                                        let charIndex = 0

                                        // Create placeholder messages for all paragraphs
                                        setState(prev => {
                                            const newMessages: Message[] = []
                                            for (const msg of prev.messages) {
                                                if (msg.id === assistantMessageId) {
                                                    // Replace placeholder with first paragraph placeholder
                                                    paragraphs.forEach((_, pIdx) => {
                                                        newMessages.push({
                                                            id: paragraphs.length > 1 ? `${assistantMessageId}-${pIdx}` : assistantMessageId,
                                                            role: 'assistant' as const,
                                                            content: '', // Start empty
                                                            timestamp: new Date(),
                                                            source: 'ai' as const
                                                        })
                                                    })
                                                } else {
                                                    newMessages.push(msg)
                                                }
                                            }
                                            return { ...prev, messages: newMessages }
                                        })

                                        // Mark typing animation as started
                                        isTypingRef.current = true

                                        const finishTyping = () => {
                                            isTypingRef.current = false
                                        }

                                        const typeCharWithCallback = () => {
                                            if (paragraphIndex >= paragraphs.length) {
                                                finishTyping()
                                                return
                                            }

                                            const currentParagraph = paragraphs[paragraphIndex]
                                            charIndex += Math.floor(Math.random() * 2) + 1
                                            if (charIndex > currentParagraph.length) charIndex = currentParagraph.length

                                            const currentMsgId = paragraphs.length > 1
                                                ? `${assistantMessageId}-${paragraphIndex}`
                                                : assistantMessageId
                                            const currentText = currentParagraph.substring(0, charIndex)

                                            setState(prev => {
                                                const newMessages = prev.messages.map(msg =>
                                                    msg.id === currentMsgId ? { ...msg, content: currentText } : msg
                                                )
                                                return { ...prev, messages: newMessages }
                                            })

                                            if (charIndex < currentParagraph.length) {
                                                setTimeout(typeCharWithCallback, typingSpeed)
                                            } else if (paragraphIndex < paragraphs.length - 1) {
                                                // Move to next paragraph after a small pause
                                                paragraphIndex++
                                                charIndex = 0
                                                setTimeout(typeCharWithCallback, 200) // Pause between bubbles
                                            } else {
                                                finishTyping()
                                            }
                                        }

                                        typeCharWithCallback()
                                    } else {
                                        // Streaming update (not done yet) - ignore if we are simulating
                                    }
                                } catch { /* ignore */ }
                            }
                        }
                    }
                } finally {
                    setState(prev => ({ ...prev, isLoading: false }))
                }
            } else {
                // ... fallback code ...
                const fallbackRes = await fetch(`${API_URL}/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: userId,
                        message,
                        item_id: itemId || currentItemId
                    })
                })

                if (fallbackRes.ok) {
                    const data = await fallbackRes.json()
                    // Only add message if we got a response
                    if (data.response) {
                        setState(prev => ({
                            ...prev,
                            messages: [...prev.messages, {
                                id: assistantMessageId,
                                role: 'assistant',
                                content: data.response,
                                timestamp: new Date()
                            }],
                            isLoading: false
                        }))
                    }
                } else {
                    const data = await fallbackRes.json()
                    setState(prev => ({
                        ...prev,
                        isLoading: false,
                        error: data.detail || 'Failed to send message'
                    }))
                }
            }
        } catch {
            setState(prev => ({
                ...prev,
                isLoading: false,
                error: 'Connection error'
            }))
        }
    }, [userId, currentItemId])

    const clearChat = useCallback(async () => {
        setState({
            messages: [],
            isLoading: false,
            error: null
        })
        setCurrentItemId(null)

        // Delete from backend
        if (!userId.startsWith('guest-')) {
            try {
                await fetch(`${API_URL}/chat/history/${userId}`, { method: 'DELETE' })
            } catch (error) {
                console.error('Failed to clear conversation:', error)
            }
        }
    }, [userId])

    // Real-time subscription
    const [isPartnerTyping, setIsPartnerTyping] = useState(false)
    const typingTimeoutRef = useRef<any>(null)

    const sendTyping = useCallback(async () => {
        if (!userId || userId.startsWith('guest-')) return

        await supabase.channel(`chat:${userId}`).send({
            type: 'broadcast',
            event: 'typing',
            payload: { source: 'user' }
        })
    }, [userId])

    useEffect(() => {
        if (!userId || userId.startsWith('guest-')) return

        const channel = supabase.channel(`chat:${userId}`)

        channel
            .on(
                'postgres_changes',
                {
                    event: 'UPDATE',
                    schema: 'public',
                    table: 'conversations',
                    filter: `user_id=eq.${userId}`
                },
                (payload) => {
                    // Skip updates while loading or typing animation is in progress
                    // This prevents DB sync from overwriting the typing effect
                    if (isTypingRef.current) return

                    setState(prev => {
                        if (prev.isLoading) return prev

                        // Update local messages when DB changes (e.g. Admin sent a message)
                        const dbMessages = payload.new.messages as any[]
                        if (dbMessages && Array.isArray(dbMessages)) {
                            // Convert backend format to frontend format
                            // Backend uses 'human'/'ai', frontend expects 'user'/'assistant'
                            const parsedMessages: Message[] = dbMessages.map(msg => {
                                const frontendRole = msg.role === 'human' ? 'user' :
                                    msg.role === 'ai' ? 'assistant' :
                                        msg.role as 'user' | 'assistant' | 'system'

                                return {
                                    id: msg.id || crypto.randomUUID(),
                                    role: frontendRole,
                                    content: msg.content,
                                    timestamp: new Date(msg.timestamp),
                                    source: msg.source
                                }
                            })
                            return { ...prev, messages: parsedMessages }
                        }
                        return prev
                    })
                }
            )
            .on(
                'broadcast',
                { event: 'typing' },
                (payload) => {
                    if (payload.payload.source === 'admin') {
                        setIsPartnerTyping(true)
                        // Clear existing timeout
                        if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current)
                        // Set new timeout to clear typing status
                        typingTimeoutRef.current = setTimeout(() => setIsPartnerTyping(false), 3000)
                    }
                }
            )
            .on(
                'broadcast',
                { event: 'new_message' },
                (payload) => {
                    const msg = payload.payload
                    // Only add if it's not from us (source != human) or if it's a system/admin message we want to see immediately
                    // The backend broadcasts all messages, so strictly we might just want to reload or append if ID mismatch
                    // But effectively, if source is 'admin', append it.
                    if (msg.source === 'admin' || msg.source === 'system') {
                        const newMessage: Message = {
                            id: crypto.randomUUID(),
                            role: msg.role === 'human' ? 'user' : msg.role === 'ai' ? 'assistant' : msg.role,
                            content: msg.content,
                            timestamp: new Date(), // msg.timestamp is 'now()' string, just use client time or parse if needed
                            source: msg.source
                        }
                        setState(prev => ({
                            ...prev,
                            messages: [...prev.messages, newMessage]
                        }))
                    }
                }
            )
            .subscribe()

        return () => {
            supabase.removeChannel(channel)
            if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current)
        }
    }, [userId])

    const loadMoreMessages = useCallback(async () => {
        if (!userId) return false

        try {
            // Get current message count directly from state at call time
            const currentCount = state.messages.length
            const response = await fetch(`${API_URL}/chat/history/${userId}?limit=20&offset=${currentCount}`)
            if (response.ok) {
                const data = await response.json()
                if (data.messages && Array.isArray(data.messages) && data.messages.length > 0) {
                    const oldMessages: Message[] = []
                    data.messages.forEach((msg: { role: string; content: string; source?: string }, idx: number) => {
                        const frontendRole = msg.role === 'human' ? 'user' :
                            msg.role === 'ai' ? 'assistant' :
                                msg.role as 'user' | 'assistant' | 'system'

                        oldMessages.push({
                            id: `history-${currentCount + idx}-${Date.now()}`,
                            role: frontendRole,
                            content: msg.content,
                            timestamp: new Date(), // In a real app, backend should return timestamp
                            source: msg.source as 'ai' | 'admin' | 'system' | 'human' | undefined
                        })
                    })

                    setState(prev => ({
                        ...prev,
                        messages: [...oldMessages, ...prev.messages]
                    }))
                    return true // Indicate success/more messages found
                }
            }
        } catch {
            // ignore
        }
        return false // No more messages
    }, [userId, state.messages.length])

    return {
        ...state,
        currentItemId,
        historyLoading,
        sendMessage,
        clearChat,
        setCurrentItemId,
        isPartnerTyping,
        sendTyping,
        loadMoreMessages
    }
}

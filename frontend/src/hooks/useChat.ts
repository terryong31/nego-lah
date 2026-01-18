import { useState, useCallback, useEffect } from 'react'
import { supabase } from '../lib/supabase'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

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

    // Load conversation history on mount
    useEffect(() => {
        async function loadHistory() {
            if (historyLoaded) return

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
        }

        if (userId && !userId.startsWith('guest-')) {
            loadHistory()
        } else {
            setHistoryLoaded(true)
        }
    }, [userId, historyLoaded])

    // Save messages to Supabase when they change
    useEffect(() => {
        async function saveHistory() {
            if (!historyLoaded || state.messages.length === 0) return
            if (userId.startsWith('guest-')) return

            const messagesToSave = state.messages.map(msg => ({
                ...msg,
                timestamp: msg.timestamp.toISOString()
            }))

            try {
                // Check if conversation exists
                const { data: existing } = await supabase
                    .from('conversations')
                    .select('id')
                    .eq('user_id', userId)
                    .single()

                if (existing) {
                    await supabase
                        .from('conversations')
                        .update({ messages: messagesToSave, updated_at: new Date().toISOString() })
                        .eq('user_id', userId)
                } else {
                    await supabase
                        .from('conversations')
                        .insert({ user_id: userId, messages: messagesToSave })
                }
            } catch (error) {
                console.error('Failed to save conversation:', error)
            }
        }

        saveHistory()
    }, [state.messages, userId, historyLoaded])

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

        // Create placeholder for assistant message
        const assistantMessageId = crypto.randomUUID()
        const assistantMessage: Message = {
            id: assistantMessageId,
            role: 'assistant',
            content: '',
            timestamp: new Date()
        }

        setState(prev => ({
            ...prev,
            messages: [...prev.messages, userMessage, assistantMessage],
            isLoading: true,
            error: null
        }))

        if (itemId) {
            setCurrentItemId(itemId)
        }

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

            if (res.ok && res.body) {
                const reader = res.body.getReader()
                const decoder = new TextDecoder()

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    const chunk = decoder.decode(value, { stream: true })
                    const lines = chunk.split('\n')

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6))

                                if (data.content && data.done) {
                                    // Full response received - animate typing with bubble splitting
                                    const fullContent = data.content as string
                                    let currentMsgId: string = assistantMessageId
                                    let currentContent = ''
                                    let msgIndex = 0

                                    for (let i = 0; i < fullContent.length; i++) {
                                        const char = fullContent[i]
                                        currentContent += char

                                        // Check for paragraph break (\n\n)
                                        if (currentContent.endsWith('\n\n') && i < fullContent.length - 1) {
                                            // Finalize current bubble without trailing newlines
                                            const finalContent = currentContent.slice(0, -2).trim()
                                            if (finalContent) {
                                                setState(prev => ({
                                                    ...prev,
                                                    messages: prev.messages.map(msg =>
                                                        msg.id === currentMsgId
                                                            ? { ...msg, content: finalContent }
                                                            : msg
                                                    )
                                                }))
                                            }

                                            // Create new message for next paragraph
                                            msgIndex++
                                            const newMsgId = `${assistantMessageId}-${msgIndex}`
                                            currentMsgId = newMsgId
                                            currentContent = ''

                                            setState(prev => ({
                                                ...prev,
                                                messages: [
                                                    ...prev.messages,
                                                    {
                                                        id: newMsgId,
                                                        role: 'assistant' as const,
                                                        content: '',
                                                        timestamp: new Date()
                                                    }
                                                ]
                                            }))
                                        } else {
                                            // Update current message content
                                            setState(prev => ({
                                                ...prev,
                                                messages: prev.messages.map(msg =>
                                                    msg.id === currentMsgId
                                                        ? { ...msg, content: currentContent.trim() }
                                                        : msg
                                                )
                                            }))
                                        }

                                        // Typing delay - 15ms per character
                                        await new Promise(resolve => setTimeout(resolve, 15))
                                    }

                                    // Done with animation
                                    setState(prev => ({
                                        ...prev,
                                        isLoading: false
                                    }))
                                }
                            } catch {
                                // Skip invalid JSON
                            }
                        }
                    }
                }
            } else {
                // Fallback to non-streaming endpoint
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
                    setState(prev => ({
                        ...prev,
                        messages: prev.messages.map(msg =>
                            msg.id === assistantMessageId
                                ? { ...msg, content: data.response }
                                : msg
                        ),
                        isLoading: false
                    }))
                } else {
                    const data = await fallbackRes.json()
                    setState(prev => ({
                        ...prev,
                        messages: prev.messages.filter(msg => msg.id !== assistantMessageId),
                        isLoading: false,
                        error: data.detail || 'Failed to send message'
                    }))
                }
            }
        } catch {
            setState(prev => ({
                ...prev,
                messages: prev.messages.filter(msg => msg.id !== assistantMessageId),
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

        // Delete from Supabase
        if (!userId.startsWith('guest-')) {
            try {
                await supabase
                    .from('conversations')
                    .delete()
                    .eq('user_id', userId)
            } catch (error) {
                console.error('Failed to clear conversation:', error)
            }
        }
    }, [userId])

    return {
        ...state,
        currentItemId,
        sendMessage,
        clearChat,
        setCurrentItemId
    }
}

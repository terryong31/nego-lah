import { useState, useRef, useEffect, useLayoutEffect } from 'react'
import { Button } from '../components/Button'
import { ChatBubble } from '../components/ChatBubble'
import { useChat } from '../hooks/useChat'

interface ChatProps {
    userId: string
    itemId?: string
    itemName?: string
    onBack: () => void
    userAvatar?: string
    userName?: string
}

export function Chat({ userId, itemId, itemName, onBack, userAvatar, userName }: ChatProps) {
    const { messages, isLoading, error, sendMessage, isPartnerTyping, sendTyping, loadMoreMessages, historyLoading, activePaymentUrls } = useChat(userId)
    const [input, setInput] = useState('')
    const [attachments, setAttachments] = useState<File[]>([])
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const mainRef = useRef<HTMLDivElement>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const hasSetInitialPlaceholder = useRef(false)

    // Placeholder is always "Enter your message" - the initial item text is put directly in input
    const placeholderText = 'Enter your message'

    // Set initial input with item context when opening chat for an item
    useEffect(() => {
        if (itemId && itemName && messages.length === 0 && !hasSetInitialPlaceholder.current) {
            hasSetInitialPlaceholder.current = true
            setInput(`Hi, I'm interested in "${itemName}". Can you tell me more about it?`)
        }
    }, [itemId, itemName, messages.length])

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }

    // Track if we're loading history to skip auto-scroll
    const isLoadingHistoryRef = useRef(false)

    useEffect(() => {
        // Skip auto-scroll when loading history
        if (isLoadingHistoryRef.current) return
        scrollToBottom()
    }, [messages])

    // Auto-resize textarea when input changes (including initial item message)
    useLayoutEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto'
            textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight + 2, 104)}px`
        }
    }, [input])

    // Wrap loadMoreMessages to preserve scroll position
    const handleLoadMore = async () => {
        const container = mainRef.current
        if (!container) return

        // Mark that we're loading history
        isLoadingHistoryRef.current = true

        // Store current scroll state BEFORE loading
        const scrollHeightBefore = container.scrollHeight
        const scrollTopBefore = container.scrollTop

        const success = await loadMoreMessages()

        if (success) {
            // Use double requestAnimationFrame for reliable DOM update
            // First RAF waits for React to commit, second RAF waits for paint
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    const scrollHeightAfter = container.scrollHeight
                    const scrollDiff = scrollHeightAfter - scrollHeightBefore
                    // Restore scroll so user sees same content they were viewing
                    container.scrollTop = scrollTopBefore + scrollDiff
                    // Reset flag after scroll restoration
                    isLoadingHistoryRef.current = false
                })
            })
        } else {
            isLoadingHistoryRef.current = false
        }
    }



    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        // Allow submission with text OR attachments
        if ((input.trim() || attachments.length > 0) && !isLoading) {
            sendMessage(input.trim(), itemId, attachments)
            setInput('')
            setAttachments([])
        }
    }

    const handleAttachmentClick = () => {
        fileInputRef.current?.click()
    }

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (files && files.length > 0) {
            // Only accept image files
            const imageFiles = Array.from(files).filter(f => f.type.startsWith('image/'))
            if (imageFiles.length > 0) {
                setAttachments(prev => [...prev, ...imageFiles])
            }
        }
        // Reset input so same file can be selected again
        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }

    const handlePaste = (e: React.ClipboardEvent) => {
        const items = e.clipboardData?.items
        if (!items) return

        const imageFiles: File[] = []
        for (let i = 0; i < items.length; i++) {
            if (items[i].type.startsWith('image/')) {
                const file = items[i].getAsFile()
                if (file) {
                    imageFiles.push(file)
                }
            }
        }

        if (imageFiles.length > 0) {
            setAttachments(prev => [...prev, ...imageFiles])
        }
    }

    const removeAttachment = (index: number) => {
        setAttachments(prev => prev.filter((_, i) => i !== index))
    }

    return (
        <div className="h-screen flex flex-col overflow-hidden">
            {/* Stars Background */}
            <div className="stars-container">
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="stars"></div>
            </div>

            {/* Header - Fixed at top */}
            <header className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--header-bg)] backdrop-blur-sm z-20">
                <div className="max-w-2xl mx-auto px-4 py-4 flex items-center gap-4">
                    <button
                        onClick={onBack}
                        className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                        aria-label="Back"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                    </button>
                    <div className="flex-1">
                        <h1 className="text-lg font-semibold text-[var(--text-primary)]">Chat</h1>
                        {itemName && (
                            <p className="text-sm text-[var(--text-muted)]">Discussing: {itemName}</p>
                        )}
                    </div>
                </div>
            </header>

            {/* Messages - Scrollable middle section */}
            <main ref={mainRef} className="flex-1 overflow-y-auto relative z-10">
                <div className="max-w-2xl mx-auto px-4 py-6 space-y-4">
                    {/* Load More Button - only show if more than 10 messages */}
                    {messages.length > 10 && (
                        <div className="flex justify-center">
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={handleLoadMore}
                                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-xs"
                            >
                                Load previous messages
                            </Button>
                        </div>
                    )}

                    {historyLoading && (
                        <div className="space-y-4 animate-pulse">
                            {/* Skeleton message bubbles */}
                            <div className="flex gap-3">
                                <div className="w-8 h-8 rounded-full bg-[var(--bg-tertiary)]" />
                                <div className="flex-1">
                                    <div className="h-4 bg-[var(--bg-tertiary)] rounded w-24 mb-2" />
                                    <div className="h-16 bg-[var(--bg-tertiary)] rounded w-3/4" />
                                </div>
                            </div>
                            <div className="flex gap-3 justify-end">
                                <div className="flex-1 flex flex-col items-end">
                                    <div className="h-4 bg-[var(--bg-tertiary)] rounded w-20 mb-2" />
                                    <div className="h-12 bg-[var(--bg-tertiary)] rounded w-2/3" />
                                </div>
                                <div className="w-8 h-8 rounded-full bg-[var(--bg-tertiary)]" />
                            </div>
                            <div className="flex gap-3">
                                <div className="w-8 h-8 rounded-full bg-[var(--bg-tertiary)]" />
                                <div className="flex-1">
                                    <div className="h-4 bg-[var(--bg-tertiary)] rounded w-28 mb-2" />
                                    <div className="h-20 bg-[var(--bg-tertiary)] rounded w-4/5" />
                                </div>
                            </div>
                        </div>
                    )}

                    {messages.length === 0 && !isLoading && !historyLoading && (
                        <div className="text-center py-12">
                            <p className="text-[var(--text-muted)] mb-2">
                                {itemName ? `Ask about "${itemName}"` : 'Start a conversation'}
                            </p>
                            <p className="text-xs text-[var(--text-muted)] opacity-60">
                                Send a message to begin
                            </p>
                        </div>
                    )}

                    {messages.map((msg) => {
                        // Skip empty assistant messages (shown as "Generating..." instead)
                        if (msg.role === 'assistant' && !msg.content) {
                            return null
                        }

                        // System messages - centered gray styling
                        if (msg.role === 'system') {
                            return (
                                <div key={msg.id} className="flex justify-center py-2">
                                    <span className="text-sm text-[var(--text-muted)] italic">
                                        {msg.content}
                                    </span>
                                </div>
                            )
                        }

                        // Determine avatar text based on source
                        const getAvatarText = () => {
                            if (msg.role === 'user') return undefined
                            // Admin messages show "T", AI messages show "AI"
                            return msg.source === 'admin' ? 'T' : 'AI'
                        }

                        const getUserName = () => {
                            if (msg.role === 'user') return userName
                            return msg.source === 'admin' ? 'Terry' : 'AI Assistant'
                        }

                        return (
                            <ChatBubble
                                key={msg.id}
                                message={msg.content}
                                isUser={msg.role === 'user'}
                                timestamp={msg.timestamp.toLocaleTimeString([], {
                                    hour: '2-digit',
                                    minute: '2-digit'
                                })}
                                avatarUrl={msg.role === 'user' ? userAvatar : undefined}
                                userName={getUserName()}
                                avatarText={getAvatarText()}
                                attachments={msg.attachments}
                                activePaymentUrls={activePaymentUrls}
                            />
                        )
                    })}

                    {/* Show "Generating..." when loading AND the last assistant message has no content yet */}
                    {isLoading && messages.length > 0 && messages[messages.length - 1]?.role === 'assistant' && !messages[messages.length - 1]?.content && (
                        <div className="flex gap-3">
                            {/* AI Avatar */}
                            <div className="flex-shrink-0">
                                <div className="w-8 h-8 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center text-xs font-medium text-[var(--text-secondary)]">
                                    AI
                                </div>
                            </div>
                            {/* Typing indicator */}
                            <div className="flex items-center">
                                <span className="text-[var(--text-muted)] text-sm italic animate-pulse">
                                    Thinking...
                                </span>
                            </div>
                        </div>
                    )}

                    {error && (
                        <p className="text-center text-red-500 text-sm">{error}</p>
                    )}

                    {/* Admin Typing Indicator */}
                    {isPartnerTyping && (
                        <div className="flex justify-start my-4">
                            <div className="flex gap-3 max-w-[80%]">
                                <div className="w-8 h-8 rounded-full bg-[var(--bg-secondary)] flex-shrink-0 flex items-center justify-center text-xs font-medium border border-[var(--border)] text-[var(--text-secondary)]">
                                    T
                                </div>
                                <div className="flex items-center">
                                    <span className="text-[var(--text-muted)] text-sm italic animate-pulse">
                                        Typing...
                                    </span>
                                </div>
                            </div>
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                </div>
            </main>

            {/* Input - Fixed at bottom */}
            <footer className="flex-shrink-0 border-t border-[var(--border)] bg-[var(--header-bg)] backdrop-blur-sm z-20">
                <form onSubmit={handleSubmit} className="max-w-2xl mx-auto px-4 py-4">
                    {/* Attachments preview */}
                    {attachments.length > 0 && (
                        <div className="mb-3 flex flex-wrap gap-2">
                            {attachments.map((file, index) => (
                                <div key={index} className="relative group">
                                    <div className="relative">
                                        <img
                                            src={URL.createObjectURL(file)}
                                            alt={file.name}
                                            className="w-16 h-16 object-cover rounded-lg border border-[var(--border)]"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => removeAttachment(index)}
                                            className="absolute -top-2 -right-2 w-5 h-5 bg-zinc-500 text-white rounded-full flex items-center justify-center text-xs hover:bg-zinc-600 transition-colors"
                                        >
                                            ×
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    <div className="flex gap-3 items-center">
                        {/* Hidden file input - images only */}
                        <input
                            ref={fileInputRef}
                            type="file"
                            onChange={handleFileChange}
                            accept="image/*"
                            multiple
                            className="hidden"
                        />

                        {/* Attachment button */}
                        <button
                            type="button"
                            onClick={handleAttachmentClick}
                            className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                            aria-label="Add attachment"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                            </svg>
                        </button>

                        <textarea
                            ref={textareaRef}
                            value={input}
                            onChange={(e) => {
                                setInput(e.target.value)
                                sendTyping()
                            }}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault()
                                    if (!isLoading && !historyLoading && (input.trim() || attachments.length > 0)) {
                                        handleSubmit(e as unknown as React.FormEvent)
                                    }
                                }
                            }}
                            onPaste={handlePaste}
                            placeholder={historyLoading ? 'Loading messages...' : placeholderText}
                            disabled={isLoading || historyLoading}
                            rows={1}
                            className="flex-1 px-4 py-3 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-xl text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--input-focus-border)] disabled:opacity-50 resize-none overflow-y-auto"
                        />
                        <Button type="submit" variant="filled" disabled={isLoading || historyLoading || (!input.trim() && attachments.length === 0)}>
                            Send
                        </Button>
                    </div>
                </form>
            </footer>
        </div>
    )
}

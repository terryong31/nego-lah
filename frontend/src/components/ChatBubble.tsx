import ReactMarkdown from 'react-markdown'

interface Attachment {
    name: string
    type: string
    url: string
}

interface ChatBubbleProps {
    message: string
    isUser: boolean
    timestamp?: string
    avatarUrl?: string
    userName?: string
    avatarText?: string  // Explicit avatar text override
    isAi?: boolean
    attachments?: Attachment[]
}

export function ChatBubble({ message, isUser, isAi, timestamp, avatarUrl, userName, avatarText, attachments }: ChatBubbleProps) {
    const initials = avatarText || (userName
        ? userName.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase()
        : isUser ? 'ME' : isAi ? 'AI' : 'U')

    return (
        <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
            {/* Avatar */}
            <div className="flex-shrink-0">
                {avatarUrl ? (
                    <img
                        src={avatarUrl}
                        alt={userName || 'Avatar'}
                        className="w-8 h-8 rounded-full object-cover"
                    />
                ) : (
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium bg-[var(--bg-tertiary)] text-[var(--text-secondary)]`}>
                        {initials}
                    </div>
                )}
            </div>

            {/* Message Bubble */}
            <div
                className={`
                    max-w-[75%] px-4 py-3 rounded-2xl
                    ${isUser
                        ? 'user-chat-bubble rounded-tr-md'
                        : isAi
                            ? 'bg-[var(--bg-tertiary)] text-[var(--text-primary)] rounded-tl-md'
                            : 'buyer-chat-bubble rounded-tl-md'
                    }
                `}
            >
                {/* Attachments - displayed above message */}
                {attachments && attachments.length > 0 && (
                    <div className="mb-2 space-y-2">
                        {attachments.map((attachment, index) => (
                            <div key={index}>
                                {attachment.type.startsWith('image/') ? (
                                    <img
                                        src={attachment.url}
                                        alt={attachment.name}
                                        className="max-w-full rounded-lg max-h-48 object-cover"
                                    />
                                ) : (
                                    <div className="flex items-center gap-2 px-3 py-2 bg-black/10 rounded-lg">
                                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                                            <polyline points="14 2 14 8 20 8" />
                                        </svg>
                                        <span className="text-sm truncate">{attachment.name}</span>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}

                {/* Message text */}
                {message && (
                    <div className={`text-sm prose prose-sm max-w-none break-words overflow-hidden ${isUser
                        ? ''
                        : 'prose-neutral dark:prose-invert'
                        }`}>
                        <ReactMarkdown>{message}</ReactMarkdown>
                    </div>
                )}
                {timestamp && (
                    <p className={`text-xs mt-1 opacity-70`}>
                        {timestamp}
                    </p>
                )}
            </div>
        </div>
    )
}

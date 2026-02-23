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
    activePaymentUrls?: string[]
}

// Detect if message contains a payment link or payment text - SIMPLIFIED
function isPaymentLink(message: string): boolean {
    // Detect "Pay RM" pattern which indicates a payment message
    return /Pay\s+RM\s*[\d.]+/i.test(message)
}

// Extract URL from markdown link or raw URL
function extractPaymentUrl(message: string): string | null {
    // Match markdown link format [text](url)
    const markdownMatch = message.match(/\[([^\]]+)\]\(([^)]+)\)/)
    if (markdownMatch && markdownMatch[2].includes('http')) return markdownMatch[2]

    // Match raw URL
    const urlMatch = message.match(/(https?:\/\/[^\s)]+)/)
    if (urlMatch) return urlMatch[1]

    return null
}

// Extract payment amount from text like "Pay RM123.00 Now"
function extractPaymentAmount(message: string): string {
    const amountMatch = message.match(/Pay\s+RM\s*([\d.]+)/i)
    if (amountMatch) return amountMatch[1]
    return ''
}

export function ChatBubble({ message, isUser, isAi, timestamp, avatarUrl, userName, avatarText, attachments, activePaymentUrls }: ChatBubbleProps) {
    const initials = avatarText || (userName
        ? userName.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase()
        : isUser ? 'ME' : isAi ? 'AI' : 'U')

    const hasPaymentLink = !isUser && isPaymentLink(message)
    const paymentUrl = hasPaymentLink ? extractPaymentUrl(message) : null
    const paymentAmount = hasPaymentLink ? extractPaymentAmount(message) : ''

    // Determine if the payment link is active
    // If activePaymentUrls is undefined, we assume it's active (backward compatibility)
    // If we have an array, check if the paymentUrl is in the array
    const isPaymentActive = paymentUrl && (!activePaymentUrls || activePaymentUrls.includes(paymentUrl))

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
            {hasPaymentLink ? (
                // Special Payment Link Bubble - Clean Liquid Glass Design
                <div className="payment-bubble max-w-[85%] rounded-2xl rounded-tl-md overflow-hidden transition-all duration-300 hover:shadow-lg">
                    {/* Header */}
                    <div className="px-5 pt-5 pb-3">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-bold tracking-widest opacity-80 uppercase text-[var(--text-secondary)]">Payment Request</span>
                        </div>
                        <div className="text-3xl font-bold tracking-tight text-[var(--text-primary)]">
                            RM {paymentAmount}
                        </div>
                    </div>

                    {/* Pay Button */}
                    <div className="px-5 pb-5">
                        {paymentUrl ? (
                            isPaymentActive ? (
                                <a
                                    href={paymentUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="payment-button block w-full py-3.5 px-6 font-bold rounded-xl text-center text-sm uppercase tracking-wide cursor-pointer flex items-center justify-center gap-2"
                                >
                                    <span>Click to Pay</span>
                                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M5 12h14" />
                                        <path d="M12 5l7 7-7 7" />
                                    </svg>
                                </a>
                            ) : (
                                <div className="block w-full py-3.5 px-6 font-bold rounded-xl text-center text-sm uppercase tracking-wide cursor-not-allowed flex items-center justify-center gap-2 bg-gray-500 text-gray-200 opacity-80">
                                    <span>Cancelled / Expired</span>
                                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <circle cx="12" cy="12" r="10"></circle>
                                        <line x1="15" y1="9" x2="9" y2="15"></line>
                                        <line x1="9" y1="9" x2="15" y2="15"></line>
                                    </svg>
                                </div>
                            )
                        ) : (
                            <div className="w-full py-3.5 px-6 bg-gray-100 dark:bg-gray-800 text-gray-500 font-medium rounded-xl text-center border border-gray-200 dark:border-gray-700 text-sm">
                                Link unavailable
                            </div>
                        )}
                    </div>

                    {timestamp && (
                        <div className="px-5 pb-3 opacity-60">
                            <p className="text-[10px] text-right font-medium text-[var(--text-secondary)]">
                                {timestamp}
                            </p>
                        </div>
                    )}
                </div>
            ) : (
                // Regular Message Bubble
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
            )}
        </div>
    )
}

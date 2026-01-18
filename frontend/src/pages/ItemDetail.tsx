import { useState, useEffect } from 'react'
import { ThemeToggle } from '../components/ThemeToggle'

interface Item {
    id: string
    name: string
    description: string
    condition: string
    price: number
    image_path?: string
    status?: string
}

interface ItemDetailProps {
    item: Item
    onBack: () => void
    onChat: (itemId: string, itemName?: string) => void
    onBuy: (itemId: string) => void
}

// Glitch Text Component
const GlitchText = ({ text, hoverText, forceHover = false }: { text: string; hoverText: string; forceHover?: boolean }) => {
    const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#%&@$"
    const [displayText, setDisplayText] = useState(text)

    useEffect(() => {
        let interval: ReturnType<typeof setInterval>
        let iteration = 0

        const targetText = forceHover ? hoverText : text

        // If texts are different lengths, pad logic or just accept morphing
        // For "Chat" (4) -> "Nego" (4), it works perfectly.

        if (forceHover || (!forceHover && displayText !== text)) {
            interval = setInterval(() => {
                setDisplayText(() =>
                    targetText
                        .split("")
                        .map((letter, index) => {
                            if (index < iteration) {
                                return letter // Settled letter
                            }
                            return letters[Math.floor(Math.random() * letters.length)] // Random letter
                        })
                        .join("")
                )

                if (iteration >= targetText.length) {
                    clearInterval(interval)
                }

                iteration += 1 / 3 // Controls speed
            }, 30)
        } else {
            setDisplayText(text)
        }

        return () => clearInterval(interval)
    }, [forceHover, text, hoverText])

    return (
        <span className="font-mono inline-block">
            {displayText}
        </span>
    )
}

export function ItemDetail({ item, onBack, onChat, onBuy }: ItemDetailProps) {
    const [currentImageIndex, setCurrentImageIndex] = useState(0)
    const [hoveredSection, setHoveredSection] = useState<'chat' | 'buy' | null>(null)
    const [isBuying, setIsBuying] = useState(false)
    const isSold = item.status === 'sold'

    // Parse all image URLs
    const images: string[] = []
    if (item.image_path) {
        try {
            const parsed = JSON.parse(item.image_path)
            Object.values(parsed).forEach((url) => {
                if (typeof url === 'string') images.push(url)
            })
        } catch { /* ignore */ }
    }

    const nextImage = () => {
        setCurrentImageIndex((prev) => (prev + 1) % images.length)
    }

    const prevImage = () => {
        setCurrentImageIndex((prev) => (prev - 1 + images.length) % images.length)
    }

    return (
        <div className="min-h-screen">
            {/* Stars Background */}
            <div className="stars-container">
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="stars"></div>
            </div>

            {/* Header */}
            <header className="sticky top-0 z-20 bg-[var(--header-bg)] backdrop-blur-md border-b border-[var(--border)]">
                <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
                    <button
                        onClick={onBack}
                        className="flex items-center gap-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                        <span className="text-sm font-medium relative">
                            Back to Store
                            <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover:w-full" />
                        </span>
                    </button>
                    <ThemeToggle className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]" />
                </div>
            </header>

            {/* Main Content - Fits in 1 screen */}
            <main className="relative z-10 max-w-7xl mx-auto px-4 py-4 h-[calc(100vh-80px)] overflow-hidden">
                <div className="flex flex-col lg:flex-row gap-6 h-full">

                    {/* Image Section - Left Column */}
                    <div className="flex-[1.2] flex flex-col min-h-0">
                        {/* Main Image Container */}
                        <div className="relative flex-1 rounded-2xl overflow-hidden bg-[var(--bg-tertiary)] border border-[var(--border)] group">
                            {images.length > 0 ? (
                                <>
                                    <img
                                        src={images[currentImageIndex]}
                                        alt={item.name}
                                        className="w-full h-full object-contain p-2"
                                    />

                                    {/* Navigation Arrows (Only if multiple images) */}
                                    {images.length > 1 && (
                                        <>
                                            <button
                                                onClick={prevImage}
                                                className="absolute left-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/50 hover:bg-black/70 text-white flex items-center justify-center transition-colors opacity-0 group-hover:opacity-100"
                                            >
                                                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                    <path d="M15 18l-6-6 6-6" />
                                                </svg>
                                            </button>
                                            <button
                                                onClick={nextImage}
                                                className="absolute right-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/50 hover:bg-black/70 text-white flex items-center justify-center transition-colors opacity-0 group-hover:opacity-100"
                                            >
                                                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                    <path d="M9 18l6-6-6-6" />
                                                </svg>
                                            </button>
                                        </>
                                    )}

                                    {/* Dots Indicator */}
                                    {images.length > 1 && (
                                        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-2">
                                            {images.map((_, idx) => (
                                                <button
                                                    key={idx}
                                                    onClick={() => setCurrentImageIndex(idx)}
                                                    className={`w-2 h-2 rounded-full transition-colors ${idx === currentImageIndex ? 'bg-white' : 'bg-white/40'}`}
                                                />
                                            ))}
                                        </div>
                                    )}
                                </>
                            ) : (
                                <div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)]">
                                    <span className="text-6xl mb-4">📦</span>
                                    <span>No Image Available</span>
                                </div>
                            )}
                        </div>

                        {/* Thumbnail Strip - Compact */}
                        {images.length > 1 && (
                            <div className="flex gap-2 mt-3 overflow-x-auto pb-1 px-1 h-20 flex-shrink-0">
                                {images.map((url, idx) => (
                                    <button
                                        key={idx}
                                        onClick={() => setCurrentImageIndex(idx)}
                                        className={`flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden border-2 transition-colors ${idx === currentImageIndex ? 'border-[var(--accent)]' : 'border-transparent opacity-60 hover:opacity-100'}`}
                                    >
                                        <img src={url} alt="" className="w-full h-full object-cover" />
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Details Section - Right Column */}
                    <div className="flex-1 flex flex-col h-full min-h-0 overflow-hidden">

                        {/* Scrollable Content Area */}
                        <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
                            {/* Header Info */}
                            <div className="mb-6">
                                {isSold && (
                                    <span className="inline-flex self-start text-sm font-bold text-red-400 bg-red-900/30 px-3 py-1 rounded border border-red-500/30 mb-3">
                                        SOLD
                                    </span>
                                )}

                                <h1 className="text-3xl md:text-4xl font-bold text-[var(--text-primary)] mb-2 leading-tight">
                                    {item.name}
                                </h1>

                                <p className="text-3xl font-bold text-[var(--accent)]">
                                    RM {item.price}
                                </p>
                            </div>

                            {/* Condition */}
                            <div className="mb-6">
                                <h2 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide mb-2">Condition</h2>
                                <span className="inline-flex text-sm text-[var(--text-secondary)] bg-[var(--bg-tertiary)] px-4 py-2 rounded-full border border-[var(--border)]">
                                    {item.condition}
                                </span>
                            </div>

                            {/* Description */}
                            <div className="mb-8">
                                <h2 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide mb-2">Description</h2>
                                <p className="text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">
                                    {item.description}
                                </p>
                            </div>
                        </div>

                        {/* Fixed Bottom Action Bar */}
                        {!isSold && (
                            <div className="flex-shrink-0 pt-4 mt-2 border-t border-[var(--border)]">
                                <div className="flex items-stretch gap-4 h-14 transition-all duration-500 ease-out">
                                    {/* Chat with AI */}
                                    <div
                                        className={`
                                            flex items-center justify-center cursor-pointer group/link relative transition-all duration-500 ease-out overflow-hidden
                                            ${hoveredSection === 'buy' ? 'flex-[0] opacity-0 w-0 p-0' : 'flex-[1] opacity-100'}
                                        `}
                                        onMouseEnter={() => setHoveredSection('chat')}
                                        onMouseLeave={() => setHoveredSection(null)}
                                        onClick={() => onChat(item.id, item.name)}
                                    >
                                        <span className={`
                                            text-[var(--text-primary)] text-lg font-medium relative z-10 whitespace-nowrap
                                            transition-all duration-300
                                        `}>
                                            <GlitchText
                                                text="Chat"
                                                hoverText="Nego"
                                                forceHover={hoveredSection === 'chat'}
                                            />&nbsp;with AI
                                        </span>
                                        {/* Underline - White */}
                                        <span className="absolute left-0 bottom-2 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover/link:w-full" />
                                    </div>

                                    {/* Buy Now / Pay with Stripe */}
                                    <button
                                        disabled={isBuying}
                                        className={`
                                            relative overflow-hidden rounded-xl font-medium transition-all duration-500 ease-out cursor-pointer
                                            bg-[var(--btn-filled-bg)] text-[var(--btn-filled-text)] hover:brightness-110 shadow-lg shadow-[var(--btn-filled-bg)]/20 border border-[var(--border)]
                                            ${isBuying || hoveredSection === 'buy' ? 'flex-[1] w-full' : 'flex-[0.4]'}
                                        `}
                                        style={{}}
                                        onMouseEnter={() => !isBuying && setHoveredSection('buy')}
                                        onMouseLeave={() => !isBuying && setHoveredSection(null)}
                                        onClick={() => {
                                            setIsBuying(true)
                                            onBuy(item.id)
                                        }}
                                    >
                                        {isBuying ? (
                                            <div className="flex items-center justify-center w-full h-full">
                                                <div className="w-5 h-5 border-2 border-[var(--btn-filled-text)] border-t-transparent rounded-full animate-spin" />
                                            </div>
                                        ) : (
                                            <span className="whitespace-nowrap flex items-center justify-center w-full px-4 gap-1.5">
                                                <GlitchText
                                                    text="Buy Now"
                                                    hoverText="Pay with"
                                                    forceHover={hoveredSection === 'buy'}
                                                />
                                                <span className={`
                                                text-[#635BFF] font-semibold text-lg tracking-tight
                                                transition-all duration-500 ease-out
                                                ${hoveredSection === 'buy' ? 'opacity-100 max-w-[100px] translate-x-0' : 'opacity-0 max-w-0 -translate-x-4 overflow-hidden'}
                                            `}>
                                                    stripe
                                                </span>
                                            </span>
                                        )}
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </main>
        </div>
    )
}

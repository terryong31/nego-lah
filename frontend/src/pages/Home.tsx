import { useState, useEffect, useRef } from 'react'
import { ItemCard } from '../components/ItemCard'
import { ItemDetail } from './ItemDetail'
import { Button } from '../components/Button'
import { ConfirmationModal } from '../components/ConfirmationModal'
import { useItems } from '../hooks/useItems'
import { ThemeToggle, useTheme } from '../components/ThemeToggle'

interface HomeProps {
    onChat: (itemId: string, itemName?: string) => void
    onLogin: () => void
    onOpenProfile: () => void
    isAuthenticated: boolean
    onLogout: () => void
    userAvatar?: string
    userName?: string
    hasUnreadMessages?: boolean
}

// Import carousel images from assets
import bicycleImg from '../assets/bicycle.jpg'
import carImg from '../assets/car.jpg'
import focusriteImg from '../assets/focusrite.jpg'
import guitarImg from '../assets/guitar.jpg'
import laptopImg from '../assets/laptop.jpg'
import motorImg from '../assets/motor.jpeg'
import skateboardImg from '../assets/skateboard.jpeg'
import sofaImg from '../assets/sofa.jpg'
import speakersImg from '../assets/speakers.jpg'
import tvImg from '../assets/tv.jpeg'

const carouselItems = [
    bicycleImg,
    carImg,
    focusriteImg,
    guitarImg,
    laptopImg,
    motorImg,
    skateboardImg,
    sofaImg,
    speakersImg,
    tvImg
]

export function Home({ onChat, onLogin, onOpenProfile, isAuthenticated, onLogout, userAvatar, userName, hasUnreadMessages }: HomeProps) {
    const { items, isLoading, error, fetchItems, getCheckoutUrl } = useItems()
    const { theme, toggleTheme } = useTheme()
    const [searchExpanded, setSearchExpanded] = useState(false)
    const [searchQuery, setSearchQuery] = useState('')
    const [isScrolledToItems, setIsScrolledToItems] = useState(false)
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
    const [profileMenuOpen, setProfileMenuOpen] = useState(false)
    const [selectedItem, setSelectedItem] = useState<typeof items[0] | null>(null)
    const itemsSectionRef = useRef<HTMLDivElement>(null)
    const searchInputRef = useRef<HTMLInputElement>(null)
    const searchContainerRef = useRef<HTMLDivElement>(null)
    const trackRef = useRef<HTMLUListElement>(null)
    const profileMenuRef = useRef<HTMLDivElement>(null)

    // Handle click outside profile menu
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (profileMenuRef.current && !profileMenuRef.current.contains(event.target as Node)) {
                setProfileMenuOpen(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => {
            document.removeEventListener('mousedown', handleClickOutside)
        }
    }, [])

    // Logout Modal State
    const [showLogoutConfirm, setShowLogoutConfirm] = useState(false)
    const [isLoggingOut, setIsLoggingOut] = useState(false)
    const [buyingItemId, setBuyingItemId] = useState<string | null>(null)

    // Track scroll position to auto-expand search when at items section
    useEffect(() => {
        const handleScroll = () => {
            if (itemsSectionRef.current) {
                const rect = itemsSectionRef.current.getBoundingClientRect()
                const shouldExpand = rect.top <= 100
                setIsScrolledToItems(shouldExpand)
                if (shouldExpand) {
                    setSearchExpanded(true)
                } else if (!searchInputRef.current?.matches(':focus')) {
                    setSearchExpanded(false)
                }
            }
        }
        window.addEventListener('scroll', handleScroll)
        return () => window.removeEventListener('scroll', handleScroll)
    }, [])

    // Handle click outside to collapse search
    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (!isScrolledToItems && searchContainerRef.current && !searchContainerRef.current.contains(e.target as Node)) {
                setSearchExpanded(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [isScrolledToItems])

    // Auto-scroll carousel with infinite loop
    useEffect(() => {
        const track = trackRef.current
        if (!track) return

        let animationId: number
        let lastTime = 0
        const scrollSpeed = 0.06 // pixels per ms

        // We assume 3 sets of items.
        // We want to keep the scroll position within the middle set (Set 2).
        // Range: [Start of Set 2, Start of Set 3)
        // If < Start of Set 2 -> Jump to corresponding pos in Set 3 (actually, Jump Forward by SetWidth).
        // If >= Start of Set 3 -> Jump to corresponding pos in Set 2 (Jump Backward by SetWidth).
        // To seamlessly loop, we need to know the width of one set.

        let singleSetWidth = 0

        const updateDimensions = () => {
            if (!track || track.children.length < 20) return // Need at least 2 sets to measure diff
            // Distance between Start of Set 2 (index 10) and Start of Set 1 (index 0)
            const firstItem = track.children[0] as HTMLElement
            const secondSetFirstItem = track.children[10] as HTMLElement

            if (firstItem && secondSetFirstItem) {
                singleSetWidth = secondSetFirstItem.offsetLeft - firstItem.offsetLeft
            }
        }

        // Initialize measuring
        updateDimensions()

        // Start in the middle set if near 0 (initial load)
        if (track.scrollLeft < 100 && singleSetWidth > 0) {
            track.scrollLeft = singleSetWidth
        }

        const animate = (currentTime: number) => {
            if (lastTime !== 0) {
                const delta = currentTime - lastTime
                track.scrollLeft += scrollSpeed * delta
            }
            lastTime = currentTime

            // Check boundaries
            if (singleSetWidth > 0) {
                // Forward loop: If we reach start of Set 3 (2 * W), jump back to Set 2 (1 * W)
                // We add a small buffer or check >= 2*W. Actually offsetLeft of Set 3 is 2*singleSetWidth relative to Set 1.
                // Let's use flexible logic:

                // If scrolled past Set 2 (entering Set 3)
                if (track.scrollLeft >= singleSetWidth * 2) {
                    track.scrollLeft -= singleSetWidth
                }
                // If scrolled before Set 2 (entering Set 1) - effectively scrolling backwards
                else if (track.scrollLeft < singleSetWidth) {
                    track.scrollLeft += singleSetWidth
                }
            } else {
                updateDimensions()
            }

            animationId = requestAnimationFrame(animate)
        }

        animationId = requestAnimationFrame(animate)
        window.addEventListener('resize', updateDimensions)

        return () => {
            cancelAnimationFrame(animationId)
            window.removeEventListener('resize', updateDimensions)
        }
    }, [selectedItem])

    const handleBuy = async (itemId: string) => {
        setBuyingItemId(itemId)
        try {
            const url = await getCheckoutUrl(itemId)
            if (url) {
                window.location.href = url
            } else {
                setBuyingItemId(null)
            }
        } catch {
            setBuyingItemId(null)
        }
    }

    const handleSearchClick = () => {
        setSearchExpanded(true)
        setTimeout(() => searchInputRef.current?.focus(), 100)
    }

    // Filter items based on search
    const filteredItems = items.filter(item =>
        item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.description?.toLowerCase().includes(searchQuery.toLowerCase())
    )

    // Limit items for non-authenticated users
    const displayItems = isAuthenticated ? filteredItems : filteredItems.slice(0, 3)

    // If an item is selected, show the detail page
    if (selectedItem) {
        return (
            <ItemDetail
                item={selectedItem}
                onBack={() => {
                    if (document.startViewTransition) {
                        document.documentElement.classList.add('back-transition')
                        const transition = document.startViewTransition(() => {
                            setSelectedItem(null)
                        })
                        transition.finished.finally(() => {
                            document.documentElement.classList.remove('back-transition')
                        })
                    } else {
                        setSelectedItem(null)
                    }
                }}
                onChat={onChat}
                onBuy={handleBuy}
            />
        )
    }

    return (
        <div className="min-h-screen relative flex flex-col">
            {/* Stars Background */}
            <div className="stars-container">
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="stars"></div>
            </div>

            {/* Header */}
            <header className="liquid-glass-header sticky top-0 z-50">
                <div className="max-w-6xl mx-auto px-6 md:px-4 py-4 flex items-center justify-between">
                    <a href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
                        <img src="/logo.png" alt="Logo" className="w-8 h-8 object-contain" />
                        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Nego-lah</h1>
                    </a>

                    {/* Desktop Navigation */}
                    <div className="hidden md:flex items-center gap-4">
                        {/* Search Bar */}
                        <div
                            ref={searchContainerRef}
                            className={`flex items-center transition-all duration-300 ease-in-out overflow-hidden rounded-lg ${searchExpanded
                                ? 'w-56 bg-[var(--bg-tertiary)]'
                                : 'w-9 bg-transparent'
                                }`}
                        >
                            <button
                                onClick={handleSearchClick}
                                className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors flex-shrink-0 cursor-pointer"
                                aria-label="Search"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <circle cx="11" cy="11" r="8" />
                                    <path d="m21 21-4.35-4.35" />
                                </svg>
                            </button>
                            <input
                                ref={searchInputRef}
                                type="text"
                                placeholder="Search items..."
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                className={`bg-transparent border-none outline-none text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-all duration-300 min-w-0 ${searchExpanded ? 'flex-1 pr-3 opacity-100' : 'w-0 opacity-0'
                                    }`}
                            />
                        </div>



                        {isAuthenticated && (
                            <button
                                onClick={() => onChat('general')}
                                className="relative p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
                                aria-label="Chat"
                            >
                                {/* Notification dot for unread messages */}
                                {hasUnreadMessages && (
                                    <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-red-500 rounded-full animate-pulse" />
                                )}
                                {/* Round chat bubble with tail facing right */}
                                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
                                </svg>
                            </button>
                        )}

                        {isAuthenticated ? (
                            <div className="relative" ref={profileMenuRef}>
                                <button
                                    onClick={() => setProfileMenuOpen(!profileMenuOpen)}
                                    className="focus:outline-none flex items-center gap-3 hover:opacity-80 transition-opacity"
                                >
                                    {userAvatar ? (
                                        <img
                                            src={userAvatar}
                                            alt="Profile"
                                            className="w-8 h-8 rounded-full object-cover"
                                        />
                                    ) : (
                                        <div className="w-8 h-8 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center text-sm font-medium text-[var(--text-secondary)]">
                                            {(userName || 'U').charAt(0).toUpperCase()}
                                        </div>
                                    )}
                                    <div className="hidden md:flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]">
                                        <span>Hello, {userName?.split(' ')[0]}</span>
                                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`text-[var(--text-secondary)] transition-transform duration-200 ${profileMenuOpen ? 'rotate-180' : ''}`}>
                                            <path d="m6 9 6 6 6-6" />
                                        </svg>
                                    </div>
                                </button>

                                {/* Profile Dropdown Menu */}
                                {profileMenuOpen && (
                                    <div className="absolute right-0 mt-2 w-56 rounded-2xl shadow-xl z-50 py-2 animate-fade-in liquid-glass-menu border border-white/20">
                                        <button
                                            onClick={() => {
                                                setProfileMenuOpen(false)
                                                onOpenProfile()
                                            }}
                                            className="w-full px-4 py-2 text-left text-sm text-[var(--text-primary)] hover:bg-gray-200 dark:hover:bg-white/10 transition-colors cursor-pointer"
                                        >
                                            Profile
                                        </button>

                                        {/* Theme Toggle in Dropdown */}
                                        <button
                                            onClick={() => {
                                                if (document.startViewTransition) {
                                                    document.documentElement.classList.add('theme-transition')
                                                    const transition = document.startViewTransition(toggleTheme)
                                                    transition.finished.finally(() => {
                                                        document.documentElement.classList.remove('theme-transition')
                                                    })
                                                } else {
                                                    toggleTheme()
                                                }
                                            }}
                                            className="w-full px-4 py-2 text-left text-sm text-[var(--text-primary)] hover:bg-gray-200 dark:hover:bg-white/10 transition-colors flex justify-between items-center cursor-pointer"
                                        >
                                            <span>Theme</span>
                                            <span className="text-xs opacity-75">{theme === 'light' ? 'Light' : 'Dark'}</span>
                                        </button>

                                        <a
                                            href="/orders"
                                            className="block w-full px-4 py-2 text-left text-sm text-[var(--text-primary)] hover:bg-gray-200 dark:hover:bg-white/10 transition-colors cursor-pointer"
                                        >
                                            My Orders
                                        </a>
                                        <div className="h-px bg-[var(--border)] my-1 mx-2"></div>
                                        <button
                                            onClick={() => {
                                                setProfileMenuOpen(false)
                                                setShowLogoutConfirm(true)
                                            }}
                                            className="w-full px-4 py-2 text-left text-sm text-red-500 hover:bg-red-100 dark:hover:bg-red-900/20 transition-colors cursor-pointer"
                                        >
                                            Logout
                                        </button>
                                    </div>

                                )}
                            </div>
                        ) : (
                            <>
                                {/* Theme toggle for non-authenticated users */}
                                <ThemeToggle className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]" />
                                <Button variant="primary" size="sm" onClick={onLogin}>
                                    Login
                                </Button>
                            </>
                        )}
                    </div>

                    {/* Mobile Navigation - Hamburger only */}
                    <div className="flex md:hidden items-center gap-1">
                        {/* Hamburger menu */}
                        <button
                            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                            className={`p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all duration-300 ${mobileMenuOpen ? 'rotate-180' : ''}`}
                            aria-label="Menu"
                        >
                            {mobileMenuOpen ? (
                                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M6 9l6 6 6-6" />
                                </svg>
                            ) : (
                                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <line x1="3" y1="12" x2="21" y2="12" />
                                    <line x1="3" y1="6" x2="21" y2="6" />
                                    <line x1="3" y1="18" x2="21" y2="18" />
                                </svg>
                            )}
                        </button>
                    </div>
                </div >

                {/* Mobile Menu Dropdown - Slide down animation */}
                < div className={`md:hidden overflow-hidden transition-all duration-300 ease-out ${mobileMenuOpen ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'}`
                }>
                    <div className="border-t border-[var(--border)] bg-[var(--header-bg)] backdrop-blur-sm px-4 py-4 space-y-3">
                        {/* Mobile Search */}
                        <div className="relative">
                            <input
                                type="text"
                                placeholder="Search items..."
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                className="w-full px-4 py-2.5 bg-[var(--bg-tertiary)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none"
                            />
                            <svg className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <circle cx="11" cy="11" r="8" />
                                <path d="m21 21-4.35-4.35" />
                            </svg>
                        </div>

                        {/* Theme Toggle Row - Clickable div */}
                        <button
                            onClick={() => {
                                if (document.startViewTransition) {
                                    document.documentElement.classList.add('theme-transition')
                                    const transition = document.startViewTransition(toggleTheme)
                                    transition.finished.finally(() => {
                                        document.documentElement.classList.remove('theme-transition')
                                        // Force re-render by closing and reopening menu state
                                        setMobileMenuOpen(false)
                                        setTimeout(() => setMobileMenuOpen(true), 10)
                                    })
                                } else {
                                    // Fallback with CSS animation
                                    document.documentElement.classList.add('theme-transition-fallback')
                                    toggleTheme()
                                    setTimeout(() => {
                                        document.documentElement.classList.remove('theme-transition-fallback')
                                    }, 500)
                                    // Force re-render by closing and reopening menu state
                                    setMobileMenuOpen(false)
                                    setTimeout(() => setMobileMenuOpen(true), 10)
                                }
                            }}
                            className="flex items-center justify-between w-full py-2.5 px-3 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                        >
                            <span className="text-base font-medium text-[var(--text-primary)]">Theme</span>
                            <span className="text-sm text-[var(--text-secondary)]">
                                {theme === 'light' ? 'Light' : 'Dark'}
                            </span>
                        </button>

                        {/* Auth Section */}
                        {isAuthenticated ? (
                            <>
                                {/* Chat button in menu for mobile */}
                                <button
                                    onClick={() => { onChat('general'); setMobileMenuOpen(false); }}
                                    className="flex items-center justify-between w-full py-2.5 px-3 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                                >
                                    <span className="text-base font-medium text-[var(--text-primary)] flex items-center gap-2">
                                        Chat
                                        {hasUnreadMessages && (
                                            <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                                        )}
                                    </span>
                                </button>
                                <a
                                    href="/orders"
                                    onClick={() => setMobileMenuOpen(false)}
                                    className="flex items-center justify-between w-full py-2.5 px-3 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                                >
                                    <span className="text-base font-medium text-[var(--text-primary)]">Orders</span>
                                </a>
                                <button
                                    onClick={() => { onOpenProfile(); setMobileMenuOpen(false); }}
                                    className="flex items-center justify-between w-full py-2.5 px-3 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                                >
                                    <span className="text-base font-medium text-[var(--text-primary)]">Profile</span>
                                </button>
                                <button
                                    onClick={() => { setShowLogoutConfirm(true); setMobileMenuOpen(false); }}
                                    className="flex items-center justify-between w-full py-2.5 px-3 rounded-lg hover:bg-red-500/10 transition-colors"
                                >
                                    <span className="text-base font-medium text-red-500">Logout</span>
                                </button>
                            </>
                        ) : (
                            <Button variant="primary" fullWidth onClick={() => { onLogin(); setMobileMenuOpen(false); }}>
                                Login
                            </Button>
                        )}
                    </div>
                </div >
            </header >

            {/* Hero Section */}
            < section className="relative z-10 py-16 md:py-20" >
                <div className="max-w-6xl mx-auto px-4 flex flex-col lg:flex-row items-center gap-8 lg:gap-16">
                    {/* Left: Hero Text */}
                    <div className="flex-1 text-center lg:text-left">
                        <h2 className="text-3xl md:text-5xl lg:text-6xl font-bold mb-6 tracking-tight">
                            <span className="text-gradient-barang">
                                'Barang Cun'
                            </span>
                            <br />
                            <span className="text-[var(--text-primary)]">
                                Nego Sampai Jadi!
                            </span>
                        </h2>
                        <p className="text-base md:text-lg text-[var(--text-secondary)] max-w-xl mb-6 leading-relaxed">
                            Quality pre-loved items looking for new owner. Why pay retail when can nego?
                            Chat with our AI to get the 'best price‘
                        </p>
                        <div className="flex flex-wrap justify-center lg:justify-start gap-4">
                            {/* Powered by Stripe badge */}
                            <div className="flex items-center gap-2">
                                <span className="text-[var(--text-muted)] text-sm">Powered by</span>
                                <span className="text-[#635BFF] font-semibold text-lg tracking-tight">stripe</span>
                            </div>
                        </div>
                    </div>

                    {/* Right: Horizontal Slider */}
                    <div className="flex-1 w-full lg:w-auto flex justify-center">
                        <div className="track-wrapper">
                            <ul className="track" ref={trackRef}>
                                {/* Render 3 sets for seamless infinite scroll */}
                                {[...carouselItems, ...carouselItems, ...carouselItems].map((src, index) => (
                                    <li key={index} className="track__item">
                                        <img src={src} alt="" />
                                    </li>
                                ))}

                            </ul>
                        </div>
                    </div>
                </div>
            </section >

            {/* Featured Items Section */}
            < div ref={itemsSectionRef} className="relative z-10" >
                <div className="max-w-6xl mx-auto px-4">
                    <div className="flex items-center gap-4 mb-8">
                        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-[var(--border)] to-transparent"></div>
                        <h3 className="text-lg font-semibold text-[var(--text-primary)] whitespace-nowrap">
                            Featured Items
                        </h3>
                        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-[var(--border)] to-transparent"></div>
                    </div>
                </div>

                {/* Main Content */}
                <main className="max-w-6xl mx-auto px-6 md:px-4 pb-8">
                    {/* Loading State */}
                    {isLoading && (
                        <div className="flex items-center justify-center py-16">
                            <div className="w-6 h-6 border-2 border-zinc-700 border-t-white rounded-full animate-spin" />
                        </div>
                    )}

                    {/* Error State */}
                    {error && (
                        <div className="text-center py-16">
                            <p className="text-zinc-500 mb-4">{error}</p>
                            <Button variant="secondary" onClick={() => fetchItems()}>
                                Try Again
                            </Button>
                        </div>
                    )}

                    {/* Empty State */}
                    {!isLoading && !error && filteredItems.length === 0 && (
                        <div className="text-center py-16">
                            <p className="text-zinc-500">
                                {searchQuery ? 'No items found matching your search' : 'No items available'}
                            </p>
                        </div>
                    )}

                    {/* Items Grid - Fixed animation by using opacity-0 initially */}
                    {!isLoading && !error && displayItems.length > 0 && (
                        <>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6">
                                {displayItems.map((item, index) => (
                                    <div
                                        key={item.id}
                                        className="opacity-0 animate-slide-up-fade"
                                        style={{
                                            animationDelay: `${index * 0.05}s`,
                                            animationFillMode: 'forwards'
                                        }}
                                    >
                                        <ItemCard
                                            item={item}
                                            onClick={() => {
                                                if (isAuthenticated) {
                                                    if (document.startViewTransition) {
                                                        document.startViewTransition(() => {
                                                            setSelectedItem(item)
                                                        })
                                                    } else {
                                                        setSelectedItem(item)
                                                    }
                                                } else {
                                                    onLogin()
                                                }
                                            }}
                                            onBuy={(itemId) => {
                                                if (isAuthenticated) {
                                                    handleBuy(itemId)
                                                } else {
                                                    onLogin()
                                                }
                                            }}
                                            isBuying={buyingItemId === item.id}
                                        />
                                    </div>
                                ))}
                            </div>

                            {/* Login to see more prompt for non-authenticated users */}
                            {!isAuthenticated && filteredItems.length > 3 && (
                                <div className="text-center py-8 mt-4 border-t border-[var(--border)]">
                                    <p className="text-[var(--text-secondary)] mb-4">Login to see {filteredItems.length - 3} more items</p>
                                    <Button variant="filled" onClick={onLogin}>
                                        Login to See More
                                    </Button>
                                </div>
                            )}
                        </>
                    )}
                </main>
            </div >

            {/* Footer - Sticky to bottom */}
            < footer className="border-t border-[var(--border)] py-6 relative z-10 mt-auto" >
                <div className="max-w-6xl mx-auto px-6 flex justify-between items-center text-sm text-[var(--text-muted)]">
                    <p>
                        &copy; Nego-lah {new Date().getFullYear()}
                    </p>
                    <div className="flex gap-4">
                        <a href="/privacy" className="relative group/link cursor-pointer hover:text-[var(--text-primary)] transition-colors">
                            Privacy
                            <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover/link:w-full" />
                        </a>
                        <span>•</span>
                        <a href="/terms" className="relative group/link cursor-pointer hover:text-[var(--text-primary)] transition-colors">
                            Terms
                            <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover/link:w-full" />
                        </a>
                        <span>•</span>
                        <a href="/about" className="relative group/link cursor-pointer hover:text-[var(--text-primary)] transition-colors">
                            About
                            <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover/link:w-full" />
                        </a>
                    </div>
                </div>
            </footer >
            {/* Logout Confirmation Modal */}
            < ConfirmationModal
                isOpen={showLogoutConfirm}
                onClose={() => setShowLogoutConfirm(false)}
                onConfirm={() => {
                    setIsLoggingOut(true)
                    setTimeout(() => {
                        onLogout()
                        setShowLogoutConfirm(false)
                        setIsLoggingOut(false)
                    }, 800)
                }}
                title="Confirm Logout"
                message="Are you sure you want to log out?"
                isLoading={isLoggingOut}
                confirmText="Yes"
                cancelText="No"
            />
        </div >
    )
}

import { useState, useEffect, useRef } from 'react'
import { ItemCard } from '../components/ItemCard'
import { ItemDetail } from './ItemDetail'
import { Button } from '../components/Button'
import { ThemeToggle } from '../components/ThemeToggle'
import { useItems } from '../hooks/useItems'

interface HomeProps {
    onChat: (itemId: string, itemName?: string) => void
    onLogin: () => void
    onOpenProfile: () => void
    isAuthenticated: boolean
    onLogout: () => void
    userAvatar?: string
}

export function Home({ onChat, onLogin, onOpenProfile, isAuthenticated, onLogout, userAvatar }: HomeProps) {
    const { items, isLoading, error, fetchItems, getCheckoutUrl } = useItems()
    const [searchExpanded, setSearchExpanded] = useState(false)
    const [searchQuery, setSearchQuery] = useState('')
    const [isScrolledToItems, setIsScrolledToItems] = useState(false)
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
    const [profileMenuOpen, setProfileMenuOpen] = useState(false)
    const [selectedItem, setSelectedItem] = useState<typeof items[0] | null>(null)
    const itemsSectionRef = useRef<HTMLDivElement>(null)
    const searchInputRef = useRef<HTMLInputElement>(null)
    const searchContainerRef = useRef<HTMLDivElement>(null)

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

    const handleBuy = async (itemId: string) => {
        const url = await getCheckoutUrl(itemId)
        if (url) {
            window.location.href = url
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
                onBack={() => setSelectedItem(null)}
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
            <header className="border-b border-[var(--border)] bg-[var(--header-bg)] backdrop-blur-sm sticky top-0 z-20 relative">
                <div className="max-w-6xl mx-auto px-6 md:px-4 py-4 flex items-center justify-between">
                    <h1 className="text-xl font-semibold text-[var(--text-primary)]">Nego-Lah</h1>

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
                                className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors flex-shrink-0"
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

                        {/* Orders Icon - Only show when authenticated */}
                        {isAuthenticated && (
                            <a
                                href="/orders"
                                className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                                aria-label="My Orders"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z" />
                                    <path d="M3 6h18" />
                                    <path d="M16 10a4 4 0 0 1-8 0" />
                                </svg>
                            </a>
                        )}

                        <ThemeToggle className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]" />

                        {isAuthenticated ? (
                            <div className="relative">
                                <button
                                    onClick={() => setProfileMenuOpen(!profileMenuOpen)}
                                    className="focus:outline-none rounded-full"
                                >
                                    {userAvatar ? (
                                        <img
                                            src={userAvatar}
                                            alt="Profile"
                                            className="w-8 h-8 rounded-full object-cover hover:opacity-80 transition-opacity cursor-pointer"
                                        />
                                    ) : (
                                        <div className="w-8 h-8 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center text-sm font-medium text-[var(--text-secondary)] hover:opacity-80 transition-opacity cursor-pointer">
                                            U
                                        </div>
                                    )}
                                </button>

                                {/* Profile Dropdown Menu */}
                                {profileMenuOpen && (
                                    <>
                                        {/* Backdrop to close menu */}
                                        <div
                                            className="fixed inset-0 z-40"
                                            onClick={() => setProfileMenuOpen(false)}
                                        />
                                        <div className="absolute right-0 mt-2 w-40 bg-[var(--card-bg)] backdrop-blur-md border border-[var(--border)] rounded-xl shadow-lg z-50 py-2 animate-fade-in">
                                            <button
                                                onClick={() => {
                                                    setProfileMenuOpen(false)
                                                    onOpenProfile()
                                                }}
                                                className="w-full px-4 py-2 text-left text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
                                            >
                                                Profile
                                            </button>
                                            <button
                                                onClick={() => {
                                                    setProfileMenuOpen(false)
                                                    onLogout()
                                                }}
                                                className="w-full px-4 py-2 text-left text-sm text-red-500 hover:bg-[var(--bg-tertiary)] transition-colors"
                                            >
                                                Logout
                                            </button>
                                        </div>
                                    </>
                                )}
                            </div>
                        ) : (
                            <Button variant="primary" size="sm" onClick={onLogin}>
                                Login
                            </Button>
                        )}
                    </div>

                    {/* Mobile Navigation - Only hamburger button */}
                    <div className="flex md:hidden items-center">
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
                </div>

                {/* Mobile Menu Dropdown - Slide down animation */}
                <div className={`md:hidden overflow-hidden transition-all duration-300 ease-out ${mobileMenuOpen ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'}`}>
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
                                const root = document.documentElement
                                const isDark = root.classList.contains('dark')
                                if (isDark) {
                                    root.classList.remove('dark')
                                    root.classList.add('light')
                                    localStorage.setItem('theme', 'light')
                                } else {
                                    root.classList.remove('light')
                                    root.classList.add('dark')
                                    localStorage.setItem('theme', 'dark')
                                }
                                // Force re-render by closing and reopening menu state
                                setMobileMenuOpen(false)
                                setTimeout(() => setMobileMenuOpen(true), 10)
                            }}
                            className="flex items-center justify-between w-full py-2.5 px-3 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                        >
                            <span className="text-base font-medium text-[var(--text-primary)]">Theme</span>
                            <span className="text-sm text-[var(--text-secondary)]">
                                {localStorage.getItem('theme') === 'light' ? 'Light' : 'Dark'}
                            </span>
                        </button>

                        {/* Auth Section */}
                        {isAuthenticated ? (
                            <>
                                <a
                                    href="/orders"
                                    onClick={() => setMobileMenuOpen(false)}
                                    className="flex items-center gap-2 w-full py-2.5 px-3 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                                >
                                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z" />
                                        <path d="M3 6h18" />
                                        <path d="M16 10a4 4 0 0 1-8 0" />
                                    </svg>
                                    <span className="text-base font-medium text-[var(--text-primary)]">My Orders</span>
                                </a>
                                <button
                                    onClick={() => { onOpenProfile(); setMobileMenuOpen(false); }}
                                    className="flex items-center justify-between w-full py-2.5 px-3 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                                >
                                    <span className="text-base font-medium text-[var(--text-primary)]">Profile</span>
                                </button>
                                <button
                                    onClick={() => { onLogout(); setMobileMenuOpen(false); }}
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
                </div>
            </header>

            {/* Hero Section */}
            <section className="relative z-10 py-12 md:py-20">
                <div className="max-w-6xl mx-auto px-4 flex flex-col lg:flex-row items-center gap-8 lg:gap-16">
                    {/* Left: Hero Text */}
                    <div className="flex-1 text-center lg:text-left">
                        <h2 className="text-3xl md:text-5xl lg:text-6xl font-bold mb-6 tracking-tight">
                            <span className="bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                                Discover Unique
                            </span>
                            <br />
                            <span className="text-[var(--text-primary)]">
                                Second-Hand Treasures
                            </span>
                        </h2>
                        <p className="text-base md:text-lg text-[var(--text-secondary)] max-w-xl mb-6 leading-relaxed">
                            Quality pre-owned items at unbeatable prices. Each piece tells a story —
                            find yours today and negotiate directly with my AI.
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
                            <ul className="track">
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1523437237164-d442d57cc3c9?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1421930866250-aa0594cea05c?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1536152470836-b943b246224c?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1491824989090-cc2d0b57eb0d?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1518717202715-9fa9d099f58a?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1507608869274-d3177c8bb4c7?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1459213599465-03ab6a4d5931?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1495107334309-fcf20504a5ab?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1453791052107-5c843da62d97?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                                <li className="track__item">
                                    <img src="https://images.unsplash.com/photo-1471978445661-ad6ec1f5ba50?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=300&w=300" alt="" />
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>
            </section>

            {/* Featured Items Section */}
            <div ref={itemsSectionRef} className="relative z-10">
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
                                                    setSelectedItem(item)
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
            </div>

            {/* Footer - Sticky to bottom */}
            <footer className="border-t border-[var(--border)] py-6 relative z-10 mt-auto">
                <p className="text-center text-sm text-[var(--text-muted)]">
                    Second Hand Store
                </p>
            </footer>
        </div>
    )
}

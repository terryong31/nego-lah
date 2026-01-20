
import { useState, useEffect, useRef } from 'react'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { Card } from '../components/Card'
import { ThemeToggle } from '../components/ThemeToggle'
import { ChatBubble } from '../components/ChatBubble'
import { ConfirmationModal } from '../components/ConfirmationModal'
import { api } from '../lib/api'
import { supabase } from '../lib/supabase'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
const CHATS_URL = `${API_URL}/admin/chats`

interface Item {
    id: string
    name: string
    description: string
    condition: string
    price: number
    min_price?: number
    status?: string
    image_path?: string
    images?: string[]
}

interface AdminProps {
    onBack: () => void
}

interface User { // Renamed from AdminUser
    id: string
    email: string
    display_name: string
    is_banned: boolean
    ai_enabled: boolean
    admin_intervening: boolean
    created_at: string
    avatar_url?: string // Added avatar_url
}

interface ChatMessage {
    role: string
    content: string
    source?: 'ai' | 'admin' | 'system' | 'human'
}

const Toggle = ({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) => (
    <button
        onClick={() => onChange(!checked)}
        className={`w-11 h-6 flex items-center rounded-full transition-colors duration-200 focus:outline-none ${checked ? 'bg-[var(--btn-filled-bg)]' : 'bg-gray-400'
            }`}
    >
        <span
            className={`block w-4 h-4 ml-1 rounded-full bg-[var(--btn-filled-text)] shadow-sm ring-1 ring-slate-900/5 transition duration-200 ease-in-out ${checked ? 'translate-x-5' : 'translate-x-0'
                }`}
        />
    </button>
)

export function Admin({ onBack }: AdminProps) {
    const [isLoggedIn, setIsLoggedIn] = useState(false)
    const [adminToken, setAdminToken] = useState<string | null>(localStorage.getItem('adminToken'))
    const [items, setItems] = useState<Item[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [editingItem, setEditingItem] = useState<Item | null>(null)
    const [showAddForm, setShowAddForm] = useState(false)
    const [isMenuOpen, setIsMenuOpen] = useState(false)


    // Login form
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [loginLoading, setLoginLoading] = useState(false)
    const [showLogoutConfirm, setShowLogoutConfirm] = useState(false)
    const [isLoggingOut, setIsLoggingOut] = useState(false)

    // Form state
    const [formData, setFormData] = useState({
        name: '',
        description: '',
        condition: 'Good',
        price: '',
        min_price: ''
    })
    const [images, setImages] = useState<FileList | null>(null)
    const [currentItemImages, setCurrentItemImages] = useState<string[]>([])

    // Tab state
    const [activeTab, setActiveTab] = useState<'items' | 'users' | 'orders'>('items')

    const [tabDirection, setTabDirection] = useState<'left' | 'right'>('right')
    const prevTabRef = useRef<'items' | 'users' | 'orders'>('items')

    // Sliding Underline Refs
    const itemsTabRef = useRef<HTMLButtonElement>(null)
    const usersTabRef = useRef<HTMLButtonElement>(null)
    const ordersTabRef = useRef<HTMLButtonElement>(null)
    const [underlineStyle, setUnderlineStyle] = useState({ left: 0, width: 0 })

    const updateUnderline = () => {
        const refs = {
            items: itemsTabRef,
            users: usersTabRef,
            orders: ordersTabRef
        }
        const currentRef = refs[activeTab]?.current
        if (currentRef) {
            setUnderlineStyle({
                left: currentRef.offsetLeft,
                width: currentRef.offsetWidth
            })
        }
    }

    useEffect(() => {
        updateUnderline()
        window.addEventListener('resize', updateUnderline)
        // Small timeout to ensure fonts/layout are stable
        const timer = setTimeout(updateUnderline, 50)
        return () => {
            window.removeEventListener('resize', updateUnderline)
            clearTimeout(timer)
        }
    }, [activeTab, isLoggedIn])


    // User management state
    const [users, setUsers] = useState<User[]>([]) // Changed to User[]
    const [usersLoading, setUsersLoading] = useState(false)
    const [selectedUserChat, setSelectedUserChat] = useState<{ userId: string, messages: ChatMessage[] } | null>(null)
    const [chatOffset, setChatOffset] = useState(0)
    const [hasMoreMessages, setHasMoreMessages] = useState(true)
    const [isLoadingHistory, setIsLoadingHistory] = useState(false)

    // Edit User State
    const [editingUser, setEditingUser] = useState<User | null>(null)
    const [editForm, setEditForm] = useState({ displayName: '', avatarUrl: '' })

    // Orders state
    interface AdminOrder {
        id: string
        item_id: string
        item_name: string
        item_image?: string
        original_price: number
        amount_paid: number
        buyer_email: string
        status: string
        created_at: string
    }
    const [orders, setOrders] = useState<AdminOrder[]>([])
    const [ordersSummary, setOrdersSummary] = useState<{ total_sales: number; total_transactions: number } | null>(null)
    const [ordersLoading, setOrdersLoading] = useState(false)

    const [adminReply, setAdminReply] = useState('')
    const messagesEndRef = useRef<HTMLDivElement>(null)

    // Confirmation Modal State
    const [confirmation, setConfirmation] = useState<{
        isOpen: boolean
        title: string
        message: string
        onConfirm: () => void
        isLoading?: boolean
    }>({
        isOpen: false,
        title: '',
        message: '',
        onConfirm: () => { }
    })

    // Check if already logged in
    useEffect(() => {
        if (adminToken) {
            verifyToken()
        }
    }, [])

    useEffect(() => {
        const order = { items: 0, users: 1, orders: 2 }
        const prev = order[prevTabRef.current]
        const curr = order[activeTab]
        if (curr > prev) {
            setTabDirection('left')
        } else {
            setTabDirection('right')
        }
        prevTabRef.current = activeTab
    }, [activeTab])



    const verifyToken = async () => {
        try {
            const res = await fetch(`${API_URL}/admin/verify?token=${adminToken}`)
            const data = await res.json()
            if (data.valid) {
                setIsLoggedIn(true)
                fetchItems()
            } else {
                localStorage.removeItem('adminToken')
                setAdminToken(null)
            }
        } catch {
            // Token invalid
        }
    }

    // Real-time Chat Logic
    const [isUserTyping, setIsUserTyping] = useState(false)
    const typingTimeoutRef = useRef<any>(null)

    useEffect(() => {
        if (selectedUserChat && messagesEndRef.current && (chatOffset === 0 || isUserTyping)) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
        }
    }, [selectedUserChat, chatOffset, isUserTyping])

    const sendTyping = async () => {
        if (!selectedUserChat) return
        await supabase.channel(`chat:${selectedUserChat.userId}`).send({
            type: 'broadcast',
            event: 'typing',
            payload: { source: 'admin' }
        })
    }

    useEffect(() => {
        if (!selectedUserChat) return

        const userId = selectedUserChat.userId
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
                    // Update messages
                    const newMessages = payload.new.messages
                    if (newMessages && Array.isArray(newMessages)) {
                        setSelectedUserChat(prev => {
                            if (!prev || prev.userId !== userId) return prev
                            return {
                                ...prev,
                                messages: newMessages
                            }
                        })
                    }
                }
            )
            .on(
                'broadcast',
                { event: 'typing' },
                (payload) => {
                    if (payload.payload.source === 'user') {
                        setIsUserTyping(true)
                        if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current)
                        typingTimeoutRef.current = setTimeout(() => setIsUserTyping(false), 3000)
                    }
                }
            )
            .on(
                'broadcast',
                { event: 'new_message' },
                (payload) => {
                    const msg = payload.payload
                    // Ignore own messages
                    if (msg.source === 'admin') return

                    setSelectedUserChat(prev => {
                        if (!prev || prev.userId !== userId) return prev

                        // Check if message already exists to avoid duplication
                        const lastMsg = prev.messages[prev.messages.length - 1]
                        if (lastMsg && lastMsg.content === msg.content && lastMsg.source === msg.source) {
                            return prev
                        }

                        return {
                            ...prev,
                            messages: [...prev.messages, {
                                role: msg.role,
                                content: msg.content,
                                source: msg.source,
                                timestamp: msg.timestamp || new Date().toISOString()
                            }]
                        }
                    })
                }
            )
            .subscribe()

        return () => {
            supabase.removeChannel(channel)
            if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current)
        }
    }, [selectedUserChat?.userId])

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault()
        setLoginLoading(true)
        setError(null)

        try {
            const res = await fetch(`${API_URL}/admin/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            })

            const data = await res.json()

            if (res.ok) {
                setAdminToken(data.token)
                localStorage.setItem('adminToken', data.token)
                setIsLoggedIn(true)
                fetchItems()
            } else {
                setError(data.detail || 'Login failed')
            }
        } catch {
            setError('Connection error')
        }
        setLoginLoading(false)
    }

    const handleLogoutClick = () => {
        setShowLogoutConfirm(true)
    }

    const confirmLogout = () => {
        setIsLoggingOut(true)
        // Simulate server request delay
        setTimeout(() => {
            localStorage.removeItem('adminToken')
            setAdminToken(null)
            setIsLoggedIn(false)
            setItems([])
            setIsLoggingOut(false)
            setShowLogoutConfirm(false)
        }, 800)
    }

    const fetchItems = async () => {
        setIsLoading(true)
        try {
            const res = await fetch(`${API_URL}/items`)
            if (res.ok) {
                const data = await res.json()
                setItems(data)
            }
        } catch {
            setError('Failed to load items')
        }
        setIsLoading(false)
    }

    const handleAdd = async (e: React.FormEvent) => {
        e.preventDefault()

        const form = new FormData()
        form.append('name', formData.name)
        form.append('description', formData.description)
        form.append('condition', formData.condition)
        form.append('price', formData.price)

        if (images) {
            Array.from(images).forEach(file => {
                form.append('images', file)
            })
        }

        try {
            const res = await fetch(`${API_URL}/items`, {
                method: 'POST',
                body: form
            })

            if (res.ok) {
                setShowAddForm(false)
                setFormData({ name: '', description: '', condition: 'Good', price: '', min_price: '' })
                setImages(null)
                fetchItems()
            } else {
                const data = await res.json()
                setError(data.detail || 'Failed to add item')
            }
        } catch {
            setError('Connection error')
        }
    }

    const handleDelete = (itemId: string) => {
        setConfirmation({
            isOpen: true,
            title: 'Delete Item',
            message: 'Are you sure you want to delete this item? This action cannot be undone.',
            onConfirm: () => performDeleteItem(itemId)
        })
    }

    const performDeleteItem = async (itemId: string) => {
        setConfirmation(prev => ({ ...prev, isLoading: true }))
        try {
            const res = await fetch(`${API_URL}/items`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_id: itemId, name: '', description: '', condition: '', images: '' })
            })

            if (res.ok) {
                fetchItems()
            }
        } catch {
            setError('Failed to delete')
        }
        setConfirmation(prev => ({ ...prev, isOpen: false, isLoading: false }))
    }

    const handleUpdate = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!editingItem) return

        try {
            const res = await fetch(`${API_URL}/items`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    item_id: editingItem.id,
                    name: formData.name,
                    description: formData.description,
                    condition: formData.condition,
                    price: formData.price ? parseFloat(formData.price) : null,
                    min_price: formData.min_price ? parseFloat(formData.min_price) : null,
                    images: ''
                })
            })

            if (res.ok) {
                setEditingItem(null)
                fetchItems()
            }
        } catch {
            setError('Failed to update')
        }
    }

    const startEdit = (item: Item) => {
        setEditingItem(item)

        // Parse images from image_path if present
        let images: string[] = []
        if (item.image_path) {
            try {
                const parsed = JSON.parse(item.image_path)
                images = Object.values(parsed)
            } catch { /* ignore */ }
        }
        setCurrentItemImages(images)

        setFormData({
            name: item.name,
            description: item.description,
            condition: item.condition,
            price: item.price.toString(),
            min_price: item.min_price?.toString() || ''
        })
    }

    const handleDeleteImage = (imageIndex: number) => {
        setConfirmation({
            isOpen: true,
            title: 'Delete Image',
            message: 'Are you sure you want to delete this image?',
            onConfirm: () => performDeleteImage(imageIndex)
        })
    }

    const performDeleteImage = async (imageIndex: number) => {
        if (!editingItem) return

        setConfirmation(prev => ({ ...prev, isLoading: true }))
        try {
            const res = await fetch(`${API_URL}/items/${editingItem.id}/images/${imageIndex}`, {
                method: 'DELETE'
            })

            if (res.ok) {
                const data = await res.json()
                setCurrentItemImages(data.remaining_images || [])
            } else {
                setError('Failed to delete image')
            }
        } catch {
            setError('Connection error')
        }
        setConfirmation(prev => ({ ...prev, isOpen: false, isLoading: false }))
    }

    const handleAddImages = async (files: FileList) => {
        if (!editingItem || !files.length) return

        const formData = new FormData()
        for (let i = 0; i < files.length; i++) {
            formData.append('images', files[i])
        }

        try {
            const res = await fetch(`${API_URL}/items/${editingItem.id}/images`, {
                method: 'POST',
                body: formData
            })

            if (res.ok) {
                const data = await res.json()
                setCurrentItemImages(data.images || [])
            } else {
                setError('Failed to add images')
            }
        } catch {
            setError('Connection error')
        }
    }

    // User Management Functions
    const fetchUsers = async () => {
        setUsersLoading(true)
        try {
            const res = await fetch(`${API_URL}/admin/users`)
            if (res.ok) {
                const data = await res.json()
                setUsers(data)
            }
        } catch {
            setError('Failed to fetch users')
        } finally {
            setUsersLoading(false)
        }
    }

    const fetchOrders = async () => {
        setOrdersLoading(true)
        try {
            const res = await fetch(`${API_URL}/admin/orders`)
            if (res.ok) {
                const data = await res.json()
                setOrders(data.orders || [])
                setOrdersSummary(data.summary || null)
            }
        } catch {
            setError('Failed to fetch orders')
        } finally {
            setOrdersLoading(false)
        }
    }

    const handleBanUser = async (userId: string, ban: boolean) => {
        try {
            const res = await fetch(`${API_URL}/admin/users/${userId}/ban`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_banned: ban })
            })
            if (res.ok) {
                fetchUsers()
            }
        } catch {
            setError('Failed to update user')
        }
    }

    const handleToggleAI = async (userId: string, enable: boolean) => {
        try {
            const res = await fetch(`${API_URL}/admin/users/${userId}/ai`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ai_enabled: enable })
            })
            if (res.ok) {
                fetchUsers()
            }
        } catch {
            setError('Failed to update AI setting')
        }
    }

    const fetchUserChat = async (userId: string, offset = 0) => {
        try {
            if (offset === 0) {
                setChatOffset(0)
                setHasMoreMessages(true)
            }
            setIsLoadingHistory(true)

            const response = await api.get(`${CHATS_URL}/${userId}?limit=10&offset=${offset}`)

            if (response.data.messages.length < 10) {
                setHasMoreMessages(false)
            }

            if (offset === 0) {
                setSelectedUserChat({ userId, messages: response.data.messages })
            } else {
                setSelectedUserChat(prev => {
                    if (!prev) return null
                    return {
                        ...prev,
                        messages: [...response.data.messages, ...prev.messages]
                    }
                })
            }
        } catch (error) {
            console.error('Failed to fetch chat:', error)
        } finally {
            setIsLoadingHistory(false)
        }
    }

    const [scrollState, setScrollState] = useState<{ height: number, top: number } | null>(null)
    const chatContainerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (scrollState && chatContainerRef.current) {
            const newHeight = chatContainerRef.current.scrollHeight
            const diff = newHeight - scrollState.height
            chatContainerRef.current.scrollTop = scrollState.top + diff
            setScrollState(null)
        }
    }, [selectedUserChat, scrollState])

    const loadMoreMessages = () => {
        if (!selectedUserChat || isLoadingHistory || !hasMoreMessages) return

        // Capture scroll state before loading
        if (chatContainerRef.current) {
            setScrollState({
                height: chatContainerRef.current.scrollHeight,
                top: chatContainerRef.current.scrollTop
            })
        }

        const newOffset = chatOffset + 10
        setChatOffset(newOffset)
        fetchUserChat(selectedUserChat.userId, newOffset)
    }

    const handleEditUser = (user: User) => {
        setEditingUser(user)
        setEditForm({
            displayName: user.display_name,
            avatarUrl: user.avatar_url || ''
        })
    }

    const handleAvatarUpload = async (files: FileList) => {
        if (!editingUser || !files.length) return

        const file = files[0]
        const formData = new FormData()
        formData.append('avatar', file)

        try {
            const res = await fetch(`${API_URL}/admin/users/${editingUser.id}/avatar`, {
                method: 'POST',
                body: formData
            })

            if (res.ok) {
                const data = await res.json()
                setEditForm(prev => ({ ...prev, avatarUrl: data.avatar_url }))
                // Update local user state immediately
                setUsers(prev => prev.map(u =>
                    u.id === editingUser.id
                        ? { ...u, avatar_url: data.avatar_url }
                        : u
                ))
            } else {
                setError('Failed to upload avatar')
            }
        } catch {
            setError('Connection error')
        }
    }

    const handleSaveProfile = async () => {
        if (!editingUser) return
        try {
            await api.put(`/admin/users/${editingUser.id}/profile`, {
                display_name: editForm.displayName,
                avatar_url: editForm.avatarUrl || null
            })
            // Refresh users
            await fetchUsers()
            setEditingUser(null)
        } catch (error) {
            console.error('Failed to update profile:', error)
        }
    }

    const handleSendAdminMessage = async () => {
        if (!selectedUserChat || !adminReply.trim()) return

        try {
            const res = await fetch(`${API_URL}/admin/chats/${selectedUserChat.userId}/message`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: adminReply })
            })
            if (res.ok) {
                setAdminReply('')
                fetchUserChat(selectedUserChat.userId)

                // Broadcast to user
                await supabase.channel(`chat:${selectedUserChat.userId}`).send({
                    type: 'broadcast',
                    event: 'new_message',
                    payload: {
                        role: 'ai', // Admin appears as 'ai' / 'assistant' in user chat typically, or 'admin' source
                        source: 'admin',
                        content: adminReply,
                        timestamp: new Date().toISOString()
                    }
                })
            }
        } catch {
            setError('Failed to send message')
        }
    }



    // Conditional Render
    if (!isLoggedIn) {
        return (
            <div className="min-h-screen flex items-center justify-center p-4" style={{ background: 'inherit' }}>
                {/* Stars Background */}
                <div className="stars-container">
                    <div className="shooting-star"></div>
                    <div className="shooting-star"></div>
                    <div className="shooting-star"></div>
                    <div className="stars"></div>
                </div>

                <div className="relative z-10 w-full max-w-sm animate-slide-up flex flex-col items-start">
                    {/* Back arrow with text */}
                    <button
                        onClick={onBack}
                        className="flex items-center gap-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group mb-4"
                        aria-label="Back to store"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                        <span className="text-sm font-medium relative">
                            Return to menu
                            <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover:w-full" />
                        </span>
                    </button>

                    <Card className="w-full backdrop-blur-sm shadow-xl">
                        <div className="mb-6 animate-fade-in">
                            <h1 className="text-xl font-semibold text-[var(--text-primary)]">Admin Login</h1>
                            <p className="text-sm text-[var(--text-secondary)] mt-1">Enter your credentials</p>
                        </div>

                        {error && (
                            <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
                                {error}
                            </div>
                        )}

                        <form onSubmit={handleLogin} className="space-y-4">
                            <div className="animate-slide-up" style={{ animationDelay: '0.1s' }}>
                                <Input
                                    type="text"
                                    label="Username"
                                    placeholder="Enter username"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    required
                                    disabled={loginLoading}
                                />
                            </div>

                            <div className="animate-slide-up" style={{ animationDelay: '0.2s' }}>
                                <Input
                                    type="password"
                                    label="Password"
                                    placeholder="Enter password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    disabled={loginLoading}
                                />
                            </div>

                            <div className="animate-slide-up pt-2" style={{ animationDelay: '0.3s' }}>
                                <Button
                                    type="submit"
                                    variant="filled"
                                    fullWidth
                                    disabled={loginLoading}
                                >
                                    {loginLoading ? 'Logging in...' : 'Login'}
                                </Button>
                            </div>
                        </form>
                    </Card>
                </div>
            </div>
        )
    }

    // Admin Dashboard
    return (
        <div className="min-h-screen transition-colors duration-300">
            <div className="stars-container">
                <div className="stars"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
            </div>

            {/* Header */}
            <header className="border-b border-[var(--border)] bg-[var(--header-bg)] backdrop-blur-sm sticky top-0 z-10 relative transition-colors duration-300">
                <div className="max-w-4xl mx-auto px-4 py-4 flex flex-wrap gap-4 items-center justify-between">
                    <div className="flex items-center gap-4">
                        <button
                            onClick={onBack}
                            className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                            aria-label="Back to store"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M19 12H5M12 19l-7-7 7-7" />
                            </svg>
                        </button>
                        <h1 className="text-xl font-semibold text-[var(--text-primary)] whitespace-nowrap">Admin Panel</h1>
                    </div>

                    {/* Desktop Actions */}
                    <div className="hidden md:flex gap-3 items-center ml-auto">
                        <ThemeToggle className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]" />
                        <Button variant="ghost" size="sm" onClick={handleLogoutClick}>
                            Logout
                        </Button>
                    </div>

                    {/* Mobile Hamburger */}
                    <button
                        className="md:hidden p-2 text-[var(--text-primary)]"
                        onClick={() => setIsMenuOpen(!isMenuOpen)}
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="3" y1="12" x2="21" y2="12"></line>
                            <line x1="3" y1="6" x2="21" y2="6"></line>
                            <line x1="3" y1="18" x2="21" y2="18"></line>
                        </svg>
                    </button>
                </div>

                {/* Mobile Menu Dropdown */}
                {isMenuOpen && (
                    <div className="md:hidden border-t border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-2 animate-slide-down">
                        <div className="flex items-center justify-between py-2">
                            <span className="text-sm text-[var(--text-primary)]">Theme</span>
                            <ThemeToggle />
                        </div>
                        <div className="py-2">
                            <div className="py-2">
                                <Button variant="ghost" size="sm" fullWidth onClick={handleLogoutClick}>
                                    Logout
                                </Button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Tab Navigation */}
                <div className="max-w-4xl mx-auto px-4">
                    {/* Sliding Underline Tabs */}
                    <div className="flex gap-4 border-b border-[var(--border)] relative">
                        <button
                            ref={itemsTabRef}
                            onClick={() => setActiveTab('items')}
                            className={`py-3 px-4 text-sm font-medium transition-colors relative ${activeTab === 'items'
                                ? 'text-[var(--text-primary)]'
                                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                                }`}
                        >
                            Items
                        </button>
                        <button
                            ref={usersTabRef}
                            onClick={() => { setActiveTab('users'); fetchUsers(); }}
                            className={`py-3 px-4 text-sm font-medium transition-colors relative ${activeTab === 'users'
                                ? 'text-[var(--text-primary)]'
                                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                                }`}
                        >
                            Users
                        </button>
                        <button
                            ref={ordersTabRef}
                            onClick={() => { setActiveTab('orders'); fetchOrders(); }}
                            className={`py-3 px-4 text-sm font-medium transition-colors relative ${activeTab === 'orders'
                                ? 'text-[var(--text-primary)]'
                                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                                }`}
                        >
                            Orders
                        </button>

                        {/* Floating Sliding Underline - Lavender/White */}
                        <div
                            className="absolute bottom-0 h-[2px] bg-[var(--btn-filled-bg)] transition-all duration-300 ease-in-out"
                            style={{ left: underlineStyle.left, width: underlineStyle.width }}
                        />
                    </div>
                </div>
            </header>

            <main className="max-w-4xl mx-auto px-4 py-8 relative z-10">
                {error && (
                    <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
                        {error}
                        <button onClick={() => setError(null)} className="ml-2 underline">Dismiss</button>
                    </div>
                )}

                {/* Items Tab Content */}
                {activeTab === 'items' && (
                    <div className={tabDirection === 'left' ? 'animate-slide-in-left' : 'animate-slide-in-right'}>
                        <div className="flex justify-end mb-4">
                            <button
                                onClick={() => setShowAddForm(true)}
                                className="flex items-center gap-2 py-2 px-4 text-sm font-medium text-[var(--text-primary)] hover:text-[var(--text-primary)] transition-colors group relative"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                                <span className="relative">
                                    Add New Item
                                    <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-current transition-all duration-300 group-hover:w-full" />
                                </span>
                            </button>
                        </div>

                        {/* Items Table */}
                        {isLoading ? (
                            <div className="flex justify-center py-16">
                                <div className="w-6 h-6 border-2 border-[var(--text-secondary)] border-t-[var(--text-primary)] rounded-full animate-spin" />
                            </div>
                        ) : items.length === 0 ? (
                            <p className="text-center text-[var(--text-muted)] py-16">No items found</p>
                        ) : (
                            <div className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-xl overflow-hidden backdrop-blur-sm">
                                <div className="overflow-x-auto">
                                    <table className="w-full min-w-[600px] text-left">
                                        <thead className="bg-[var(--header-bg)] border-b border-[var(--border)]">
                                            <tr>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">Image</th>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">Name</th>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">Price</th>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">Base</th>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">Status</th>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] text-right whitespace-nowrap">Actions</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-[var(--border)]">
                                            {items.map((item) => {
                                                let imageUrl = null
                                                if (item.image_path) {
                                                    try {
                                                        const parsed = JSON.parse(item.image_path)
                                                        imageUrl = Object.values(parsed)[0] as string
                                                    } catch { /* ignore */ }
                                                }
                                                return (
                                                    <tr key={item.id} className="hover:bg-[var(--header-bg)] transition-colors">
                                                        <td className="px-4 py-3">
                                                            <div className="w-12 h-12 rounded bg-[var(--bg-secondary)] overflow-hidden">
                                                                {imageUrl ? (
                                                                    <img src={imageUrl} alt={item.name} className="w-full h-full object-cover" />
                                                                ) : (
                                                                    <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)]">📷</div>
                                                                )}
                                                            </div>
                                                        </td>
                                                        <td className="px-4 py-3">
                                                            <span className="font-medium text-[var(--text-primary)]">{item.name}</span>
                                                        </td>
                                                        <td className="px-4 py-3 text-[var(--text-secondary)]">RM{item.price}</td>
                                                        <td className="px-4 py-3 text-[var(--text-muted)]">
                                                            {item.min_price ? `RM${item.min_price}` : '-'}
                                                        </td>
                                                        <td className="px-4 py-3">
                                                            <span className="px-2 py-1 text-xs rounded-full bg-green-600 text-white">
                                                                Available
                                                            </span>
                                                        </td>
                                                        <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                                                            <Button variant="ghost" size="sm" onClick={() => startEdit(item)}>
                                                                Edit
                                                            </Button>
                                                            <Button variant="danger" size="sm" onClick={() => handleDelete(item.id)}>
                                                                Delete
                                                            </Button>
                                                        </td>
                                                    </tr>
                                                )
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* Users Table */}
                {activeTab === 'users' && (
                    <div className={tabDirection === 'left' ? 'animate-slide-in-left' : 'animate-slide-in-right'}>
                        {usersLoading ? (
                            <div className="flex justify-center py-16">
                                <div className="w-6 h-6 border-2 border-[var(--text-secondary)] border-t-[var(--text-primary)] rounded-full animate-spin" />
                            </div>
                        ) : users.length === 0 ? (
                            <p className="text-center text-[var(--text-muted)] py-16">No users found</p>
                        ) : (
                            <div className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-xl overflow-hidden backdrop-blur-sm">
                                <div className="overflow-x-auto">
                                    <table className="w-full min-w-[600px] text-left">
                                        <thead className="bg-[var(--header-bg)] border-b border-[var(--border)]">
                                            <tr>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">User</th>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">Status</th>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">AI</th>
                                                <th className="px-4 py-3 text-sm font-medium text-[var(--text-secondary)] text-right whitespace-nowrap">Actions</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-[var(--border)]">
                                            {users.map((user) => (
                                                <tr key={user.id} className="hover:bg-[var(--header-bg)] transition-colors">
                                                    <td className="px-4 py-3">
                                                        <div>
                                                            <span className="font-medium text-[var(--text-primary)]">{user.display_name}</span>
                                                            <p className="text-xs text-[var(--text-muted)]">{user.email}</p>
                                                        </div>
                                                    </td>
                                                    <td className="px-4 py-3">
                                                        {user.is_banned ? (
                                                            <span className="px-2 py-1 text-xs rounded-full bg-red-600 text-white">Banned</span>
                                                        ) : (
                                                            <span className="px-2 py-1 text-xs rounded-full bg-green-600 text-white">Active</span>
                                                        )}
                                                    </td>
                                                    <td className="px-4 py-3">
                                                        <Toggle
                                                            checked={user.ai_enabled}
                                                            onChange={(checked) => handleToggleAI(user.id, checked)}
                                                        />
                                                    </td>
                                                    <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            onClick={() => fetchUserChat(user.id)}
                                                        >
                                                            Chat
                                                        </Button>
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            onClick={() => handleEditUser(user)}
                                                        >
                                                            Edit
                                                        </Button>
                                                        <Button
                                                            variant={user.is_banned ? 'primary' : 'danger'}
                                                            size="sm"
                                                            onClick={() => handleBanUser(user.id, !user.is_banned)}
                                                        >
                                                            {user.is_banned ? 'Unban' : 'Ban'}
                                                        </Button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        )}
                    </div >
                )}

                {/* Orders Tab */}
                {activeTab === 'orders' && (
                    <div className={tabDirection === 'left' ? 'animate-slide-in-left' : 'animate-slide-in-right'}>
                        {/* Orders Summary */}
                        {ordersSummary && (
                            <div className="grid grid-cols-2 gap-4 mb-6">
                                <div className="bg-[var(--card-bg)] border border-[var(--border)] rounded-xl p-4">
                                    <p className="text-[var(--text-muted)] text-sm">Total Sales</p>
                                    <p className="text-2xl font-bold text-green-400">RM {ordersSummary.total_sales.toFixed(2)}</p>
                                </div>
                                <div className="bg-[var(--card-bg)] border border-[var(--border)] rounded-xl p-4">
                                    <p className="text-[var(--text-muted)] text-sm">Total Orders</p>
                                    <p className="text-2xl font-bold text-[var(--text-primary)]">{ordersSummary.total_transactions}</p>
                                </div>
                            </div>
                        )}

                        {ordersLoading ? (
                            <div className="flex items-center justify-center py-12">
                                <div className="w-8 h-8 border-2 border-zinc-700 border-t-white rounded-full animate-spin" />
                            </div>
                        ) : orders.length === 0 ? (
                            <div className="text-center py-12 text-[var(--text-muted)]">
                                <div className="text-5xl mb-4">📦</div>
                                <p>No orders yet</p>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {orders.map((order) => {
                                    let imageUrl = null
                                    if (order.item_image) {
                                        try {
                                            const parsed = JSON.parse(order.item_image)
                                            imageUrl = Object.values(parsed)[0] as string
                                        } catch { /* ignore */ }
                                    }

                                    return (
                                        <div key={order.id} className="bg-[var(--card-bg)] border border-[var(--border)] rounded-xl p-4 flex gap-4">
                                            {/* Item Image */}
                                            <div className="w-16 h-16 flex-shrink-0 rounded-lg overflow-hidden bg-[var(--bg-tertiary)]">
                                                {imageUrl ? (
                                                    <img src={imageUrl} alt={order.item_name} className="w-full h-full object-cover" />
                                                ) : (
                                                    <div className="w-full h-full flex items-center justify-center text-2xl">📦</div>
                                                )}
                                            </div>

                                            {/* Order Details */}
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-start justify-between gap-2">
                                                    <h3 className="font-semibold text-[var(--text-primary)] truncate">{order.item_name}</h3>
                                                    <span className={`px-2 py-0.5 text-xs font-medium rounded border ${order.status === 'completed' ? 'bg-green-500/20 text-green-400 border-green-500/30' :
                                                        order.status === 'refunded' ? 'bg-red-500/20 text-red-400 border-red-500/30' :
                                                            'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                                                        }`}>
                                                        {order.status.charAt(0).toUpperCase() + order.status.slice(1)}
                                                    </span>
                                                </div>
                                                <p className="text-sm text-[var(--text-muted)] truncate">{order.buyer_email}</p>
                                                <div className="flex items-center justify-between mt-2">
                                                    <span className="font-bold text-[var(--accent)]">RM {order.amount_paid.toFixed(2)}</span>
                                                    <span className="text-xs text-[var(--text-muted)]">
                                                        {new Date(order.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </div>
                )}
            </main>


            {editingUser && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
                    <div className="w-full max-w-md animate-slide-up flex flex-col items-start">
                        {/* Return to users link */}
                        <button
                            onClick={() => setEditingUser(null)}
                            className="flex items-center gap-2 text-white hover:text-white/80 transition-colors group mb-4"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M19 12H5M12 19l-7-7 7-7" />
                            </svg>
                            <span className="text-sm font-medium relative">
                                Return to users
                                <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-white transition-all duration-300 group-hover:w-full" />
                            </span>
                        </button>

                        <Card className="w-full">
                            <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-4">Edit User</h2>
                            <div className="space-y-6">
                                <Input
                                    label="Display Name"
                                    value={editForm.displayName}
                                    onChange={(e) => setEditForm(prev => ({ ...prev, displayName: e.target.value }))}
                                />

                                {/* Avatar Upload */}
                                <div>
                                    <label className="block text-sm font-medium text-[var(--text-secondary)] mb-2">Avatar</label>
                                    <div className="flex items-center gap-4">
                                        <div className="w-20 h-20 rounded-full bg-[var(--bg-secondary)] overflow-hidden border border-[var(--border)] relative group">
                                            {editForm.avatarUrl ? (
                                                <img
                                                    src={editForm.avatarUrl}
                                                    alt="Avatar"
                                                    className="w-full h-full object-cover"
                                                />
                                            ) : (
                                                <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] text-xl">
                                                    {(editForm.displayName || '?').charAt(0).toUpperCase()}
                                                </div>
                                            )}
                                            {/* Overlay on hover */}
                                        </div>

                                        <label className="px-4 py-2 border border-[var(--border)] rounded-lg hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)] text-[var(--text-secondary)] transition-colors cursor-pointer text-sm font-medium">
                                            Upload Image
                                            <input
                                                type="file"
                                                accept="image/*"
                                                onChange={(e) => e.target.files && handleAvatarUpload(e.target.files)}
                                                className="hidden"
                                            />
                                        </label>
                                    </div>
                                </div>

                                <div className="pt-2">
                                    <Button fullWidth variant="filled" onClick={handleSaveProfile}>
                                        Save Changes
                                    </Button>
                                </div>
                            </div>
                        </Card>
                    </div>
                </div>
            )}

            {/* Full Chat View - Replaces entire screen when active */}
            {selectedUserChat && (
                <div
                    className="h-[100dvh] flex flex-col overflow-hidden fixed inset-0 z-50"
                    style={{ background: 'var(--chat-bg-gradient)' }}
                >
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
                                onClick={() => setSelectedUserChat(null)}
                                className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                                aria-label="Back"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M19 12H5M12 19l-7-7 7-7" />
                                </svg>
                            </button>
                            <div className="flex-1">
                                <h1 className="text-lg font-semibold text-[var(--text-primary)]">Chat</h1>
                                <p className="text-sm text-[var(--text-muted)]">
                                    {users.find(u => u.id === selectedUserChat.userId)?.display_name || 'User'}
                                </p>
                            </div>
                        </div>
                    </header>

                    {/* Messages - Scrollable middle section */}
                    <main ref={chatContainerRef} className="flex-1 overflow-y-auto relative z-10">
                        <div className="max-w-2xl mx-auto px-4 py-6 space-y-4">
                            {/* Load More Button */}
                            {hasMoreMessages && (
                                <div className="flex justify-center py-2">
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={loadMoreMessages}
                                        className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                                        disabled={isLoadingHistory}
                                    >
                                        {isLoadingHistory ? 'Loading...' : 'Load previous messages'}
                                    </Button>
                                </div>
                            )}

                            {selectedUserChat.messages.map((msg, idx) => {
                                // System Message
                                if (msg.source === 'system') {
                                    return (
                                        <div key={idx} className="flex justify-center py-2">
                                            <span className="text-sm text-[var(--text-muted)] italic">
                                                {msg.content}
                                            </span>
                                        </div>
                                    )
                                }

                                // Skip empty messages (e.g. file uploads without text, or glitches)
                                if (!msg.content) return null

                                const isAdmin = msg.source === 'admin'
                                const user = users.find(u => u.id === selectedUserChat.userId)

                                const getUserName = () => {
                                    if (msg.source === 'admin') return 'Me'
                                    if (msg.source === 'ai') return 'AI Assistant'
                                    return user?.display_name || 'User'
                                }

                                const getAvatarText = () => {
                                    if (msg.source === 'admin') return 'A'
                                    if (msg.source === 'ai') return 'AI'
                                    return (user?.display_name || 'U').charAt(0)
                                }

                                // Admin on Right (isUser=true), User/AI on Left (isUser=false)
                                return (
                                    <ChatBubble
                                        key={idx}
                                        message={msg.content}
                                        isUser={isAdmin}
                                        isAi={msg.source === 'ai'}
                                        timestamp={new Date().toLocaleTimeString([], {
                                            hour: '2-digit',
                                            minute: '2-digit'
                                        })}
                                        avatarUrl={!isAdmin && msg.source === 'human' ? user?.avatar_url : undefined}
                                        userName={getUserName()}
                                        avatarText={getAvatarText()}
                                    />
                                )
                            })}

                            {isUserTyping && (
                                <div className="flex justify-start my-4">
                                    <div className="flex gap-3 max-w-[80%]">
                                        <div className="w-8 h-8 rounded-full bg-[var(--bg-secondary)] flex-shrink-0 flex items-center justify-center text-xs font-medium border border-[var(--border)] text-[var(--text-secondary)]">
                                            {(users.find(u => u.id === selectedUserChat.userId)?.display_name || 'U').charAt(0).toUpperCase()}
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
                        <div className="max-w-2xl mx-auto px-4 py-4">
                            <div className="flex gap-3 items-center">
                                <input
                                    type="text"
                                    value={adminReply}
                                    onChange={(e) => {
                                        setAdminReply(e.target.value)
                                        sendTyping()
                                    }}
                                    placeholder="Enter your message"
                                    className="flex-1 px-4 py-3 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-xl text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--input-focus-border)]"
                                    onKeyDown={(e) => e.key === 'Enter' && handleSendAdminMessage()}
                                />
                                <Button
                                    variant="filled"
                                    onClick={handleSendAdminMessage}
                                    disabled={!adminReply.trim()}
                                >
                                    Send
                                </Button>
                            </div>
                        </div>
                    </footer>
                </div>
            )}

            {/* Modals outside the main container for proper z-index */}
            {/* Add Form Modal */}
            {showAddForm && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
                    <div className="w-full max-w-md animate-slide-up flex flex-col items-start">
                        {/* Return to items link above the card */}
                        <button
                            onClick={() => setShowAddForm(false)}
                            className="flex items-center gap-2 text-white hover:text-white/80 transition-colors group mb-4"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M19 12H5M12 19l-7-7 7-7" />
                            </svg>
                            <span className="text-sm font-medium relative">
                                Return to items
                                <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-white transition-all duration-300 group-hover:w-full" />
                            </span>
                        </button>

                        <Card className="w-full max-h-[85vh] overflow-y-auto">
                            <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-4">Add New Item</h2>
                            <form onSubmit={handleAdd} className="space-y-4">
                                <Input
                                    label="Name"
                                    value={formData.name}
                                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                    required
                                />
                                <Input
                                    label="Description"
                                    value={formData.description}
                                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                    required
                                />
                                <div className="grid grid-cols-2 gap-4">
                                    <Input
                                        label="Listed Price (RM)"
                                        type="number"
                                        value={formData.price}
                                        onChange={(e) => setFormData({ ...formData, price: e.target.value })}
                                        required
                                    />
                                    <Input
                                        label="Base Price (RM)"
                                        type="number"
                                        placeholder="Min acceptable"
                                        value={formData.min_price}
                                        onChange={(e) => setFormData({ ...formData, min_price: e.target.value })}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">Condition</label>
                                    <select
                                        value={formData.condition}
                                        onChange={(e) => setFormData({ ...formData, condition: e.target.value })}
                                        className="w-full px-4 py-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-[var(--input-focus-border)] transition-colors"
                                    >
                                        <option value="New">New</option>
                                        <option value="Like New">Like New</option>
                                        <option value="Good">Good</option>
                                        <option value="Fair">Fair</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">Images</label>
                                    <input
                                        type="file"
                                        multiple
                                        accept="image/*"
                                        onChange={(e) => setImages(e.target.files)}
                                        className="w-full text-[var(--text-secondary)] file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-[var(--bg-tertiary)] file:text-[var(--text-primary)] hover:file:bg-[var(--border)] transition-colors"
                                    />
                                </div>
                                <div className="pt-2">
                                    <Button type="submit" fullWidth variant="filled">
                                        Add Item
                                    </Button>
                                </div>
                            </form>
                        </Card>
                    </div >
                </div >
            )
            }

            {/* Edit Form Modal */}
            {
                editingItem && (
                    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
                        <div className="w-full max-w-md animate-slide-up flex flex-col items-start">
                            {/* Return to items link above the card */}
                            <button
                                onClick={() => setEditingItem(null)}
                                className="flex items-center gap-2 text-white hover:text-white/80 transition-colors group mb-4"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M19 12H5M12 19l-7-7 7-7" />
                                </svg>
                                <span className="text-sm font-medium relative">
                                    Return to items
                                    <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-white transition-all duration-300 group-hover:w-full" />
                                </span>
                            </button>

                            <Card className="w-full max-h-[85vh] overflow-y-auto">
                                <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-4">Edit Item</h2>
                                <form onSubmit={handleUpdate} className="space-y-4">
                                    <Input
                                        label="Name"
                                        value={formData.name}
                                        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                        required
                                    />
                                    <Input
                                        label="Description"
                                        value={formData.description}
                                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                        required
                                    />
                                    <div className="grid grid-cols-2 gap-4">
                                        <Input
                                            label="Listed Price (RM)"
                                            type="number"
                                            value={formData.price}
                                            onChange={(e) => setFormData({ ...formData, price: e.target.value })}
                                        />
                                        <Input
                                            label="Base Price (RM)"
                                            type="number"
                                            placeholder="Min acceptable"
                                            value={formData.min_price}
                                            onChange={(e) => setFormData({ ...formData, min_price: e.target.value })}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">Condition</label>
                                        <select
                                            value={formData.condition}
                                            onChange={(e) => setFormData({ ...formData, condition: e.target.value })}
                                            className="w-full px-4 py-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-[var(--input-focus-border)] transition-colors"
                                        >
                                            <option value="New">New</option>
                                            <option value="Like New">Like New</option>
                                            <option value="Good">Good</option>
                                            <option value="Fair">Fair</option>
                                        </select>
                                    </div>
                                    {/* Current Images */}
                                    <div>
                                        <label className="block text-sm font-medium text-[var(--text-secondary)] mb-2">Images</label>
                                        <div className="flex flex-wrap gap-3">
                                            {currentItemImages.map((img, idx) => (
                                                <div key={idx} className="relative group">
                                                    <img
                                                        src={img}
                                                        alt={`Item ${idx + 1}`}
                                                        className="w-20 h-20 object-cover rounded-lg border border-[var(--border)]"
                                                    />
                                                    <button
                                                        type="button"
                                                        onClick={() => handleDeleteImage(idx)}
                                                        className="absolute -top-2 -right-2 w-5 h-5 bg-gray-500 text-white rounded-full flex items-center justify-center text-xs hover:bg-gray-600 transition-colors opacity-0 group-hover:opacity-100"
                                                    >
                                                        ×
                                                    </button>
                                                </div>
                                            ))}
                                            {/* Add Image Button */}
                                            <label className="w-20 h-20 border-2 border-dashed border-[var(--border)] rounded-lg flex items-center justify-center cursor-pointer hover:border-[var(--accent)] transition-colors">
                                                <input
                                                    type="file"
                                                    multiple
                                                    accept="image/*"
                                                    onChange={(e) => e.target.files && handleAddImages(e.target.files)}
                                                    className="hidden"
                                                />
                                                <span className="text-2xl text-[var(--text-muted)]">+</span>
                                            </label>
                                        </div>
                                    </div>
                                    <div className="pt-2">
                                        <Button type="submit" fullWidth variant="filled">
                                            Save Changes
                                        </Button>
                                    </div>
                                </form>
                            </Card>
                        </div>
                    </div>
                )}
            {/* Confirmation Modal */}
            <ConfirmationModal
                isOpen={confirmation.isOpen}
                onClose={() => setConfirmation(prev => ({ ...prev, isOpen: false }))}
                onConfirm={confirmation.onConfirm}
                title={confirmation.title}
                message={confirmation.message}
                isLoading={confirmation.isLoading}
            />

            {/* Logout Confirmation Modal */}
            <ConfirmationModal
                isOpen={showLogoutConfirm}
                onClose={() => setShowLogoutConfirm(false)}
                onConfirm={confirmLogout}
                title="Logout"
                message="Are you sure you want to logout?"
                confirmText="Logout"
                isLoading={isLoggingOut}
            />
        </div>
    )
}




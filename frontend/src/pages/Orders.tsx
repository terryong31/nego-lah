import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ThemeToggle } from '../components/ThemeToggle'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

interface Order {
    id: string
    item_id: string
    item_name: string
    item_image?: string
    item_condition?: string
    amount: number
    status: string
    created_at: string
}

export function Orders() {
    const [orders, setOrders] = useState<Order[]>([])
    const [loading, setLoading] = useState(true)
    const { user } = useAuth()
    const navigate = useNavigate()

    useEffect(() => {
        async function fetchOrders() {
            if (!user?.email) {
                setLoading(false)
                return
            }

            try {
                const response = await fetch(`${API_URL}/orders/user/${encodeURIComponent(user.email)}`)
                if (response.ok) {
                    const data = await response.json()
                    setOrders(data.orders || [])
                }
            } catch (error) {
                console.error('Failed to fetch orders:', error)
            } finally {
                setLoading(false)
            }
        }

        fetchOrders()
    }, [user?.email])

    // Parse first image from JSON image_path
    const getFirstImage = (imagePath?: string): string | null => {
        if (!imagePath) return null
        try {
            const parsed = JSON.parse(imagePath)
            const urls = Object.values(parsed)
            return urls[0] as string
        } catch {
            return null
        }
    }

    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        })
    }

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'completed':
                return 'bg-green-500/20 text-green-400 border-green-500/30'
            case 'refunded':
                return 'bg-red-500/20 text-red-400 border-red-500/30'
            case 'pending':
                return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
            default:
                return 'bg-gray-500/20 text-gray-400 border-gray-500/30'
        }
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
                <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
                    <button
                        onClick={() => {
                            if (document.startViewTransition) {
                                document.documentElement.classList.add('back-transition')
                                const transition = document.startViewTransition(() => {
                                    navigate('/')
                                })
                                transition.finished.finally(() => {
                                    document.documentElement.classList.remove('back-transition')
                                })
                            } else {
                                navigate('/')
                            }
                        }}
                        className="flex items-center gap-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                        <span className="text-sm font-medium relative">
                            Back
                            <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover:w-full" />
                        </span>
                    </button>
                    <h1 className="text-xl font-bold text-[var(--text-primary)]">My Orders</h1>
                    <ThemeToggle className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]" />
                </div>
            </header>

            {/* Main Content */}
            <main className="relative z-10 max-w-4xl mx-auto px-4 py-8">
                {loading ? (
                    <div className="flex items-center justify-center py-20">
                        <div className="w-8 h-8 border-2 border-zinc-700 border-t-white rounded-full animate-spin" />
                    </div>
                ) : orders.length === 0 ? (
                    <div className="text-center py-20">
                        <div className="text-6xl mb-4">📦</div>
                        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-2">No orders yet</h2>
                        <p className="text-[var(--text-secondary)] mb-6">
                            When you purchase items, they'll appear here.
                        </p>
                        <button
                            onClick={() => {
                                if (document.startViewTransition) {
                                    document.documentElement.classList.add('back-transition')
                                    const transition = document.startViewTransition(() => {
                                        navigate('/')
                                    })
                                    transition.finished.finally(() => {
                                        document.documentElement.classList.remove('back-transition')
                                    })
                                } else {
                                    navigate('/')
                                }
                            }}
                            className="px-6 py-3 bg-[var(--btn-filled-bg)] text-[var(--btn-filled-text)] rounded-xl font-medium hover:bg-[var(--btn-filled-bg-hover)] transition-colors"
                        >
                            Browse Items
                        </button>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {orders.map((order) => {
                            const imageUrl = getFirstImage(order.item_image)
                            return (
                                <div
                                    key={order.id}
                                    className="bg-[var(--card-bg)] backdrop-blur-md border border-[var(--border)] rounded-2xl p-4 flex gap-4"
                                >
                                    {/* Item Image */}
                                    <div className="w-24 h-24 flex-shrink-0 rounded-xl overflow-hidden bg-[var(--bg-tertiary)]">
                                        {imageUrl ? (
                                            <img src={imageUrl} alt={order.item_name} className="w-full h-full object-cover" />
                                        ) : (
                                            <div className="w-full h-full flex items-center justify-center text-3xl">📦</div>
                                        )}
                                    </div>

                                    {/* Order Details */}
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-start justify-between gap-2">
                                            <h3 className="font-semibold text-[var(--text-primary)] truncate">
                                                {order.item_name}
                                            </h3>
                                            <span className={`px-2 py-0.5 text-xs font-medium rounded border ${getStatusColor(order.status)}`}>
                                                {order.status.charAt(0).toUpperCase() + order.status.slice(1)}
                                            </span>
                                        </div>

                                        {order.item_condition && (
                                            <p className="text-sm text-[var(--text-muted)] mt-1">
                                                Condition: {order.item_condition}
                                            </p>
                                        )}

                                        <div className="flex items-center justify-between mt-3">
                                            <span className="text-lg font-bold text-[var(--accent)]">
                                                RM {order.amount.toFixed(2)}
                                            </span>
                                            <span className="text-xs text-[var(--text-muted)]">
                                                {formatDate(order.created_at)}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </main>
        </div>
    )
}

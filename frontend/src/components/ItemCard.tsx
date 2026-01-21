import { Button } from './Button'

interface Item {
    id: string
    name: string
    description: string
    condition: string
    price: number
    image_path?: string
    status?: string
}

interface ItemCardProps {
    item: Item
    onClick?: () => void
    onBuy?: (itemId: string) => void
    isBuying?: boolean
}

export function ItemCard({ item, onClick, onBuy, isBuying = false }: ItemCardProps) {
    const isSold = item.status === 'sold'

    // Parse first image URL
    let imageUrl: string | null = null
    if (item.image_path) {
        try {
            const images = JSON.parse(item.image_path)
            const firstKey = Object.keys(images)[0]
            if (firstKey) {
                imageUrl = images[firstKey]
            }
        } catch { /* ignore */ }
    }

    const handleCardClick = () => {
        if (onClick) onClick()
    }

    const handleBuyClick = (e: React.MouseEvent) => {
        e.stopPropagation() // Prevent card click
        if (onBuy && !isBuying) onBuy(item.id)
    }

    return (
        <div
            className={`cool-card-wrapper group cursor-pointer ${isSold ? 'opacity-60 grayscale' : ''}`}
            onClick={handleCardClick}
        >
            {/* Main Card - No floating accents */}
            <div className="cool-card">
                {/* Top Light Accent */}
                <div className="top-light"></div>

                {/* Image with rounded corners */}
                <div className="cool-card-img-container">
                    {imageUrl ? (
                        <img
                            src={imageUrl}
                            alt={item.name}
                            className="rounded-xl"
                        />
                    ) : (
                        <div className="flex flex-col items-center justify-center text-[var(--text-muted)] w-full h-full rounded-xl bg-[var(--bg-tertiary)]">
                            <span className="text-4xl mb-2">📦</span>
                            <span className="text-sm">No Image</span>
                        </div>
                    )}
                </div>

                {/* Content - Reduced gap with mt-2 */}
                <div className="relative z-10 mt-2">
                    <h3 className="line-clamp-1 text-[var(--text-primary)]" title={item.name}>{item.name}</h3>
                    <span className="price text-[var(--text-primary)]">RM {item.price}</span>

                    <div className="flex items-center justify-between mt-3">
                        {/* Click for details with underline animation */}
                        <span className="text-xs text-[var(--text-secondary)] relative group/link cursor-pointer">
                            Click for details
                            <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-secondary)] transition-all duration-300 group-hover/link:w-full group-hover:w-full" />
                        </span>

                        {!isSold ? (
                            <Button
                                variant="filled"
                                size="sm"
                                className="!rounded-full !px-6 flex items-center gap-2 min-w-[80px] h-8 justify-center transition-colors"
                                onClick={handleBuyClick}
                                disabled={isBuying}
                            >
                                {isBuying ? (
                                    <div className="w-4 h-4 border-2 border-[var(--btn-filled-text)] border-t-transparent rounded-full animate-spin" />
                                ) : (
                                    'Buy'
                                )}
                            </Button>
                        ) : (
                            <span className="text-sm font-bold text-red-400 bg-red-900/30 px-3 py-1 rounded border border-red-500/30">
                                SOLD
                            </span>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}

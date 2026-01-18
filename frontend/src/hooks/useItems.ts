import { useState, useEffect, useCallback } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

interface Item {
    id: string
    name: string
    description: string
    condition: string
    price: number
    image_path?: string
    status?: string
}

interface ItemsState {
    items: Item[]
    isLoading: boolean
    error: string | null
}

export function useItems() {
    const [state, setState] = useState<ItemsState>({
        items: [],
        isLoading: true,
        error: null
    })

    const fetchItems = useCallback(async (keyword?: string) => {
        setState(prev => ({ ...prev, isLoading: true, error: null }))

        try {
            const url = keyword
                ? `${API_URL}/items?keyword=${encodeURIComponent(keyword)}`
                : `${API_URL}/items`

            const res = await fetch(url)

            if (res.ok) {
                const data = await res.json()
                setState({
                    items: data,
                    isLoading: false,
                    error: null
                })
            } else {
                setState(prev => ({
                    ...prev,
                    isLoading: false,
                    error: 'Failed to load items'
                }))
            }
        } catch {
            setState(prev => ({
                ...prev,
                isLoading: false,
                error: 'Connection error'
            }))
        }
    }, [])

    const getCheckoutUrl = useCallback(async (itemId: string): Promise<string | null> => {
        try {
            const res = await fetch(`${API_URL}/checkout`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_id: itemId })
            })

            if (res.ok) {
                const data = await res.json()
                return data.checkout_url
            }
            return null
        } catch {
            return null
        }
    }, [])

    useEffect(() => {
        fetchItems()
    }, [fetchItems])

    return {
        ...state,
        fetchItems,
        getCheckoutUrl
    }
}

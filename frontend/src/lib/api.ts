export const API_URL = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '/api' : 'http://127.0.0.1:8000')

export const api = {
    get: async (url: string) => {
        const fullUrl = url.startsWith('http') ? url : `${API_URL}${url}`
        const res = await fetch(fullUrl)
        if (!res.ok) {
            throw new Error(`API Error: ${res.statusText}`)
        }
        const data = await res.json()
        return { data }
    },
    put: async (url: string, body: any) => {
        const fullUrl = url.startsWith('http') ? url : `${API_URL}${url}`
        const res = await fetch(fullUrl, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(body),
        })
        if (!res.ok) {
            throw new Error(`API Error: ${res.statusText}`)
        }
        const data = await res.json()
        return { data }
    }
}

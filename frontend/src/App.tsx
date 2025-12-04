import { useState, useEffect } from 'react'

const API_URL = 'http://127.0.0.1:8820'

interface Item {
  id: number
  name: string
  description: string
  condition: string
  image_path: string
}

function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'))
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [message, setMessage] = useState('')
  const [isLogin, setIsLogin] = useState(true)

  // Fetch items on load
  useEffect(() => {
    fetchItems()
  }, [])

  const fetchItems = async () => {
    try {
      const res = await fetch(`${API_URL}/items`)
      if (res.ok) {
        const data = await res.json()
        setItems(data)
      }
    } catch (err) {
      console.log('Could not fetch items')
    }
  }

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    setMessage('')
    
    const endpoint = isLogin ? '/login' : '/register'
    
    try {
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      })
      
      const data = await res.json()
      
      if (res.ok) {
        setToken(data.access_token)
        localStorage.setItem('token', data.access_token)
        setMessage(`✅ ${isLogin ? 'Login' : 'Registration'} successful!`)
        setUsername('')
        setPassword('')
      } else {
        setMessage(`❌ ${data.detail}`)
      }
    } catch (err) {
      setMessage('❌ Server error')
    }
  }

  const handleLogout = () => {
    setToken(null)
    localStorage.removeItem('token')
    setMessage('Logged out')
  }

  return (
    <div className="min-h-screen bg-gray-100 p-4">
      <div className="max-w-md mx-auto">
        
        {/* Header */}
        <h1 className="text-2xl font-bold text-center mb-6">🛒 Second Hand Store</h1>

        {/* Auth Section */}
        <div className="bg-white rounded-lg shadow p-4 mb-4">
          <h2 className="text-lg font-semibold mb-3">
            {token ? '👤 Logged In' : (isLogin ? '🔐 Login' : '📝 Register')}
          </h2>
          
          {token ? (
            <button 
              onClick={handleLogout}
              className="w-full bg-red-500 text-white py-2 rounded hover:bg-red-600"
            >
              Logout
            </button>
          ) : (
            <form onSubmit={handleAuth} className="space-y-3">
              <input
                type="text"
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full border rounded p-2"
                required
              />
              <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full border rounded p-2"
                required
              />
              <button 
                type="submit"
                className="w-full bg-blue-500 text-white py-2 rounded hover:bg-blue-600"
              >
                {isLogin ? 'Login' : 'Register'}
              </button>
              <button 
                type="button"
                onClick={() => setIsLogin(!isLogin)}
                className="w-full text-blue-500 text-sm"
              >
                {isLogin ? 'Need an account? Register' : 'Have an account? Login'}
              </button>
            </form>
          )}
          
          {message && (
            <p className="mt-3 text-center text-sm">{message}</p>
          )}
        </div>

        {/* Items Section */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-lg font-semibold">📦 Items</h2>
            <button 
              onClick={fetchItems}
              className="text-sm bg-gray-200 px-3 py-1 rounded hover:bg-gray-300"
            >
              Refresh
            </button>
          </div>
          
          {items.length === 0 ? (
            <p className="text-gray-500 text-center py-4">No items found</p>
          ) : (
            <div className="space-y-3">
              {items.map((item) => (
                <div key={item.id} className="border rounded p-3">
                  <h3 className="font-medium">{item.name}</h3>
                  <p className="text-sm text-gray-600">{item.description}</p>
                  <span className="inline-block mt-1 text-xs bg-gray-100 px-2 py-1 rounded">
                    {item.condition}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Debug Info */}
        <div className="mt-4 text-xs text-gray-400 text-center">
          <p>API: {API_URL}</p>
          <p>Token: {token ? '✅ Present' : '❌ None'}</p>
        </div>
        
      </div>
    </div>
  )
}

export default App

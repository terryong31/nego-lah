import { BrowserRouter, Routes, Route, useNavigate, Navigate, useLocation } from 'react-router-dom'
import { Home } from './pages/Home'
import { Chat } from './pages/Chat'
import { Admin } from './pages/Admin'
import { Login } from './pages/Login'
import { Profile } from './pages/Profile'
import { ProfileSetup } from './pages/ProfileSetup'
import { Orders } from './pages/Orders'
import { AuthProvider, useAuth } from './context/AuthContext'
import { useState, useCallback, useEffect } from 'react'

interface ChatContext {
  itemId?: string
  itemName?: string
}

// Toast notification component
function Toast({ message, type = 'success', onClose }: { message: string; type?: 'success' | 'warning' | 'info'; onClose: () => void }) {
  const [isExiting, setIsExiting] = useState(false)

  useEffect(() => {
    // Start exit animation before actually closing
    const exitTimer = setTimeout(() => setIsExiting(true), 4600)
    const closeTimer = setTimeout(onClose, 5000)
    return () => {
      clearTimeout(exitTimer)
      clearTimeout(closeTimer)
    }
  }, [onClose])

  const bgColor = type === 'success' ? 'bg-green-600' : type === 'warning' ? 'bg-amber-500' : 'bg-blue-500'

  return (
    <div className={`fixed bottom-4 left-4 z-50 ${bgColor} text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 ${isExiting ? 'toast-exit' : 'toast-enter'}`}>
      {type === 'success' ? (
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      ) : type === 'warning' ? (
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      ) : (
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
      )}
      <span>{message}</span>
    </div>
  )
}

// Protected route component
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-zinc-700 border-t-white rounded-full animate-spin" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function AppRoutes() {
  const [chatContext, setChatContext] = useState<ChatContext>({})
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'warning' | 'info' } | null>(null)
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // Check for confirmation success or payment status in URL
  useEffect(() => {
    const params = new URLSearchParams(location.search)

    // Handle email confirmation
    if (params.get('confirmed') === 'true') {
      setToast({ message: 'Email confirmation successful!', type: 'success' })
      navigate('/', { replace: true })
      return
    }

    // Handle payment status
    const paymentStatus = params.get('payment')
    if (paymentStatus === 'success') {
      setToast({ message: 'Payment successful! Thank you for your purchase.', type: 'success' })
      navigate('/', { replace: true })
    } else if (paymentStatus === 'cancelled') {
      setToast({ message: 'Payment was cancelled. Feel free to try again when ready.', type: 'warning' })
      navigate('/', { replace: true })
    }
  }, [location.search, navigate])

  // Use Supabase user ID if logged in, otherwise guest ID
  const userId = user?.id || `guest-${Date.now()}`

  const handleOpenChat = useCallback((itemId: string, itemName?: string) => {
    setChatContext({ itemId, itemName })
    navigate('/chat')
  }, [navigate])

  const handleBackToHome = useCallback(() => {
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
  }, [navigate])

  const handleOpenLogin = useCallback(() => {
    navigate('/login')
  }, [navigate])

  const handleOpenProfile = useCallback(() => {
    navigate('/profile')
  }, [navigate])

  return (
    <>
      {/* Toast notification */}
      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}

      <Routes>
        <Route
          path="/"
          element={
            <Home
              onChat={handleOpenChat}
              onLogin={handleOpenLogin}
              onOpenProfile={handleOpenProfile}
              isAuthenticated={!!user}
              onLogout={signOut}
              userAvatar={user?.user_metadata?.avatar_url}
              userName={user?.user_metadata?.full_name || user?.email}
            />
          }
        />
        <Route
          path="/login"
          element={<Login onBack={handleBackToHome} />}
        />
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              <Chat
                userId={userId}
                itemId={chatContext.itemId}
                itemName={chatContext.itemName}
                onBack={handleBackToHome}
                userAvatar={user?.user_metadata?.avatar_url}
                userName={user?.user_metadata?.full_name || user?.email}
              />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={<Admin onBack={handleBackToHome} />}
        />
        <Route
          path="/profile"
          element={
            <ProtectedRoute>
              <Profile />
            </ProtectedRoute>
          }
        />
        <Route
          path="/profile-setup"
          element={
            <ProtectedRoute>
              <ProfileSetup />
            </ProtectedRoute>
          }
        />
        <Route
          path="/orders"
          element={
            <ProtectedRoute>
              <Orders />
            </ProtectedRoute>
          }
        />
      </Routes>
    </>
  )
}

function App() {
  // Initialize theme on app load
  useEffect(() => {
    const savedTheme = localStorage.getItem('theme') || 'dark'
    const root = document.documentElement
    root.classList.remove('light', 'dark')
    root.classList.add(savedTheme)
  }, [])

  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App

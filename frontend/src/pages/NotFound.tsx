import { useNavigate } from 'react-router-dom'
import { Button } from '../components/Button'
import { Card } from '../components/Card'

export function NotFound() {
    const navigate = useNavigate()

    return (
        <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden">
            {/* Stars Background */}
            <div className="stars-container">
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="stars"></div>
            </div>

            <div className="relative z-10 w-full max-w-md text-center animate-slide-up">
                <Card className="backdrop-blur-md shadow-2xl border-[var(--border)] p-8">
                    <div className="mb-6">
                        <div className="text-6xl font-bold bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent mb-2">
                            404
                        </div>
                        <h1 className="text-2xl font-semibold text-[var(--text-primary)] mb-2">
                            Page Not Found
                        </h1>
                        <p className="text-[var(--text-secondary)]">
                            The page you are looking for doesn't exist or has been moved.
                        </p>
                    </div>

                    <div className="flex flex-col gap-3">
                        <Button
                            variant="filled"
                            fullWidth
                            onClick={() => navigate('/')}
                        >
                            Return Home
                        </Button>
                    </div>
                </Card>
            </div>
        </div>
    )
}

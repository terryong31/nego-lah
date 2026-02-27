import { useNavigate } from 'react-router-dom'


export function Terms() {
    const navigate = useNavigate()

    return (
        <div className="min-h-screen relative flex flex-col font-['Space_Grotesk']">
            {/* Stars Background */}
            <div className="stars-container">
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="stars"></div>
            </div>

            {/* Header */}
            <header className="liquid-glass-header sticky top-0 z-50">
                <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
                    <a href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
                        <img src="/logo.png" alt="Logo" className="w-8 h-8 object-contain" />
                        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Nego-lah</h1>
                    </a>

                </div>
            </header>

            {/* Main Content */}
            <main className="flex-1 relative z-10 py-12 px-4 md:px-6">
                <div className="max-w-4xl mx-auto">
                    <div className="mb-6">
                        <button
                            onClick={() => navigate('/')}
                            className="flex items-center gap-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors group"
                        >   ←
                            <span className="text-sm font-medium relative">
                                Back to Home
                                <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover:w-full" />
                            </span>
                        </button>
                    </div>

                    <div className="cool-card p-8 md:p-12 !min-h-0 backdrop-blur-xl">
                        <h1 className="text-3xl md:text-4xl font-bold mb-8 text-[var(--text-primary)]">Terms of Service</h1>

                        <div className="space-y-8 text-[var(--text-secondary)] leading-relaxed">
                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <circle cx="12" cy="12" r="10" />
                                        <line x1="12" x2="12" y1="8" y2="12" />
                                        <line x1="12" x2="12.01" y1="16" y2="16" />
                                    </svg>
                                    Agreement to Terms
                                </h2>
                                <p>
                                    By accessing our website at Nego-lah, you agree to be bound by these terms of service, all applicable laws and regulations, and agree that you are responsible for compliance with any applicable local laws. If you do not agree with any of these terms, you are prohibited from using or accessing this site.
                                </p>
                            </section>

                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <path d="M12.5 22H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v5" />
                                        <path d="M16 16v-3a2 2 0 0 0-4 0v3" />
                                        <circle cx="14" cy="19" r="3" />
                                        <path d="M9 17v1a3 3 0 0 0 6 0v-1" />
                                    </svg>
                                    Use License
                                </h2>
                                <p>
                                    Permission is granted to temporarily download one copy of the materials (information or software) on Nego-lah's website for personal, non-commercial transitory viewing only. This is the grant of a license, not a transfer of title, and under this license you may not:
                                </p>
                                <ul className="list-disc pl-6 mt-4 space-y-2">
                                    <li>Modify or copy the materials;</li>
                                    <li>Use the materials for any commercial purpose, or for any public display (commercial or non-commercial);</li>
                                    <li>Attempt to decompile or reverse engineer any software contained on Nego-lah's website;</li>
                                    <li>Remove any copyright or other proprietary notations from the materials; or</li>
                                    <li>Transfer the materials to another person or "mirror" the materials on any other server.</li>
                                </ul>
                            </section>

                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <circle cx="12" cy="12" r="10" />
                                        <path d="M8 12h8" />
                                    </svg>
                                    Disclaimer
                                </h2>
                                <p>
                                    The materials on Nego-lah's website are provided on an 'as is' basis. Nego-lah makes no warranties, expressed or implied, and hereby disclaims and negates all other warranties including, without limitation, implied warranties or conditions of merchantability, fitness for a particular purpose, or non-infringement of intellectual property or other violation of rights.
                                </p>
                            </section>

                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5" />
                                        <path d="M8.5 8.5v.5" />
                                        <path d="M16 16v.5" />
                                        <path d="M12 12v.5" />
                                        <path d="M8.5 16H9" />
                                        <path d="M16 8.5H15" />
                                    </svg>
                                    Limitations
                                </h2>
                                <p>
                                    In no event shall Nego-lah or its suppliers be liable for any damages (including, without limitation, damages for loss of data or profit, or due to business interruption) arising out of the use or inability to use the materials on Nego-lah's website, even if Nego-lah or a Nego-lah authorized representative has been notified orally or in writing of the possibility of such damage.
                                </p>
                            </section>

                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <path d="m5 12 7-7 7 7" />
                                        <path d="M12 19V5" />
                                    </svg>
                                    Modifications
                                </h2>
                                <p>
                                    Nego-lah may revise these terms of service for its website at any time without notice. By using this website you are agreeing to be bound by the then current version of these terms of service.
                                </p>
                            </section>
                        </div>
                    </div>
                </div>
            </main>

            <footer className="border-t border-[var(--border)] py-6 relative z-10 mt-auto">
                <div className="max-w-6xl mx-auto px-6 flex justify-between items-center text-sm text-[var(--text-muted)]">
                    <p>&copy; Nego-lah {new Date().getFullYear()}</p>
                </div>
            </footer>
        </div>
    )
} 

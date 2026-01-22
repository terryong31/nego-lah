import { useNavigate } from 'react-router-dom'


export function Privacy() {
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
                        <h1 className="text-3xl md:text-4xl font-bold mb-8 text-[var(--text-primary)]">Privacy Policy</h1>

                        <div className="space-y-8 text-[var(--text-secondary)] leading-relaxed">
                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                                        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                                    </svg>
                                    Introduction
                                </h2>
                                <p>
                                    Welcome to Nego-lah ("we," "our," or "us"). <br></br><br></br>We respect your privacy and are committed to protecting your personal data. This privacy policy will inform you as to how we look after your personal data when you visit our website and tell you about your privacy rights and how the law protects you.
                                </p>
                            </section>

                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                        <polyline points="7 10 12 15 17 10" />
                                        <line x1="12" x2="12" y1="15" y2="3" />
                                    </svg>
                                    Data We Collect
                                </h2>
                                <p>
                                    We may collect, use, store and transfer different kinds of personal data about you which we have grouped together follows:
                                    <ul className="list-disc pl-6 mt-4 space-y-2">
                                        <li><strong>Identity Data:</strong> includes first name, last name, username or similar identifier.</li>
                                        <li><strong>Contact Data:</strong> includes email address.</li>
                                        <li><strong>Technical Data:</strong> includes internet protocol (IP) address, your login data, browser type and version, time zone setting and location, browser plug-in types and versions, operating system and platform, and other technology on the devices you use to access this website.</li>
                                    </ul>
                                </p>
                            </section>

                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <circle cx="12" cy="12" r="10" />
                                        <circle cx="12" cy="12" r="4" />
                                        <line x1="21.17" x2="12" y1="8" y2="8" />
                                        <line x1="3.95" x2="8.54" y1="6.06" y2="14" />
                                        <line x1="10.88" x2="15.46" y1="21.94" y2="14" />
                                    </svg>
                                    Google OAuth
                                </h2>
                                <p>
                                    Our service uses Google OAuth for authentication. When you choose to login with Google, we collect your email address and basic profile information (name and profile picture) to create your account and provide a personalized experience. We do not access your Google contracts, drive files, or other private data.
                                </p>
                            </section>

                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
                                    </svg>
                                    How We Use Your Data
                                </h2>
                                <p>
                                    We will only use your personal data when the law allows us to. Most commonly, we will use your personal data in the following circumstances:
                                </p>
                                <ul className="list-disc pl-6 mt-4 space-y-2">
                                    <li><p>Where we need to perform the contract we are about to enter into or have entered into with you.</p></li>
                                    <li><p>Where it is necessary for our legitimate interests (or those of a third party) and your interests and fundamental rights do not override those interests.</p></li>
                                </ul>
                            </section>

                            <section>
                                <h2 className="text-xl font-semibold mb-4 text-[var(--text-primary)] flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-70">
                                        <rect width="20" height="16" x="2" y="4" rx="2" />
                                        <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
                                    </svg>
                                    Contact Us
                                </h2>
                                <p>
                                    If you have any questions about this privacy policy or our privacy practices, please contact us at: <a href="mailto:nego-lah@terryong.me" className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors underline">nego-lah@terryong.me</a>
                                </p>
                            </section>
                        </div>
                    </div>
                </div>
            </main >

            <footer className="border-t border-[var(--border)] py-6 relative z-10 mt-auto">
                <div className="max-w-6xl mx-auto px-6 flex justify-between items-center text-sm text-[var(--text-muted)]">
                    <p>&copy; Nego-lah {new Date().getFullYear()}</p>
                    <div className="flex gap-4">
                        <a href="/privacy" className="hover:text-[var(--text-primary)] transition-colors">Privacy</a>
                        <a href="/terms" className="hover:text-[var(--text-primary)] transition-colors">Terms</a>
                    </div>
                </div>
            </footer>
        </div >
    )
} 

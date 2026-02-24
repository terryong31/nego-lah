import { Card } from '../components/Card'
import { FaLinkedin, FaGithub } from "react-icons/fa";
import { useNavigate } from 'react-router-dom'

export function About() {
    const navigate = useNavigate()

    return (
        <div className="min-h-screen relative flex flex-col pb-20">
            {/* Stars Background */}
            <div className="stars-container">
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="shooting-star"></div>
                <div className="stars"></div>
            </div>

            <header className="liquid-glass-header sticky top-0 z-50">
                <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
                    <a href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
                        <img src="/logo.png" alt="Logo" className="w-8 h-8 object-contain" />
                        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Nego-lah</h1>
                    </a>
                </div>
            </header>

            <main className="flex-1 w-full max-w-3xl mx-auto px-4 py-12 relative z-10 animate-fade-in text-[var(--text-primary)]">
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

                <div className="space-y-8">
                    <Card padding="lg" className="backdrop-blur-xl bg-[var(--card-bg)]/80 border-[var(--border)] shadow-2xl overflow-hidden relative">
                        <div className="mb-12 text-left">
                            <h1 className="text-4xl md:text-5xl font-bold mb-4 tracking-tight">About Nego-lah</h1>
                        </div>

                        {/* Decorative gradient orb */}
                        <div className="absolute -top-32 -right-32 w-64 h-64 bg-indigo-500/20 rounded-full blur-3xl pointer-events-none" />

                        <div className="relative z-10">
                            <h2 className="text-2xl font-bold mb-6 text-[var(--text-primary)]">The Developer Behind the Bots</h2>

                            <div className="space-y-6 text-[var(--text-secondary)] leading-relaxed">
                                <p>
                                    Hi, I'm <strong className="text-[var(--text-primary)] font-medium">Terry Ong (Ong Kok Donq)</strong>.
                                    I'm a final-year Computer Science student at Quest International University in Ipoh, Malaysia,
                                    specializing in building production-ready generative AI systems.
                                </p>

                                <p>
                                    Nego-lah started as an experiment. I wanted to see if I could build a marketplace where an agentic AI
                                    handles complex price negotiations autonomously. What began as a side project eventually grew into
                                    a full-stack application using FastAPI, LangGraph, and specialized vector databases.
                                </p>

                                <p>
                                    When I'm not studying or debugging complex LLM orchestration pipelines, I'm usually competing in AI hackathons.
                                    These experiences push me to constantly refine how I build robust algorithms and user-centric applications.
                                </p>
                            </div>
                        </div>
                    </Card>

                    <Card padding="lg" className="backdrop-blur-xl bg-[var(--bg-secondary)]/50 border-[var(--border)]">
                        <h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">The Tech Stack</h3>
                        <div className="flex flex-wrap gap-2">
                            {['React', 'Tailwind', 'FastAPI', 'LangGraph', 'Pgvector', 'Google Cloud', 'Supabase', 'Stripe'].map(tech => (
                                <span key={tech} className="px-3 py-1.5 text-sm font-medium border border-[var(--border)] rounded-full bg-[var(--card-bg)] text-[var(--text-secondary)] shadow-sm">
                                    {tech}
                                </span>
                            ))}
                        </div>
                    </Card>

                    <div className="flex flex-col sm:flex-row gap-6 justify-center pt-8">
                        <a
                            href="https://github.com/terryong31"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-3xl text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:scale-110 transition-all"
                        >
                            <FaGithub />
                        </a>
                        <a
                            href="https://linkedin.com/in/ongkokdonq"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-3xl text-[var(--text-secondary)] hover:text-[#0A66C2] hover:scale-110 transition-all"
                        >
                            <FaLinkedin />
                        </a>
                    </div>
                </div>
            </main>
        </div>
    )
}
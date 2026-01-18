import type { ReactNode } from 'react'

interface CardProps {
    children: ReactNode
    className?: string
    padding?: 'none' | 'sm' | 'md' | 'lg'
}

export function Card({ children, className = '', padding = 'md' }: CardProps) {
    const paddingStyles = {
        none: '',
        sm: 'p-4',
        md: 'p-6',
        lg: 'p-8'
    }

    return (
        <div
            className={`
        bg-[var(--card-bg)] border border-[var(--border)] rounded-xl
        ${paddingStyles[padding]}
        ${className}
      `}
        >
            {children}
        </div>
    )
}

interface CardHeaderProps {
    title: string
    subtitle?: string
    action?: ReactNode
}

export function CardHeader({ title, subtitle, action }: CardHeaderProps) {
    return (
        <div className="flex items-center justify-between mb-4">
            <div>
                <h2 className="text-lg font-semibold text-zinc-100">{title}</h2>
                {subtitle && (
                    <p className="text-sm text-zinc-500 mt-0.5">{subtitle}</p>
                )}
            </div>
            {action && <div>{action}</div>}
        </div>
    )
}

import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    children: ReactNode
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'link' | 'filled'
    size?: 'sm' | 'md' | 'lg'
    fullWidth?: boolean
}

export function Button({
    children,
    variant = 'primary',
    size = 'md',
    fullWidth = false,
    className = '',
    disabled,
    ...props
}: ButtonProps) {
    const sizes = {
        sm: 'text-sm',
        md: 'text-sm',
        lg: 'text-base'
    }

    const sizesPadded = {
        sm: 'px-3 py-1.5 text-sm',
        md: 'px-4 py-2 text-sm',
        lg: 'px-6 py-3 text-base'
    }

    const widthClass = fullWidth ? 'w-full' : ''

    // Primary & Link variants - text only with underline animation
    if (variant === 'primary' || variant === 'link') {
        return (
            <button
                className={`
                    relative font-medium text-[var(--text-primary)] 
                    disabled:opacity-50 disabled:cursor-not-allowed
                    focus:outline-none
                    group
                    ${sizes[size]}
                    ${widthClass}
                    ${className}
                `}
                disabled={disabled}
                {...props}
            >
                {children}
                <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-primary)] transition-all duration-300 group-hover:w-full" />
            </button>
        )
    }

    // Secondary variant - text only with underline
    if (variant === 'secondary') {
        return (
            <button
                className={`
                    relative font-medium text-[var(--text-secondary)]
                    disabled:opacity-50 disabled:cursor-not-allowed
                    focus:outline-none
                    group
                    ${sizes[size]}
                    ${widthClass}
                    ${className}
                `}
                disabled={disabled}
                {...props}
            >
                {children}
                <span className="absolute left-0 bottom-0 w-0 h-[1px] bg-[var(--text-secondary)] transition-all duration-300 group-hover:w-full" />
            </button>
        )
    }

    // Filled variant - theme-aware: dark in light mode, light in dark mode
    if (variant === 'filled') {
        return (
            <button
                className={`
                    font-medium rounded-lg transition-all
                    bg-[var(--btn-filled-bg)] hover:bg-[var(--btn-filled-bg-hover)] text-[var(--btn-filled-text)] hover:text-[var(--btn-filled-text-hover)]
                    disabled:opacity-50 disabled:cursor-not-allowed
                    focus:outline-none
                    ${sizesPadded[size]}
                    ${widthClass}
                    ${className}
                `}
                disabled={disabled}
                {...props}
            >
                {children}
            </button>
        )
    }

    // Ghost and Danger variants
    const baseStyles = 'font-medium rounded-lg transition-colors focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed'

    const variants = {
        ghost: 'bg-transparent hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]',
        danger: 'bg-red-600 hover:bg-red-700 text-white'
    }

    return (
        <button
            className={`${baseStyles} ${variants[variant]} ${sizesPadded[size]} ${widthClass} ${className}`}
            disabled={disabled}
            {...props}
        >
            {children}
        </button>
    )
}


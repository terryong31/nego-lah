
import { Button } from './Button'

interface ConfirmationModalProps {
    isOpen: boolean
    onClose: () => void
    onConfirm: () => void
    title: string
    message: string
    isLoading?: boolean
    confirmText?: string
    cancelText?: string
}

export function ConfirmationModal({
    isOpen,
    onClose,
    onConfirm,
    title,
    message,
    isLoading = false,
    confirmText = 'Yes',
    cancelText = 'No'
}: ConfirmationModalProps) {
    if (!isOpen) return null

    return (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
            <div className="bg-[var(--card-bg)] border border-[var(--border)] rounded-2xl p-6 max-w-sm w-full shadow-2xl animate-slide-up transform transition-all">
                <h3 className="text-xl font-bold text-[var(--text-primary)] mb-2">
                    {title}
                </h3>
                <p className="text-[var(--text-secondary)] mb-6">
                    {message}
                </p>
                <div className="flex justify-end gap-3">
                    <Button
                        variant="ghost"
                        onClick={onClose}
                        disabled={isLoading}
                    >
                        {cancelText}
                    </Button>
                    <Button
                        variant="danger"
                        onClick={onConfirm}
                        disabled={isLoading}
                        className="min-w-[80px]"
                    >
                        {isLoading ? (
                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin mx-auto" />
                        ) : (
                            confirmText
                        )}
                    </Button>
                </div>
            </div>
        </div>
    )
}

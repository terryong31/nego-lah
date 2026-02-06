import { useState, useRef, useCallback } from 'react'

interface UploadingFile {
    file: File
    progress: number
    status: 'uploading' | 'finished'
}

interface ImageDropzoneProps {
    onFilesSelected: (files: File[]) => void
    isAnalyzing?: boolean
    disabled?: boolean
}

export function ImageDropzone({ onFilesSelected, isAnalyzing = false, disabled = false }: ImageDropzoneProps) {
    const [isDragging, setIsDragging] = useState(false)
    const [files, setFiles] = useState<UploadingFile[]>([])
    const inputRef = useRef<HTMLInputElement>(null)

    const handleFiles = useCallback((selectedFiles: FileList | null) => {
        if (!selectedFiles || selectedFiles.length === 0) return

        const fileArray = Array.from(selectedFiles)

        // Create uploading file entries with simulated progress
        const newFiles: UploadingFile[] = fileArray.map(file => ({
            file,
            progress: 0,
            status: 'uploading' as const
        }))

        setFiles(prev => [...prev, ...newFiles])

        // Simulate upload progress for each file
        newFiles.forEach((uploadingFile, index) => {
            const startTime = Date.now()
            const duration = 800 + Math.random() * 400 // 800-1200ms

            const updateProgress = () => {
                const elapsed = Date.now() - startTime
                const progress = Math.min(100, (elapsed / duration) * 100)

                setFiles(prev => prev.map(f =>
                    f.file === uploadingFile.file
                        ? { ...f, progress, status: progress >= 100 ? 'finished' : 'uploading' }
                        : f
                ))

                if (progress < 100) {
                    requestAnimationFrame(updateProgress)
                }
            }

            // Stagger start times
            setTimeout(() => requestAnimationFrame(updateProgress), index * 100)
        })

        // Call parent callback with files
        onFilesSelected(fileArray)
    }, [onFilesSelected])

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        if (!disabled) setIsDragging(true)
    }, [disabled])

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragging(false)
    }, [])

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragging(false)
        if (!disabled) handleFiles(e.dataTransfer.files)
    }, [disabled, handleFiles])

    const uploadingFiles = files.filter(f => f.status === 'uploading')
    const finishedFiles = files.filter(f => f.status === 'finished')

    return (
        <div className="space-y-6">
            {/* Dropzone */}
            <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => !disabled && inputRef.current?.click()}
                className={`
                    dropzone relative rounded-xl border-2 border-dashed p-8 text-center cursor-pointer
                    transition-all duration-200
                    ${isDragging ? 'dropzone-active border-[var(--accent)] bg-[var(--accent)]/10' : 'border-[var(--border)] hover:border-[var(--text-muted)]'}
                    ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
                `}
            >
                <input
                    ref={inputRef}
                    type="file"
                    multiple
                    accept="image/jpeg,image/png,image/gif"
                    onChange={(e) => handleFiles(e.target.files)}
                    className="hidden"
                    disabled={disabled}
                />

                {/* Upload Icon */}
                <div className="flex justify-center mb-3">
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="32"
                        height="32"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="text-[var(--text-muted)]"
                    >
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="17 8 12 3 7 8" />
                        <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                </div>

                <p className="text-[var(--text-primary)] font-medium">
                    Drop files here or <span className="text-[var(--accent)] underline">browse files</span> to add
                </p>
                <p className="text-sm text-[var(--text-muted)] mt-1">
                    Supported: JPG, PNG, GIF (max 10 MB)
                </p>
            </div>

            {/* Uploading Section */}
            {uploadingFiles.length > 0 && (
                <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        <span className="uppercase tracking-wider font-medium">Uploading</span>
                    </div>
                    {uploadingFiles.map((f, i) => (
                        <div key={`uploading-${i}`} className="upload-file-item">
                            <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded bg-[var(--bg-tertiary)] flex items-center justify-center flex-shrink-0">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-[var(--text-muted)]">
                                        <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
                                        <polyline points="14 2 14 8 20 8" />
                                    </svg>
                                </div>
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm text-[var(--text-primary)] truncate">{f.file.name}</p>
                                    <div className="mt-1 h-1.5 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
                                        <div
                                            className="h-full bg-[var(--text-primary)] rounded-full transition-all duration-100"
                                            style={{ width: `${f.progress}%` }}
                                        />
                                    </div>
                                </div>
                                <span className="text-sm text-[var(--text-muted)] flex-shrink-0">{Math.round(f.progress)}%</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Finished Section */}
            {finishedFiles.length > 0 && (
                <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                            <polyline points="22 4 12 14.01 9 11.01" />
                        </svg>
                        <span className="uppercase tracking-wider font-medium">Ready ({finishedFiles.length} images)</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {finishedFiles.map((f, i) => (
                            <div key={`finished-${i}`} className="w-12 h-12 rounded-lg overflow-hidden bg-[var(--bg-tertiary)]">
                                <img
                                    src={URL.createObjectURL(f.file)}
                                    alt={f.file.name}
                                    className="w-full h-full object-cover"
                                />
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Analyzing Indicator */}
            {isAnalyzing && finishedFiles.length > 0 && (
                <div className="flex items-center justify-center gap-3 py-4 text-[var(--text-primary)]">
                    <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
                    <span className="font-medium">AI is analyzing your images...</span>
                </div>
            )}
        </div>
    )
}

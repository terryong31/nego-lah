export interface DownscaleImageOptions {
  /** Longest edge in pixels (defaults to 2048 to match backend MAX_ITEM_EDGE). */
  maxEdge?: number
  /** JPEG encoding quality from 0 to 1 (defaults to 0.82 to match backend JPEG_QUALITY). */
  quality?: number
  /** Files already within maxEdge and smaller than this byte floor are left untouched. */
  sizeFloor?: number
}

const DEFAULT_MAX_EDGE = 2048
const DEFAULT_QUALITY = 0.82
const DEFAULT_SIZE_FLOOR = 400_000

function toJpgFilename(name: string): string {
  const dot = name.lastIndexOf('.')
  const stem = dot > 0 ? name.slice(0, dot) : name
  return `${stem || 'photo'}.jpg`
}

/**
 * Downscale and JPEG-compress an image in the browser before upload so multi-photo
 * multipart payloads stay well under the 15 MB edge/API body limit.
 * Falls back to the original `File` when decoding is unavailable, fails, or produces
 * a larger output.
 */
export async function downscaleImage(
  file: File,
  options: DownscaleImageOptions = {}
): Promise<File> {
  if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return file

  const maxEdge = options.maxEdge ?? DEFAULT_MAX_EDGE
  const quality = options.quality ?? DEFAULT_QUALITY
  const sizeFloor = options.sizeFloor ?? DEFAULT_SIZE_FLOOR

  let bitmap: ImageBitmap | undefined
  try {
    bitmap = await createImageBitmap(file)
    const longest = Math.max(bitmap.width, bitmap.height)
    const scale = Math.min(1, maxEdge / longest)
    if (scale === 1 && file.size < sizeFloor) return file

    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)

    const blob = await new Promise<Blob | null>(resolve =>
      canvas.toBlob(resolve, 'image/jpeg', quality)
    )
    if (!blob || blob.size >= file.size) return file

    return new File([blob], toJpgFilename(file.name), {
      type: 'image/jpeg',
      lastModified: file.lastModified
    })
  } catch {
    return file
  } finally {
    bitmap?.close()
  }
}

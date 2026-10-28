import { afterEach, describe, expect, it, vi } from 'vitest'
import { downscaleImage } from '~/utils/downscaleImage'

function makeFile(name: string, byteLength: number, type = 'image/png'): File {
  return new File([new Uint8Array(byteLength)], name, { type })
}

describe('utils/downscaleImage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('returns the original file when createImageBitmap is unavailable', async () => {
    vi.stubGlobal('createImageBitmap', undefined)
    const file = makeFile('raw.png', 2_000_000)

    const result = await downscaleImage(file)

    expect(result).toBe(file)
  })

  it('downscales an image whose longest edge exceeds maxEdge and returns a smaller .jpg File', async () => {
    const closeSpy = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({
      width: 4032,
      height: 3024,
      close: closeSpy
    }))

    const drawImageSpy = vi.fn()
    let capturedWidth = 0
    let capturedHeight = 0
    const origCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'canvas') {
        const fakeCanvas = {
          set width(w: number) { capturedWidth = w },
          get width() { return capturedWidth },
          set height(h: number) { capturedHeight = h },
          get height() { return capturedHeight },
          getContext: () => ({ drawImage: drawImageSpy }),
          toBlob: (cb: (b: Blob | null) => void, type?: string, quality?: number) => {
            expect(type).toBe('image/jpeg')
            expect(quality).toBe(0.82)
            cb(new Blob([new Uint8Array(150_000)], { type: 'image/jpeg' }))
          }
        }
        return fakeCanvas as unknown as HTMLCanvasElement
      }
      return origCreateElement(tag)
    })

    const file = makeFile('guitar_photo.PNG', 3_500_000)
    const result = await downscaleImage(file) // default maxEdge = 2048

    expect(capturedWidth).toBe(2048)
    expect(capturedHeight).toBe(1536)
    expect(drawImageSpy).toHaveBeenCalledOnce()
    expect(closeSpy).toHaveBeenCalledOnce()
    expect(result).toBeInstanceOf(File)
    expect(result).not.toBe(file)
    expect(result.size).toBe(150_000)
    expect(result.name).toBe('guitar_photo.jpg')
    expect(result.type).toBe('image/jpeg')
  })

  it('leaves a small file untouched when its dimensions are already within maxEdge', async () => {
    const closeSpy = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({
      width: 1200,
      height: 900,
      close: closeSpy
    }))
    const createElSpy = vi.spyOn(document, 'createElement')

    const file = makeFile('small.jpg', 120_000, 'image/jpeg')
    const result = await downscaleImage(file)

    expect(result).toBe(file)
    expect(createElSpy).not.toHaveBeenCalled()
    expect(closeSpy).toHaveBeenCalledOnce()
  })

  it('re-encodes a file within maxEdge when its byte size is above sizeFloor', async () => {
    const closeSpy = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({
      width: 1600,
      height: 1200,
      close: closeSpy
    }))

    vi.spyOn(document, 'createElement').mockImplementation(() => ({
      width: 0,
      height: 0,
      getContext: () => ({ drawImage: vi.fn() }),
      toBlob: (cb: (b: Blob | null) => void) =>
        cb(new Blob([new Uint8Array(180_000)], { type: 'image/jpeg' }))
    }) as unknown as HTMLCanvasElement)

    const file = makeFile('uncompressed.png', 1_200_000)
    const result = await downscaleImage(file)

    expect(result.size).toBe(180_000)
    expect(result.name).toBe('uncompressed.jpg')
    expect(closeSpy).toHaveBeenCalledOnce()
  })

  it('returns the original file when the re-encoded blob is not smaller', async () => {
    const closeSpy = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({
      width: 3000,
      height: 2000,
      close: closeSpy
    }))

    vi.spyOn(document, 'createElement').mockImplementation(() => ({
      width: 0,
      height: 0,
      getContext: () => ({ drawImage: vi.fn() }),
      toBlob: (cb: (b: Blob | null) => void) =>
        cb(new Blob([new Uint8Array(600_000)], { type: 'image/jpeg' }))
    }) as unknown as HTMLCanvasElement)

    const file = makeFile('already-tight.jpg', 500_000, 'image/jpeg')
    const result = await downscaleImage(file)

    expect(result).toBe(file)
    expect(closeSpy).toHaveBeenCalledOnce()
  })

  it('returns the original file when createImageBitmap throws (e.g. undecodable HEIC)', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockRejectedValue(new Error('decode failed')))
    const file = makeFile('photo.heic', 2_500_000, 'image/heic')

    const result = await downscaleImage(file)

    expect(result).toBe(file)
  })
})

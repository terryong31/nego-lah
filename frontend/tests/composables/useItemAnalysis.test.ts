import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { watch } from 'vue'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { useItemAnalysis, type AnalyzePatch } from '../../app/composables/useItemAnalysis'

// `fetch` is a runtime global here, not a Nuxt auto-import, so stub it directly
// (same reasoning as tests/composables/useAdminApi.test.ts does for `$fetch`).
const fetchMock = vi.fn()
const adminCallMock = vi.fn()

mockNuxtImport('useAdminApi', () => () => ({ call: adminCallMock }))

/** Build a Response-like object whose body streams the given SSE chunks. */
function sseResponse(chunks: string[], { ok = true, status = 200 } = {}) {
  const encoder = new TextEncoder()
  let i = 0
  return {
    ok,
    status,
    json: async () => ({}),
    body: {
      getReader: () => ({
        read: async () => (
          i < chunks.length
            ? { done: false, value: encoder.encode(chunks[i++]) }
            : { done: true, value: undefined }
        )
      })
    }
  }
}

function frame(event: Record<string, unknown>) {
  return `data: ${JSON.stringify(event)}\n\n`
}

const DONE = frame({
  stage: 'done',
  progress: 100,
  message: 'Done',
  result: { name: 'Brass Lamp', description: 'Warm glow' }
})

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  // jsdom has no real image decoder; without createImageBitmap the composable
  // sends the original files through untouched, which is the path under test.
  vi.stubGlobal('createImageBitmap', undefined)
})

afterEach(() => {
  fetchMock.mockReset()
  adminCallMock.mockReset()
  vi.useRealTimers()
})

describe('composables/useItemAnalysis', () => {
  it('POSTs the photos to the streaming endpoint with the admin cookie', async () => {
    fetchMock.mockResolvedValueOnce(sseResponse([DONE]))
    const { analyze } = useItemAnalysis()

    await analyze([new File(['x'], 'lamp.png', { type: 'image/png' })])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, opts] = fetchMock.mock.calls[0]!
    expect(url).toBe('http://localhost:8000/admin/analyze-image/stream')
    expect(opts.method).toBe('POST')
    expect(opts.credentials).toBe('include')
    expect(opts.body).toBeInstanceOf(FormData)
    expect((opts.body as FormData).getAll('images')).toHaveLength(1)
  })

  it('returns the result carried by the final `done` event', async () => {
    fetchMock.mockResolvedValueOnce(sseResponse([DONE]))
    const { analyze } = useItemAnalysis()

    const result = await analyze([new File(['x'], 'lamp.png')])

    expect(result).toEqual({ name: 'Brass Lamp', description: 'Warm glow' })
  })

  it('tracks progress and the stage message from each event as it arrives', async () => {
    const seen: number[] = []
    fetchMock.mockResolvedValueOnce(sseResponse([
      frame({ stage: 'uploaded', progress: 10, message: 'Photos received' }),
      frame({ stage: 'identified', progress: 50, message: 'Identified: Brass Lamp' }),
      DONE
    ]))

    const { analyze, progress, stageMessage } = useItemAnalysis()
    const stop = watch(progress, v => seen.push(v))

    const result = await analyze([new File(['x'], 'lamp.png')])
    stop()

    expect(seen).toContain(10)
    expect(seen).toContain(50)
    expect(progress.value).toBe(100)
    expect(stageMessage.value).toBe('Done')
    expect(result.name).toBe('Brass Lamp')
  })

  it('forwards each event patch to the caller so fields fill in early', async () => {
    const patches: AnalyzePatch[] = []
    fetchMock.mockResolvedValueOnce(sseResponse([
      frame({ stage: 'identified', progress: 50, message: 'Identified', patch: { name: 'Brass Lamp' } }),
      frame({ stage: 'priced', progress: 72, message: 'Priced', patch: { price: 120 } }),
      DONE
    ]))

    const { analyze } = useItemAnalysis()
    await analyze([new File(['x'], 'lamp.png')], p => patches.push(p))

    expect(patches).toEqual([{ name: 'Brass Lamp' }, { price: 120 }])
  })

  it('handles events split across chunk boundaries', async () => {
    const whole = frame({ stage: 'identified', progress: 50, message: 'Identified' }) + DONE
    const split = Math.floor(whole.length / 3)
    fetchMock.mockResolvedValueOnce(sseResponse([whole.slice(0, split), whole.slice(split)]))

    const { analyze } = useItemAnalysis()
    const result = await analyze([new File(['x'], 'lamp.png')])

    expect(result.name).toBe('Brass Lamp')
  })

  it('skips frames that are not valid JSON rather than failing the run', async () => {
    fetchMock.mockResolvedValueOnce(sseResponse(['data: {not json\n\n', ': keep-alive\n\n', DONE]))

    const { analyze } = useItemAnalysis()
    const result = await analyze([new File(['x'], 'lamp.png')])

    expect(result.name).toBe('Brass Lamp')
  })

  it('rejects with the message from an `error` event', async () => {
    fetchMock.mockResolvedValueOnce(sseResponse([
      frame({ stage: 'error', progress: 100, message: 'Failed to analyze image: gemini exploded' })
    ]))

    const { analyze } = useItemAnalysis()

    await expect(analyze([new File(['x'], 'lamp.png')]))
      .rejects.toThrow('Failed to analyze image: gemini exploded')
  })

  it('rejects when the stream ends without a result', async () => {
    fetchMock.mockResolvedValueOnce(sseResponse([
      frame({ stage: 'identified', progress: 50, message: 'Identified' })
    ]))

    const { analyze } = useItemAnalysis()

    await expect(analyze([new File(['x'], 'lamp.png')]))
      .rejects.toThrow('Analysis ended before returning a result')
  })

  it('surfaces the API detail on a non-OK response', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: 'Server said no' })
    })

    const { analyze } = useItemAnalysis()

    await expect(analyze([new File(['x'], 'lamp.png')])).rejects.toThrow('Server said no')
  })

  it('falls back to the status code when the error body is not JSON', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('not json')
      }
    })

    const { analyze } = useItemAnalysis()

    await expect(analyze([new File(['x'], 'lamp.png')])).rejects.toThrow('Analysis failed (502)')
  })

  it('falls back to the non-streaming endpoint when the response has no readable body', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, body: null, json: async () => ({}) })
    adminCallMock.mockResolvedValueOnce({ name: 'Fallback Lamp' })

    const { analyze } = useItemAnalysis()
    const result = await analyze([new File(['x'], 'lamp.png')])

    expect(adminCallMock).toHaveBeenCalledWith('/analyze-image', expect.objectContaining({ method: 'POST' }))
    expect(result).toEqual({ name: 'Fallback Lamp' })
  })

  it('clears isAnalyzing whether the run succeeds or fails', async () => {
    const { analyze, isAnalyzing } = useItemAnalysis()

    fetchMock.mockResolvedValueOnce(sseResponse([DONE]))
    await analyze([new File(['x'], 'lamp.png')])
    expect(isAnalyzing.value).toBe(false)

    fetchMock.mockRejectedValueOnce(new Error('network down'))
    await expect(analyze([new File(['x'], 'lamp.png')])).rejects.toThrow('network down')
    expect(isAnalyzing.value).toBe(false)
  })

  it('creeps the bar toward - but never past - the next milestone while a stage runs', async () => {
    vi.useFakeTimers()
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })

    const encoder = new TextEncoder()
    let stage = 0
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({}),
      body: {
        getReader: () => ({
          read: async () => {
            if (stage === 0) {
              stage = 1
              // "identified" lands at 50; the next milestone is 50 + 22 = 72.
              return { done: false, value: encoder.encode(frame({ stage: 'identified', progress: 50, message: 'Identified' })) }
            }
            if (stage === 1) {
              stage = 2
              await gate
              return { done: false, value: encoder.encode(DONE) }
            }
            return { done: true, value: undefined }
          }
        })
      }
    })

    const { analyze, progress } = useItemAnalysis()
    const pending = analyze([new File(['x'], 'lamp.png')])

    await vi.advanceTimersByTimeAsync(0)
    expect(progress.value).toBe(50)

    // Each 500ms tick nudges it up by one…
    await vi.advanceTimersByTimeAsync(500)
    expect(progress.value).toBe(51)

    // …and it stalls one short of 72 instead of claiming the stage finished.
    await vi.advanceTimersByTimeAsync(500 * 60)
    expect(progress.value).toBe(71)

    release()
    await vi.advanceTimersByTimeAsync(0)
    await pending

    expect(progress.value).toBe(100)
  })
})

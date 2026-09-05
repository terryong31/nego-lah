// AI listing analysis for the admin "upload item" flow.
//
// Three things make this fast enough to watch:
//   1. Photos are downscaled in the browser before they're sent. A phone photo
//      is ~4MB; the vision model sees no more detail at 1024px than it does at
//      4032px, and the upload is what dominates on a slow connection.
//   2. The downscales run concurrently, as does the backend pipeline
//      (see agent/tools/listing_pipeline.py).
//   3. The backend streams progress over SSE as each stage actually lands, so
//      the bar reports real state instead of animating a guess.

export interface AnalyzeResult {
  name?: string
  description?: string
  condition?: string
  category?: string
  market_data?: { suggested_listing?: number } | null
  translations?: Record<string, ItemTranslation>
}

// A partial form update the backend hands over early, before the whole
// analysis is finished — so fields fill in as their stage completes.
export interface AnalyzePatch {
  name?: string
  description?: string
  condition?: string
  price?: number
  translations?: Record<string, ItemTranslation>
}

interface AnalyzeEvent {
  stage: string
  progress: number
  message: string
  patch?: AnalyzePatch
  result?: AnalyzeResult
}

// Longest edge (px) any photo is scaled to before being sent for analysis.
const MAX_ANALYSIS_EDGE = 1024
// Photos already smaller than this are sent untouched — re-encoding them costs
// more than it saves.
const DOWNSCALE_SIZE_FLOOR = 400_000

// How much headroom the bar may creep through while a stage is still running,
// keyed by the stage that just finished. The bar never reaches the next
// milestone on its own — only a real event gets it there.
const STAGE_HEADROOM: Record<string, number> = {
  uploaded: 10,
  identifying: 30,
  identified: 22,
  described: 22,
  priced: 22
}

/** Shrink an image so the analysis upload stays small. Falls back to the original. */
async function downscale(file: File): Promise<Blob> {
  if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return file

  let bitmap: ImageBitmap | undefined
  try {
    bitmap = await createImageBitmap(file)
    const longest = Math.max(bitmap.width, bitmap.height)
    const scale = Math.min(1, MAX_ANALYSIS_EDGE / longest)
    if (scale === 1 && file.size < DOWNSCALE_SIZE_FLOOR) return file

    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)

    const blob = await new Promise<Blob | null>(resolve =>
      canvas.toBlob(resolve, 'image/jpeg', 0.82)
    )
    return blob && blob.size < file.size ? blob : file
  } catch {
    return file
  } finally {
    bitmap?.close()
  }
}

export const useItemAnalysis = () => {
  const config = useRuntimeConfig()
  const { call, ensureCsrfToken: adminEnsureCsrf } = useAdminApi()

  const isAnalyzing = ref(false)
  const progress = ref(0)
  const stageMessage = ref('')

  // Between two real events the bar creeps toward — but never reaches — the
  // next milestone, so a slow stage still looks alive without lying about
  // having finished.
  let creepTimer: ReturnType<typeof setInterval> | null = null

  function stopCreep() {
    if (creepTimer) clearInterval(creepTimer)
    creepTimer = null
  }

  function creepToward(nextMilestone: number) {
    stopCreep()
    // Stop one short of the milestone: only a real event may claim it.
    const ceiling = Math.min(99, nextMilestone - 1)
    creepTimer = setInterval(() => {
      if (progress.value < ceiling) progress.value += 1
    }, 500)
  }

  function applyEvent(event: AnalyzeEvent, onPatch?: (patch: AnalyzePatch) => void) {
    progress.value = Math.max(progress.value, event.progress)
    stageMessage.value = event.message
    if (event.patch) onPatch?.(event.patch)
    creepToward(event.progress + (STAGE_HEADROOM[event.stage] ?? 5))
  }

  /** Read an SSE body, applying each event as it arrives. Returns the final result. */
  async function consumeStream(
    body: ReadableStream<Uint8Array>,
    onPatch?: (patch: AnalyzePatch) => void
  ): Promise<AnalyzeResult> {
    const reader = body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: AnalyzeResult | null = null
    let failure: string | null = null

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE frames are separated by a blank line.
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''

      for (const frame of frames) {
        const line = frame.split('\n').find(l => l.startsWith('data:'))
        if (!line) continue

        let event: AnalyzeEvent
        try {
          event = JSON.parse(line.slice(5).trim())
        } catch {
          continue
        }

        if (event.stage === 'error') {
          failure = event.message
          continue
        }
        applyEvent(event, onPatch)
        if (event.result) result = event.result
      }
    }

    if (failure) throw new Error(failure)
    if (!result) throw new Error('Analysis ended before returning a result')
    return result
  }

  /**
   * Analyze the given photos and return the detected listing details.
   *
   * @param files photos to analyze
   * @param onPatch called as individual fields become available, before the
   *   whole analysis is done
   * @param language target language for AI generation ('en', 'ms', 'zh')
   */
  async function analyze(
    files: File[],
    onPatch?: (patch: AnalyzePatch) => void,
    language: string = 'all'
  ): Promise<AnalyzeResult> {
    isAnalyzing.value = true
    progress.value = 0
    stageMessage.value = 'Preparing photos…'

    try {
      const shrunk = await Promise.all(files.map(downscale))
      const fd = new FormData()
      shrunk.forEach((blob, i) => fd.append('images', blob, files[i]?.name ?? `photo-${i}.jpg`))
      fd.append('language', language)

      progress.value = 5
      stageMessage.value = 'Uploading photos…'

      const csrfToken = adminEnsureCsrf ? await adminEnsureCsrf() : getCsrfToken()
      const headers: Record<string, string> = {}
      if (csrfToken) {
        headers['X-CSRF-Token'] = csrfToken
      }

      let res = await fetch(`${config.public.apiBaseUrl}/admin/analyze-image/stream`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: fd
      })

      if (res.status === 403) {
        try {
          const fresh = await $fetch<{ csrf_token: string }>(`${config.public.apiBaseUrl}/admin/auth/csrf`, {
            credentials: 'include'
          })
          if (fresh?.csrf_token) {
            headers['X-CSRF-Token'] = fresh.csrf_token
            res = await fetch(`${config.public.apiBaseUrl}/admin/analyze-image/stream`, {
              method: 'POST',
              credentials: 'include',
              headers,
              body: fd
            })
          }
        } catch {
          // Fall through to error handler
        }
      }

      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        throw new Error(detail?.detail || `Analysis failed (${res.status})`)
      }

      // Any environment that can't hand us a readable body (an old proxy that
      // buffers, a polyfilled fetch) still gets an answer, just without the
      // live progress.
      if (!res.body) {
        stageMessage.value = 'Analyzing…'
        return await call<AnalyzeResult>('/analyze-image', { method: 'POST', body: fd })
      }

      const result = await consumeStream(res.body, onPatch)
      progress.value = 100
      stageMessage.value = 'Done'
      return result
    } finally {
      stopCreep()
      isAnalyzing.value = false
    }
  }

  // Only when there's a scope to tie to — this is also callable standalone.
  if (getCurrentScope()) onScopeDispose(stopCreep)

  return { analyze, isAnalyzing, progress, stageMessage }
}

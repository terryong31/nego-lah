import { ref, computed } from 'vue'

const token = ref<string | undefined>(undefined)

export function useTurnstileToken() {
  const isEnabled = computed(() => {
    try {
      const config = useRuntimeConfig()
      if (typeof config?.public?.turnstileEnabled === 'boolean') {
        return config.public.turnstileEnabled
      }
    } catch {
      // Fallback if useRuntimeConfig is not available
    }
    return process.env.NODE_ENV === 'production'
  })

  const isReady = computed(() => Boolean(token.value))

  function setToken(newToken: string | undefined) {
    token.value = newToken
  }

  function clearToken() {
    token.value = undefined
  }

  return {
    token,
    isReady,
    isEnabled,
    setToken,
    clearToken
  }
}

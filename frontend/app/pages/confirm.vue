<script setup lang="ts">
import { safeRedirectPath } from '~/utils/auth'

/**
 * The landing screen after an emailed link.
 *
 * This page used to perform the auth exchange itself — 380 lines of reading
 * `?code=` / `#access_token=` out of the URL in three places, calling
 * `exchangeCodeForSession` or `verifyOtp`, and waiting for a session to appear.
 * Since SPEC-093 the backend does all of that: Supabase redirects to
 * `GET /auth/callback` on the API, which redeems the link, sets the session
 * cookie and 302s here with nothing but `?status=`. There is no credential in
 * this URL and nothing for this page to exchange.
 *
 * What is left is the confirmation screen itself, plus a forwarder for links
 * that were already in someone's inbox when this shipped and still point at the
 * SPA.
 */
const { t } = useI18n()
const config = useRuntimeConfig()
const route = useRoute()
const router = useRouter()
const { fetchSession } = useAuth()

const status = ref<'loading' | 'success' | 'error'>('loading')
const message = ref('')

function legacyCallbackUrl(): string | null {
  const code = route.query.code
  const tokenHash = route.query.token_hash
  if (typeof code !== 'string' && typeof tokenHash !== 'string') return null

  // Hand it to the API, which owns the exchange now. A link minted before this
  // shipped still works; it just takes one extra redirect.
  const url = new URL(`${config.public.apiBaseUrl}/auth/callback`)
  for (const [key, value] of Object.entries(route.query)) {
    if (typeof value === 'string') url.searchParams.set(key, value)
  }
  return url.toString()
}

onMounted(async () => {
  const legacy = legacyCallbackUrl()
  if (legacy) {
    window.location.replace(legacy)
    return
  }

  // `link_invalid` is our own callback's verdict; `otp_expired` is the code
  // Supabase puts on a link that was already used or has aged out, which is
  // what a legacy link forwarded here by the global middleware carries.
  const error = route.query.error
  const errorCode = route.query.error_code
  if (typeof error === 'string' && error) {
    const expired = error === 'link_invalid' || errorCode === 'otp_expired'
    status.value = 'error'
    message.value = expired ? t('auth.linkExpired') : t('auth.confirmFailedDesc')
    return
  }

  // The cookie was set on the redirect that brought us here, so this is the
  // first chance to learn who it belongs to.
  await fetchSession()
  status.value = 'success'
})

const redirectTarget = computed(() => safeRedirectPath(route.query.redirect) ?? '/')

useSeoMeta({ title: () => t('auth.emailConfirmedTitle') })
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[70vh] gap-4 p-4">
    <UCard class="w-full max-w-md text-center">
      <div
        v-if="status === 'loading'"
        class="flex flex-col items-center gap-3 py-6"
      >
        <UIcon
          name="i-lucide-loader-circle"
          class="size-8 animate-spin text-primary"
        />
        <p class="text-muted">
          {{ $t('auth.confirmingDesc') }}
        </p>
      </div>

      <div
        v-else-if="status === 'success'"
        class="flex flex-col items-center gap-3 py-6"
      >
        <UIcon
          name="i-lucide-circle-check"
          class="size-10 text-primary"
        />
        <h1 class="text-lg font-semibold">
          {{ $t('auth.emailConfirmedTitle') }}
        </h1>
        <p class="text-muted">
          {{ $t('auth.emailConfirmedDesc') }}
        </p>
        <UButton
          :to="redirectTarget"
          color="primary"
          @click="router.replace(redirectTarget)"
        >
          {{ $t('auth.continueToStore') }}
        </UButton>
      </div>

      <div
        v-else
        class="flex flex-col items-center gap-3 py-6"
      >
        <UIcon
          name="i-lucide-circle-alert"
          class="size-10 text-error"
        />
        <h1 class="text-lg font-semibold">
          {{ $t('auth.confirmFailedTitle') }}
        </h1>
        <p class="text-muted">
          {{ message }}
        </p>
        <UButton
          to="/login"
          color="primary"
        >
          {{ $t('auth.loginTitle') }}
        </UButton>
      </div>
    </UCard>
  </div>
</template>

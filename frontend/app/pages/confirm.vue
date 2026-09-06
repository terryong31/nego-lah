<script setup lang="ts">
import type { EmailOtpType, Session } from '@supabase/supabase-js'
import { loginRedirect, safeRedirectPath } from '~/utils/auth'

const { t } = useI18n()
const user = useSupabaseUser()
const supabase = useSupabaseClient()
const route = useRoute()
const router = useRouter()
const { initLanguage } = useLanguage()

type ConfirmStatus = 'loading' | 'success' | 'error'

type AmrEntry = string | { method?: string }

/**
 * Supabase returns the callback params in the query string on the PKCE flow and
 * in the URL fragment on the implicit one, and `route.query` only ever sees the
 * former — so every param is looked up across all three sources.
 */
function readParam(name: string): string | null {
  const fromRoute = route.query[name]
  if (typeof fromRoute === 'string' && fromRoute) return fromRoute
  if (typeof window === 'undefined') return null
  const fromSearch = new URLSearchParams(window.location.search).get(name)
  if (fromSearch) return fromSearch
  if (!window.location.hash) return null
  return new URLSearchParams(window.location.hash.replace(/^#/, '')).get(name)
}

function getLocalizedError(rawCode?: string | null, rawDesc?: string | null) {
  const code = (rawCode || '').toLowerCase()
  const desc = (rawDesc || '').toLowerCase()

  if (code === 'otp_expired' || desc.includes('expired') || desc.includes('invalid')) {
    return t('auth.linkExpired')
  }
  if (desc) {
    return t('auth.confirmFailedDesc')
  }
  return null
}

const status = ref<ConfirmStatus>(readParam('error') || readParam('error_code') ? 'error' : 'loading')
const errorMessage = ref<string | null>(null)
const countdown = ref(5)
let timer: ReturnType<typeof setInterval> | null = null

// How long to give the router redirect before forcing a hard navigation.
const WATCHDOG_MS = 2500
let watchdog: ReturnType<typeof setTimeout> | null = null

// Both are resolved during setup rather than in `onMounted`, because the
// `watch(user, { immediate: true })` below can complete the flow before mount
// and it needs the target and the flow marker already in hand.
const targetRedirect = ref<string | null>(safeRedirectPath(readParam('redirect')))
const isTaggedOAuth = readParam('flow') === 'oauth'
// Positive evidence that something was actually verified. Without any of these
// the visitor merely navigated to the callback route.
const hasVerificationParam = !!(readParam('code') || readParam('token_hash') || readParam('type'))

let redirected = false

function proceedToHome() {
  if (timer) clearInterval(timer)
  router.push(targetRedirect.value || '/')
}

/**
 * How the *current* session authenticated, from the JWT's `amr` claim.
 *
 * Deliberately not `app_metadata.provider`: that is the account's ORIGINAL
 * provider and never changes, so an account created with a password and later
 * linked to Google reports `email` on every Google login for the rest of time.
 * `amr` describes this sign-in. It comes in an object and a string form.
 */
function signedInWithOAuth(): boolean {
  // Read from `useSupabaseUser()` specifically: @nuxtjs/supabase populates it
  // from `getClaims()`, so it is the JWT payload. The `User` object the client
  // hands back from a code exchange has no `amr` at all — it is a session fact,
  // not a user one.
  const amr = (user.value as { amr?: AmrEntry[] } | null)?.amr
  if (!Array.isArray(amr)) return false
  return amr.some(entry => (typeof entry === 'string' ? entry : entry?.method) === 'oauth')
}

/**
 * Whether this callback is a real email confirmation — the only thing that earns
 * the "Email Confirmed!" screen.
 *
 * Everything else goes straight through to the app: a social sign-in (which the
 * visitor just performed deliberately and needs no interstitial for), and a stray
 * navigation to /confirm, where announcing a confirmation would simply be untrue.
 */
function isEmailConfirmation(): boolean {
  if (isTaggedOAuth) return false
  if (!hasVerificationParam) return false
  return !signedInWithOAuth()
}

/**
 * Single completion path for every way a session can arrive here.
 *
 * Only a genuine email confirmation stops on the success screen. A social login
 * goes straight through — someone who just clicked "Sign in with Google" gets
 * told nothing by an "Email Confirmed!" screen they never asked for — and
 * `replace` keeps the spent callback route out of their history.
 */
async function succeed() {
  if (status.value === 'success' || redirected) return

  if (!isEmailConfirmation()) {
    redirected = true
    // The immediate watcher can fire during setup; wait for the mount so the
    // navigation isn't issued from a component that doesn't exist yet.
    await nextTick()
    const target = targetRedirect.value || '/'
    // Strip the spent callback params BEFORE navigating, not after. Until this
    // navigation commits the browser URL still reads `/confirm?code=...`, and
    // `auth-redirect.global` inspects it — leaving them on is what used to
    // bounce this very redirect back here and hang the page on the spinner.
    cleanUrl()
    router.replace(target)
    armRedirectWatchdog(target)
    return
  }

  status.value = 'success'
  await initLanguage()
  startCountdown()
}

/**
 * Last resort for a router redirect that never lands.
 *
 * `redirected` latches, so a swallowed navigation would otherwise leave a
 * signed-in visitor on the loading spinner with nothing left to retry. A full
 * page load to an already-cleaned URL cannot be intercepted by a route guard,
 * and the established session means it won't come back here.
 */
function armRedirectWatchdog(target: string) {
  if (typeof window === 'undefined') return
  if (watchdog) clearTimeout(watchdog)
  watchdog = setTimeout(() => {
    if (window.location.pathname === '/confirm') window.location.replace(target)
  }, WATCHDOG_MS)
}

/** Never downgrade a flow that already completed. */
function fail() {
  if (status.value === 'loading' && !redirected) status.value = 'error'
}

/**
 * Fall back to whatever session the Supabase client has settled on by now.
 * Returns false when there still isn't one.
 */
async function succeedIfSessionExists(): Promise<boolean> {
  const { data } = await supabase.auth.getSession()
  const sessionUser = data?.session?.user ?? user.value
  if (!sessionUser) return false
  await succeed()
  return true
}

/**
 * Runs one of the Supabase verification calls and resolves the outcome.
 *
 * A failure here is not conclusive: `@nuxtjs/supabase` races us for the same
 * code and often wins, which surfaces as "invalid code" even though the session
 * is fine — hence the fallback, and the grace period for storage to sync.
 */
async function verify(
  run: () => Promise<{ data: { session: Session | null } | null, error: { message: string } | null }>,
  label: string,
  graceMs: number
) {
  try {
    const { data, error } = await run()
    if (!error && data?.session) {
      await succeed()
      return
    }
    if (error) console.warn(`[confirm.vue] ${label}:`, error.message)
  } catch (e) {
    console.warn(`[confirm.vue] ${label} caught:`, e)
  }

  if (await succeedIfSessionExists()) return
  if (!graceMs) {
    fail()
    return
  }
  setTimeout(async () => {
    if (!await succeedIfSessionExists()) fail()
  }, graceMs)
}

function cleanUrl() {
  if (typeof window !== 'undefined' && (window.location.search || window.location.hash)) {
    window.history.replaceState(window.history.state, '', window.location.pathname)
  }
}

let authSubscription: { unsubscribe: () => void } | null = null

onMounted(async () => {
  const err = readParam('error')
  const errCode = readParam('error_code')
  const errDesc = readParam('error_description')

  if (err || errCode) {
    console.error('[confirm.vue] Auth provider error:', { err, errCode, errDesc })
    status.value = 'error'
    errorMessage.value = getLocalizedError(errCode, errDesc) || errDesc || null
    cleanUrl()
    return
  }

  // Subscribe first, in case @nuxtjs/supabase exchanges the code in the background
  const { data: authListener } = supabase.auth.onAuthStateChange((_event, session) => {
    if (session?.user) succeed()
  })
  authSubscription = authListener.subscription

  const code = readParam('code')
  const tokenHash = readParam('token_hash')
  const type = (readParam('type') || 'email') as EmailOtpType

  if (code) {
    await verify(() => supabase.auth.exchangeCodeForSession(code), 'exchangeCodeForSession', 800)
  } else if (tokenHash) {
    await verify(() => supabase.auth.verifyOtp({ token_hash: tokenHash, type }), 'verifyOtp', 0)
  } else if (!await succeedIfSessionExists()) {
    setTimeout(async () => {
      if (!await succeedIfSessionExists()) fail()
    }, 1500)
  }

  cleanUrl()
})

function startCountdown() {
  if (timer) return
  timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      proceedToHome()
    }
  }, 1000)
}

watch(user, (newUser) => {
  if (newUser && !errorMessage.value) succeed()
}, { immediate: true })

watch(status, (newStatus) => {
  if (newStatus === 'success') {
    startCountdown()
  }
}, { immediate: true })

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (watchdog) clearTimeout(watchdog)
  if (authSubscription) authSubscription.unsubscribe()
})
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] p-4 text-center">
    <!-- Loading State -->
    <div
      v-if="status === 'loading'"
      class="flex flex-col items-center gap-4"
    >
      <UProgress
        indeterminate
        class="w-64"
      />
      <p class="text-sm text-muted">
        {{ $t('auth.confirmingDesc') }}
      </p>
    </div>

    <!-- Success State: Email Confirmed Screen -->
    <div
      v-else-if="status === 'success'"
      class="max-w-md w-full"
    >
      <UEmpty
        icon="i-lucide-badge-check"
        :title="$t('auth.emailConfirmedTitle')"
        :description="$t('auth.emailConfirmedDesc')"
        variant="naked"
        class="py-8"
      >
        <template #leading>
          <UIcon
            name="i-lucide-badge-check"
            class="size-16 text-success mb-2"
          />
        </template>
        <template #actions>
          <div class="flex flex-col items-center gap-3 w-full">
            <UButton
              :label="$t('auth.continueToStore')"
              color="primary"
              size="lg"
              class="w-full justify-center"
              @click="proceedToHome"
            />
            <p class="text-xs text-muted">
              {{ $t('auth.redirectingCountdown', { seconds: countdown }) }}
            </p>
          </div>
        </template>
      </UEmpty>
    </div>

    <!-- Error State -->
    <div
      v-else
      class="max-w-md w-full"
    >
      <UEmpty
        icon="i-lucide-alert-circle"
        :title="$t('auth.confirmFailedTitle')"
        :description="errorMessage || $t('auth.confirmFailedDesc')"
        variant="naked"
        class="py-8"
        :actions="[{
          label: $t('auth.backToLogin'),
          to: loginRedirect(targetRedirect),
          color: 'neutral',
          size: 'lg'
        }]"
      >
        <template #leading>
          <UIcon
            name="i-lucide-alert-circle"
            class="size-16 text-error mb-2"
          />
        </template>
      </UEmpty>
    </div>
  </div>
</template>

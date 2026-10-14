import { computed, onBeforeUnmount, ref } from 'vue'

/**
 * State for a page that renders the Turnstile widget (sign-in, register,
 * forgot password, console sign-in).
 *
 * `isPending` is what keeps the submit button disabled until the challenge is
 * solved. Pressing a live button only to be told "complete the security check"
 * reads as a broken form — and the guard in each `onSubmit` stays as the
 * backstop, not the interface.
 *
 * A siteverify token is single-use and expires after five minutes, so the token
 * has to go away whenever it stops being good:
 *  - `spend()` after every submit, whatever the outcome. It also resets the
 *    widget so a fresh challenge starts now — without the reset the widget only
 *    re-solves on its own 250 s timer, and the button would stay disabled.
 *  - the widget's `expired-callback`, until it refreshes itself.
 *  - leaving the page. The token lives in a module-level ref, so without this a
 *    token solved on /login would unlock /register's button before /register's
 *    own widget had run.
 */
export function useTurnstileWidget(action: string) {
  const { token, isEnabled, clearToken } = useTurnstileToken()
  const widget = ref<{ reset: () => void } | null>(null)

  const isPending = computed(() => isEnabled.value && !token.value)

  const options = {
    action,
    'expired-callback': clearToken
  }

  function spend() {
    clearToken()
    widget.value?.reset()
  }

  onBeforeUnmount(clearToken)

  return { token, isEnabled, isPending, widget, options, spend }
}

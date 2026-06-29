/**
 * Global middleware that catches `?payment=success` or `?payment=cancelled`
 * query params on ANY page and redirects to the proper checkout result page.
 *
 * This is needed because Stripe PaymentLinks may redirect to arbitrary URLs
 * (e.g. the homepage) with query params, and those pages don't handle payment
 * confirmation logic.
 */
export default defineNuxtRouteMiddleware((to) => {
  const payment = to.query.payment as string | undefined

  if (!payment) return

  // Already on checkout pages — let them handle it
  if (to.path.startsWith('/checkout/')) return

  if (payment === 'success') {
    return navigateTo({
      path: '/checkout/success',
      query: {
        item_id: to.query.item_id,
        session_id: to.query.session_id
      }
    })
  }

  if (payment === 'cancelled') {
    return navigateTo('/checkout/cancel')
  }
})

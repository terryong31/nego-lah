---
id: SPEC-082
title: Item Store Identity Scoping
status: complete
priority: high
created: 2026-09-15
tags: [frontend, security, pricing, auth]
assigned: agent
---

# Context & Objectives

`useItemStore` (SPEC-041) is a `useState`-backed, per-tab cache of item rows. Its contents
are **user-scoped**: `GET /items/:id` attaches `discounted_price` resolved from the *calling
buyer's* negotiated price (`payment.pricing.active_negotiated_price`), and the chat SSE
`data-discount` frame patches that same entry via `applyDiscount`.

Nothing empties the cache when the signed-in user changes. `supabase.auth.signOut()` is
called in `AppHeader.vue`, `profile.vue`, `chat.vue` and `useApi.ts`, and none of them touch
the store. So in one tab: buyer A negotiates an item down to RM2,449 → signs out → buyer B
signs in and opens the same item → `fetchIfMissing` sees a warm entry, returns without
calling the API, and B is shown A's negotiated price and discount badge. Only a hard reload
(which drops JS memory) corrects it.

That is one buyer's negotiation outcome disclosed to another, and a price the backend would
never have quoted B.

**Objective:** scope the cache to the identity that populated it, and drop it the moment that
identity changes.

# Acceptance Criteria

- [x] **Owner tracking:** the store records the user id its entries belong to.
- [x] **Clear on change:** setting a different owner empties the cache, so the next
      `fetchIfMissing` is a real request under the new buyer's JWT.
- [x] **Sign-out clears:** owner `null` is a change like any other — signing out empties it.
- [x] **No spurious clears:** re-asserting the same owner (token refresh, repeated
      `INITIAL_SESSION`, tab focus) is a no-op and does not drop a live negotiated price.
- [x] **Wired to auth:** a client plugin watches `useSupabaseUser()` — the ref
      `@nuxtjs/supabase`'s own `onAuthStateChange` subscription already writes every
      transition into — rather than opening a second listener of its own.
- [x] **No boot race:** the watcher's `immediate` run primes the owner before any page
      fetches, so the first identity signal cannot wipe a cache a page just populated.
      (`@nuxtjs/supabase`'s own plugin is `enforce: 'pre'` and awaits `getSession()` +
      `getClaims()`, so the signed-in user is already known.)

# Technical Design & Contracts

```ts
// app/stores/item.ts
const _owner = useState<string | null>('item-store-owner', () => null)

function setOwner(userId: string | null): void {
  if (_owner.value === userId) return
  _owner.value = userId
  _items.value = new Map()
}

// app/plugins/item-store-identity.client.ts
// The ref holds JWT claims: the id is `sub`, `id` is the spelling the rest of
// the app reads off it.
const user = useSupabaseUser()
watch(
  () => user.value?.sub ?? user.value?.id ?? null,
  userId => store.setOwner(userId ?? null),
  { immediate: true }
)
```

# TDD Scenarios

- [x] **S1:** entry cached under owner A is gone after `setOwner('B')`, and `fetchIfMissing`
      then issues a fresh API call.
- [x] **S2:** `setOwner(null)` (sign-out) empties the cache.
- [x] **S3:** `setOwner` with the current owner does not clear a negotiated price applied by
      `applyDiscount`.
- [x] **S4:** the plugin primes the owner from the restored identity and leaves a
      just-fetched entry intact when the same user is re-asserted; a different user, and a
      sign-out, each clear the store.

# Implementation Files

- `frontend/app/stores/item.ts` — `setOwner`
- `frontend/app/plugins/item-store-identity.client.ts`
- `frontend/tests/stores/item.test.ts`
- `frontend/tests/plugins/itemStoreIdentity.test.ts`

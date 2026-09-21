---
id: SPEC-099
title: The Walkthrough Video Starts Loading Before You Need It
status: complete
priority: medium
created: 2026-09-20
tags: [frontend, performance, media, ux]
assigned: agent
---

# Context & Objectives
The homepage walkthrough (`HomeAgentPipeline`) stalls for several seconds before the first frame
appears. The cause is not streaming — `media.negolah.my` returns `accept-ranges: bytes`, answers
range requests with `206`, and the shipped MP4 is FastStart (`moov` ahead of `mdat`). The cause is
that the fetch is started at the exact moment the video is needed:

* every `<video>` is `preload="none"`, and
* its `<source>` is not attached until the step is *active*, which happens when the section's
  observer fires at `rootMargin: '200px'`.

200px of scroll is a few hundred milliseconds. `play()` is called on a video that has just been
handed its URL, so the visitor watches DNS, TLS, the request and the first decode happen.

SPEC-045 made this lazy on purpose — the old build fetched a 12.9 MB file on every homepage visit
and burned the Supabase egress quota. That constraint is kept: nothing is fetched unless the
visitor is approaching the section. The change is *how early* "approaching" starts.

# Acceptance Criteria
- [x] A step's video begins downloading roughly **one viewport before** the section is reached,
      not 200px before.
- [x] Warming is still viewport-gated: a visitor who never scrolls near `#how-it-works` fetches
      **no** video bytes. The SPEC-045 egress guarantee is unchanged.
- [x] A warmed `<video>` uses `preload="auto"`; an unwarmed one stays `preload="none"` and has
      **no** `<source>` child.
- [x] The **next** step is warmed once the visitor is *in* the section — approaching warms one clip,
      arriving warms the next, so merely scrolling past does not cost two downloads.
- [x] At most `current + 1` steps are ever warmed at once — never all three up front.
- [x] Playback timing is untouched: the existing `armed` observer still decides when to *play*.
      Warming only decides when to *fetch*.
- [x] A step already warmed is never un-warmed by scrolling away.

# Technical Design & Contracts
Two observers with different jobs, because they answer different questions:

| observer | `rootMargin` | sets | means |
|---|---|---|---|
| warm (new) | `100% 0px` | `warm` | "start fetching" — one viewport of runway |
| armed (existing) | `200px` | `armed` | "start playing" — unchanged |

`warm: Set<string>` replaces `reached` as what gates the `<source>`. It is populated by the warm
observer (step 0) and by the active-step watcher (`active` and `active + 1`), and never shrinks.

`preload` binds to `warm.has(id) ? 'auto' : 'none'`. `auto` matters: with a `<source>` attached but
`preload="none"`, a browser is entitled to fetch nothing until `play()`, which is the stall again
with extra steps.

Fallback is unchanged — no `IntersectionObserver` means warm everything immediately, same as the
existing `armed = true`.

# Test-Driven Development (TDD) Scenarios
- [x] A visitor who has not approached the section has **zero** `<source>` elements.
- [x] Once the section is approached, step 0 has a `<source>` and `preload="auto"`.
- [x] Step 1 is warmed alongside step 0 (lookahead), step 2 is not.
- [x] Selecting step 1 warms step 2; all three then have sources.
- [x] An unwarmed `<video>` carries `preload="none"` and no `<source>`.
- [x] Scrolling back to an earlier step keeps its `<source>` attached.
- [x] Warm and armed stay independent: warming alone must not call `play()`.

# Implementation Files
- `frontend/app/components/home/AgentPipeline.vue`
- `frontend/nuxt.config.ts` — `preconnect` / `dns-prefetch` to the media origin
- `frontend/tests/components/home/AgentPipeline.test.ts`

# Outcome
1,012 frontend tests pass (76 files); `eslint` and `nuxt typecheck` clean.

**Caveat worth recording.** This fix is correct but is *not* what a visitor sees on production
today. `negolah.my` serves release `e4738ff91fe5c4da…`, which is this component, and all six of its
CDN assets 404:

```
media.negolah.my/videos/how-it-works/{listing,haggle,delivery}.mp4  -> 404
media.negolah.my/videos/how-it-works/{listing,haggle,delivery}.jpg  -> 404
```

The recordings have never been produced — `~/Desktop/nego-lah-media/dist/` holds only the
pre-SPEC-069 `negotiation-demo.mp4`. So the section currently renders its placeholder and no video
plays at all. This spec removes the stall that will otherwise appear the moment those files land.

Two things found alongside, deliberately left alone (out of scope, no owner's decision taken):

* A missing recording makes each `<video>` download a **28 KB HTML page** served as
  `content-type: text/html` — the R2 custom domain falls through to the SPA shell on a miss.
  Nothing surfaces this; `ready` simply never fills.
* `masters/upload.mp4` and `frontend/videos/test.mp4` are **not FastStart** (`moov` after `mdat`).
  Neither ships today, but either would reproduce "must fully download before playing" exactly if
  uploaded. The shipped `negotiation-demo.mp4` is correctly FastStart.

# Outcome
Measured in real Chrome (playwright) against the app serving ffmpeg-generated FastStart clips,
with 400 ms of artificial latency applied to media requests only — throttling the whole dev bundle
measures Vite, not this.

**At rest, having only approached the section:**

| stage | before | after |
|---|---|---|
| 1 `listing` | source, `preload=none`, `readyState=4`, buffered 6 s | source, `preload=auto`, `readyState=4`, buffered 6 s |
| 2 `haggle` | **no source, `readyState=0`, buffered 0 s** | source, `preload=auto`, **`readyState=4`, buffered 6 s** |
| 3 `delivery` | no source | no source *(correctly deferred)* |

**Honest reading of the numbers.** Time-to-first-frame for step 1 did *not* improve (119 ms before,
129 ms after) and was never going to on this layout: `#how-it-works` sits ~80 px below the fold, so
the old `rootMargin: '200px'` observer already fired at page load and `play()` forced the fetch
regardless of `preload="none"`. The measurable defect was **steps 2 and 3** — no `<source>`, nothing
buffered, so every step change paid the full fetch. That is now pre-buffered.

What the change buys where it could not be measured locally: `preload="auto"` means the browser
buffers instead of waiting for `play()`, `preconnect` takes DNS and the TLS handshake off the first
media request (the local test served same-origin, because CSP is `media-src 'self' https:`), and
the one-viewport warm margin matters on any layout where the section is further down than this one.

1,012 frontend tests pass, `eslint` and `nuxt typecheck` clean. Test rig removed;
`frontend/public/videos/` was gitignored throughout, so nothing leaked.

---
id: SPEC-100
title: One Motion-Graphics Intro Video Replaces the Three-Step Walkthrough
status: complete
priority: medium
created: 2026-10-07
tags: [frontend, media, motion, home]
assigned: agent
---

# Context & Objectives
"How it works" (`HomeAgentPipeline`, SPEC-069/075) was a scroll-pinned `UStepper` driving three
screen recordings. None were ever recorded, so every visitor saw "Recording coming soon" three
times. It is replaced by **one** ~27 s motion-graphics intro, written as code in a Remotion
project (`video/`, ADR-0031) and served from R2 like every other video.

The look is the site's own Corporate Memphis vocabulary pushed further — not the generic
AI-generated look (purple gradients, Inter, glow blobs, card grids) and not a warm-beige editorial
look. The product's own screens (listing card, chat, price tag, tracker) are rebuilt as vector
components, so the video stays sharp and never shows stale UI.

# Acceptance Criteria
- [x] The home page has exactly one `<video>`; no stepper, no scroll pin, no "coming soon" state.
- [x] SPEC-045/099 hold: nothing is fetched until the section is about one viewport away; then the
      source is attached with `preload="auto"`. It plays on screen and pauses off it.
- [x] Autoplays **muted** and inline (browser policy); a Nuxt UI button toggles sound.
- [x] Under `prefers-reduced-motion` it does not autoplay; the poster shows with a play button.
- [x] The video never shows or implies a floor price; prices fall in whole-number, small steps.
- [x] Rendered MP4 is H.264 + AAC, FastStart, ≤ 4 MB, with a poster frame; neither is in git.
- [x] Music and SFX are free for commercial use; raw audio is not committed (public repo) and
      `video/audio/CREDITS.md` records the source and licence of each file.

# Technical Design & Contracts
- **Media URLs:** `${mediaCdnUrl}/videos/intro.mp4`, poster `${mediaCdnUrl}/videos/intro.jpg`.
  `scripts/sync-media-r2.mjs` uploads posters (`.jpg`/`.webp`) alongside videos.
- **Component:** `HomeIntroVideo` (`components/home/IntroVideo.vue`) keeps `id="how-it-works"`.
  Two observers as in SPEC-099: warm at `rootMargin: '100% 0px'` (one-shot), play/pause at
  `200px`. A click on the play/sound control is trusted as proof of visibility.
- **Remotion:** composition `NegoLahIntro`, 1920×1080 @ 30 fps. Six scenes cut on a 120 BPM
  grid (`BEAT = 15` frames). Scene changes are shape wipes. Audio cues are declared in one list;
  a cue whose file is absent is skipped, so the video renders silent before audio is chosen.
- **Banned in the video:** crossfades, blur-ins, 3D flips, gradients and glows, glassmorphism,
  beige/terracotta palettes, Inter.

# Test-Driven Development (TDD) Scenarios
- [x] **One video:** exactly one `<video>`, no `UStepper`.
- [x] **Inert until approached:** no `<source>`, `preload="none"` before the warm observer fires.
- [x] **Warm:** after it fires, a `<source>` for `intro.mp4` and `preload="auto"`.
- [x] **Never blank:** `poster` points at `intro.jpg`; `muted` and `playsinline` are set.
- [x] **Plays on screen, pauses off it** via the 200px observer.
- [x] **Sound toggle** flips `muted` and the button's label.
- [x] **Reduced motion:** `play()` is not called by the observer; the play button starts it.

# Implementation Files
- `frontend/app/components/home/IntroVideo.vue` — replaces `AgentPipeline.vue`
- `frontend/tests/components/home/IntroVideo.test.ts` — replaces `AgentPipeline.test.ts`
- `frontend/app/pages/index.vue`, `frontend/app/locales/{en,ms,zh}.json`
- `frontend/scripts/sync-media-r2.mjs` — poster upload
- `video/**` — Remotion project; `mise.toml` — `video:*` tasks; `.gitignore`

# ADR-0031: Videos Are Code

**Status:** Accepted · **Date:** 2026-10-07 · **Supersedes the media plan of:** SPEC-069/075 · **Relates to:** [SPEC-100](../specs/SPEC-100-one-intro-video.md), SPEC-045

## Context

The home page waited on three screen recordings that never got made. A recording is expensive to
produce, goes stale the moment the UI changes, and cannot be edited — a new price or a renamed
button means recording it again.

## Decision

The intro video is a **Remotion** project in `video/`: React components rendered frame by frame to
MP4. The product's screens appear as vector rebuilds, not captures.

- `video/` is its own package with its own lockfile. It is not part of the Nuxt build, the
  Cloudflare deploy, or CI's test matrix — it is an authoring tool, run by hand.
- The **output** never enters git. `mise run video:render` writes to the media folder outside the
  repo and `mise run media:sync` publishes it to R2, as SPEC-045 does for every video.
- **Raw audio never enters git either.** The repo is public and stock-audio licences permit use in
  a video, not redistribution of the files. `video/public/audio/` is ignored; `CREDITS.md` records
  each file's source and licence so the render is reproducible.

## Consequences

- A copy or price change is a code change and a re-render, reviewable as a diff.
- Remotion is free for individuals and companies of up to three people; past that it needs a
  company licence.
- The render needs Chromium and ffmpeg locally (Remotion downloads its own headless shell).

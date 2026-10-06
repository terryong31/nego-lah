# Audio credits

The files themselves live in `video/public/audio/` and are **not committed** (ADR-0031): the repo
is public, and a stock licence covers use in the video, not redistribution. This file is what
makes the render reproducible: download each one and save it under the slot name.

Any of `.mp3` / `.wav` / `.ogg` / `.m4a` works. A missing slot is skipped, so the video still
renders without it. Cue times come from `src/timeline.ts`, wired in `src/Soundtrack.tsx`.

| Slot | Used for | Source file | Pack | Licence |
|------|----------|-------------|------|---------|
| `pop` | hook bubbles, "Listed", URL pill | `pluck_001.ogg` | [Kenney — Interface Sounds](https://kenney.nl/assets/interface-sounds) | CC0 |
| `message` | each chat message | `drop_001.ogg` | Kenney — Interface Sounds | CC0 |
| `tick` | "seen", price steps, tracker stops | `tick_002.ogg` | Kenney — Interface Sounds | CC0 |
| `whoosh` | every shape wipe | `maximize_006.ogg` | Kenney — Interface Sounds | CC0 |
| `stamp` | price tag, DEAL stamp | `impactPunch_heavy_000.ogg` | [Kenney — Impact Sounds](https://kenney.nl/assets/impact-sounds) | CC0 |
| `cash` | "Paid" | `confirmation_002.ogg` | Kenney — Interface Sounds | CC0 |
| `chime` | logo lands | `confirmation_004.ogg` | Kenney — Interface Sounds | CC0 |
| `music` | the bed, full length (first 0.9 s trimmed) | "Background Music" by Sub_Clair — save as `music.mp3` | [Pixabay](https://pixabay.com/music/funk-background-music-591220/) (funk, ~118 BPM) | Pixabay Content Licence (commercial use, no credit required) |

Kenney credit is not required by CC0 but is given here anyway.

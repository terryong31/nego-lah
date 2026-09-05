---
id: SPEC-027
title: Authorship-Aware Chat Bubble Segmentation
status: complete
priority: medium
created: 2026-09-06
tags: [frontend, chat, ux]
assigned: agent
---

# Context & Objectives

`\n` is overloaded in the chat thread. The seller persona is prompted to "text like a
friend — one thought each" (`backend/agent/config.py`), so an AI newline can mean a
**message boundary**. But `UChatPrompt` has `submitOnEnter: true`: a human presses Enter
to send and Shift+Enter to add a line, so a human newline is a **line inside one
message**. Splitting on the character alone shreds a buyer's deliberate multi-line
message; not splitting at all collapses the AI's texting cadence into one wall of text
(the current behaviour).

Within an AI turn the boundary is a **blank** line, not any newline. Splitting on
every newline shreds structured content the agent legitimately writes on consecutive
lines — a shipping address, a `list_all_items` result, a spec sheet — into one bubble per
line. Blank-line splitting also fails safe: if the model forgets the blank line the turn
renders as one bubble with line breaks, which reads fine, where the inverse mistake looks
broken.

The character is ambiguous, but the authorship is not: every stored message already
carries `source` (`human` | `ai` | `admin` | `system`) beside `role`, persisted by
`ConversationMemory.add_message` and returned by `/chat/history`. A seller takeover is
stored as `role="ai", source="admin"` (`backend/routes/admin.py`), which is exactly the
signal needed to tell a human's newline from the AI's on the assistant side.

Segmentation is therefore keyed on **who authored the newline**, not on the newline.

A secondary objective: `messageBlocks`, the `Block` type and the `PAY_LINK` regex are
copy-pasted into both `chat.vue` and `AdminChats.vue` and have already drifted. They
move to one shared, unit-testable util.

---

# Acceptance Criteria

- [x] **Split rule**: a message is split into one bubble per **blank-line-separated
      block** iff `role === 'assistant' && source !== 'admin'`. All other messages render
      as a single bubble with newlines preserved (`whitespace-pre-wrap`).
- [x] **Single newlines are line breaks**: consecutive lines inside a block stay in one
      bubble, so an address or item list is never shredded. A run of several blank lines
      is one boundary.
- [x] **Role is the primary gate**: `get_history_page` defaults a missing `source` to
      `"ai"`, so pre-`source` rows must still be gated by `role` — a legacy buyer message
      is never split.
- [x] **Streaming default**: a live-streamed assistant turn carries no stored `source`
      and is always the AI, so an absent source splits.
- [x] **Buyer and seller see the same shape**: `AdminChats.vue` applies the identical
      rule via its existing `admin` flag, ending the divergence where the console renders
      AI replies as one blob.
- [x] **Payment links survive**: a markdown pay link is lifted out of its block and
      renders as `ChatPayCard`; a half-streamed link renders the `pending` placeholder.
- [x] **No empty bubbles**: blank lines — including those left behind by stripping
      `[[STATUS:…]]` markers — are dropped.
- [x] **Persona emits blank lines**: `SELLER_PERSONA` teaches blank line = new bubble,
      single line break = same bubble, with a worked address example.
- [x] **No backend API change**: `source` is already persisted, returned by
      `/chat/history` and carried on the realtime broadcast.

---

# Technical Design & Contracts

New util `frontend/app/utils/chatBlocks.ts`:

```ts
type Block =
  | { type: 'text', text: string }
  | { type: 'pay', label: string, url: string }
  | { type: 'pending' }

function shouldSplit(role?: string, source?: string): boolean
function messageBlocks(text: string, split: boolean): Block[]
```

`shouldSplit` is the single home of the rule. `messageBlocks` takes already-resolved
text (the caller decides whether that is the typewriter's partial reveal or the
finished message) so the util stays free of component state.

When `split` is true the text is cut on `/\n\s*\n/`; each block is then parsed by the
same `parseSegment` used for the unsplit path, so a pay link is lifted into its own card
on either path and a half-streamed link keeps the text that already arrived.

Consumers plumb `source` through:

- `chat.vue` — `mapMessages` and the realtime `onMessage` push both attach the stored
  `source` as a `data-source` part; streamed messages have none and default to splitting.
- `AdminChats.vue` — passes its existing `admin: isAdmin` flag straight through.

---

# Test-Driven Development (TDD) Scenarios

- [x] **AI message splits:** `shouldSplit('assistant', 'ai')` → true; three
      blank-line-separated blocks yield three bubbles.
- [x] **Address stays whole:** an AI block of consecutive lines is one bubble, not four.
- [x] **Fails safe:** an AI reply with no blank lines renders as one bubble.
- [x] **Repeated blank lines:** `'One\n\n\n\nTwo'` is two bubbles, not three.
- [x] **Buyer message does not split:** `shouldSplit('user', 'human')` → false; a
      Shift+Enter message stays one block with its `\n` intact.
- [x] **Seller takeover does not split:** `shouldSplit('assistant', 'admin')` → false.
- [x] **Legacy row gated by role:** `shouldSplit('user', 'ai')` → false (missing `source`
      defaulted to `"ai"` server-side).
- [x] **Streaming default:** `shouldSplit('assistant', undefined)` → true.
- [x] **Pay link per block:** a link in its own block becomes a `pay` block with its
      label and URL; surrounding blocks stay text blocks.
- [x] **Pay link unsplit:** in a non-split message the link is still lifted into a `pay`
      block, with the text before/after preserved around it.
- [x] **Half-streamed link:** text containing `](http` but no closing paren yields the
      already-readable text plus `pending`, with the partial `[label` markdown trimmed.
- [x] **Blank lines dropped:** `[[STATUS:…]]` residue and empty lines produce no bubbles.

---

# Implementation Files

- `frontend/app/utils/chatBlocks.ts` - Shared split rule + block parser (new)
- `frontend/tests/utils/chatBlocks.test.ts` - Unit tests for the above (new)
- `frontend/app/pages/chat.vue` - Carry `source`, delegate to the util
- `frontend/app/components/admin/AdminChats.vue` - Delegate to the util via `admin` flag
- `backend/agent/config.py` - Persona emits a blank line between messages

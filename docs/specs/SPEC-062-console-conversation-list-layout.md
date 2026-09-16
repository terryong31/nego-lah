---
id: SPEC-062
title: Console Conversation List Layout
status: complete
priority: medium
created: 2026-09-10
tags: [admin, frontend, nuxt-ui, ux]
assigned: agent
---

# Context & Objectives

The conversation list header carries two rows of controls for a pane that is
340px wide at its default size. The top row is a hand-rolled segmented control
(three `UButton`s in a `bg-elevated/50` box) filtering All / Unread / Read; the
second row is a search box and a sort select, both `size="xs"`, with the
refresh button stranded up in the first row.

The filter is redundant: "Unread first" is already a sort option, and unread
rows already carry a `UChip`. Removing it buys back a whole row of vertical
space in the pane that has the least of it, and lets the remaining controls
grow to a size that matches the rest of the console.

The pane itself is also too narrow to do its job — display names and message
previews truncate at the default 20%.

# Acceptance Criteria

- [x] The All / Unread / Read segmented control is gone, along with its
      `filter` state and the `admin.chatsSection.filterAll` /
      `admin.filterUnread` / `admin.filterRead` strings where they are no
      longer used.
- [x] The search input is `size="md"` on one row with the sort, archive and
      refresh controls, refresh last.
- [x] The sort is an `md` funnel-icon dropdown, not a 160px select: it spent
      most of a 377px pane spelling out a choice that is almost always the
      default. It tints when the operator has moved off "Recent activity", so a
      non-default order is never silent.
- [x] The list's control strip and the thread header are pinned to the same
      height — they sit either side of the splitter handle, where a few pixels
      apart reads as misalignment.
- [x] The conversation list pane cannot be dragged below 30% of the splitter,
      defaults to 32%, and still caps at 45%; the thread's minimum drops to 55%
      so the two constraints can coexist.
- [x] Mobile (<768px) keeps its single-pane behaviour and the same one-row
      control strip.
- [x] The empty state uses `UEmpty` with an icon and a title, not a bare
      description, and still distinguishes "no conversations yet" from
      "nothing matches this search".

# Technical Design & Contracts

`splitterItems` becomes:

    list   { minSize: 30, defaultSize: 32, maxSize: 45 }
    thread { minSize: 55, defaultSize: 68 }

Desktop and mobile carried a byte-identical copy of this list, so every change
here had to be made twice and the copies had already drifted. Both now render
one `AdminChatList.vue`; `AdminChats.vue` keeps the wrapper that actually
differs (splitter pane vs. master-detail) and owns the data. `ChatSummary` moves
to `app/utils/adminChat.ts` — a `.ts` file under `app/components/` gets
registered as a bogus auto-imported component.

One control row replaces two, pinned to `h-14` to match the thread header:

    <UInput size="md" class="flex-1 min-w-0" icon="i-lucide-search" … />
    <UDropdownMenu :items="sortMenu">        <!-- i-lucide-funnel, md, ghost -->
    <UButton size="md" variant="ghost" icon="i-lucide-archive" />
    <UButton size="md" variant="ghost" icon="i-lucide-refresh-cw" :loading="pending" />

`sortMenu` maps `sortItems` to `type: 'checkbox'` entries. `onSelect` is
prevented so the menu behaves as a picker, and re-picking the active sort is a
no-op rather than a clear — there is no "unsorted".

`filteredChats` collapses into `visibleChats`; the search + sort behaviour is
unchanged. No API changes.

`UEmpty` gains `icon="i-lucide-messages-square"` plus a title
(`admin.chatsSection.emptyListTitle` / `noMatchTitle`), keeping the existing
descriptions as the second line.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** The rendered list header contains no All/Unread/Read
      buttons.
- [x] **Scenario 2:** Search still filters on display name and last message;
      sort options still reorder.
- [x] **Scenario 3:** The refresh button sits in the same row as the search and
      sort controls, in that order, and still triggers `refresh()`.
- [x] **Scenario 3b:** The strip and the thread header carry the same pinned
      height class.
- [x] **Scenario 4:** With no conversations, `UEmpty` renders with an icon and
      the "no conversations yet" title; with a non-matching query it renders
      the "no matches" title instead.
- [x] **Scenario 5:** `splitterItems` exposes the new min/default/max sizes,
      and the two minimums still fit inside 100%.

# Implementation Files

- `frontend/app/components/admin/AdminChatList.vue` - extracted list, one copy
- `frontend/app/components/admin/AdminChats.vue` - wrapper, data, actions
- `frontend/app/utils/adminChat.ts` - the shared `ChatSummary` row type
- `frontend/app/locales/{en,ms,zh}.json`
- `frontend/tests/components/admin/AdminChats.test.ts`

---
id: SPEC-065
title: Global Filter on the Console Tables
status: complete
priority: medium
created: 2026-09-10
tags: [admin, frontend, nuxt-ui, ux]
assigned: agent
---

# Context & Objectives

The console's three tables — items, orders, users — have no way to find a row.
Every one of them is an unbounded list that only grows: every listing ever
created, every order ever paid, every account ever registered. Finding one means
scrolling, and the answer to "did that order ship?" is somewhere in a page the
seller has to read by eye.

The conversation list already got search (SPEC-062). These three are the same
problem with more rows.

# Acceptance Criteria

- [x] Items, orders and users each carry a search input above the table.
- [x] Typing filters the rows across every visible column, case-insensitively.
- [x] The count line reflects what is on screen — a filtered table saying
      "42 items" while showing three is a lie.
- [x] Clearing the input restores the full list.
- [x] A filter that matches nothing shows the table's `#empty` state saying so,
      distinct from the table being genuinely empty. On items, the "create your
      first listing" action is withheld under a failed search — it answers a
      different question.
- [x] The input is `md`, on the same row as the refresh control, matching the
      conversation list's strip.

# Technical Design & Contracts

`UTable` already wires TanStack's `getFilteredRowModel`, so this is
`v-model:global-filter` bound to a `UInput` — no client-side filtering of the
data array, and sorting/expansion keep working because the table still owns its
row model.

    <UInput v-model="globalFilter" size="md" icon="i-lucide-search" />
    <UTable v-model:global-filter="globalFilter" … />

The visible count comes from the table instance rather than the source array:
a `tableRef` and `tableRef.tableApi?.getFilteredRowModel().rows.length`, falling
back to the array length before the table has mounted.

Nested display fields (buyer email under buyer name, say) are matched by
TanStack against the row's accessor values, so columns rendered purely through a
cell template still filter on their `accessorKey`.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** Each table renders a search input bound to the table's
      `globalFilter`.
- [x] **Scenario 2:** Typing narrows the rendered rows; clearing restores them.
- [x] **Scenario 3:** The count line follows the filtered rows, not the source.
- [x] **Scenario 4:** A non-matching query renders the "no matches" empty state,
      not the "nothing here yet" one.

# Implementation Files

- `frontend/app/components/admin/{AdminItems,AdminOrders,AdminUsers}.vue`
- `frontend/app/locales/{en,ms,zh}.json`
- `frontend/tests/components/admin/AdminTableFiltering.test.ts`

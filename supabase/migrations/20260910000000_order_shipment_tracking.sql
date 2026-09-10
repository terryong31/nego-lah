-- SPEC-057 — the order lifecycle gets an end.
--
-- `orders.status` could already be flipped to 'shipped', but there was nowhere
-- to record what it shipped WITH. A buyer told "shipped" and nothing else has
-- learned nothing they can act on, so the seller was pasting tracking numbers
-- into the chat by hand and the agent, asked "where's my stuff?", could only
-- repeat the word.
--
-- Five nullable columns. Nothing backfills and nothing is required: every row
-- that exists today stays exactly as it is, and every read path treats NULL as
-- "not shipped yet", which is what it was already doing implicitly.
--
-- No courier API integration, deliberately. For a single seller posting a few
-- parcels a week, the seller IS the source of truth; polling a carrier would be
-- more moving parts than the problem has.

alter table public.orders
    add column if not exists courier         text,
    add column if not exists tracking_number text,
    add column if not exists tracking_url    text,
    add column if not exists shipped_at      timestamptz,
    add column if not exists delivered_at    timestamptz;

comment on column public.orders.courier is
    'Carrier name as recorded by the seller, e.g. "J&T Express". Free text: the '
    'registry in domains/catalog/shipping.py knows the common ones well enough '
    'to build a tracking URL, and an unknown carrier is still worth storing.';

comment on column public.orders.tracking_url is
    'Derived from courier + tracking_number where the carrier is known, or set '
    'explicitly by the seller. NULL simply means "no link to offer".';

comment on column public.orders.shipped_at is
    'Stamped when postage is first recorded. Distinct from status: an order can '
    'be moved back out of "shipped" by a correction without losing when it went.';

-- Orders are read by buyer and by status; a partial index keeps the "what is
-- currently in transit" console view cheap without paying for the NULLs.
create index if not exists orders_shipped_at_idx
    on public.orders (shipped_at desc)
    where shipped_at is not null;

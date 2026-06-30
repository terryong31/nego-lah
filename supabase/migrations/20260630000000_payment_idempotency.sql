-- ============================================================
-- Payment idempotency + race-safety constraints
-- ============================================================
-- Required by backend/payment/fulfillment.py. The UNIQUE constraint on
-- orders.stripe_payment_id is the idempotency key that guarantees exactly one
-- order per Stripe PaymentIntent, even when:
--   * Stripe re-delivers the webhook (at-least-once delivery), or
--   * the frontend confirm-payment fallback fires for the same payment.
-- The first writer wins the insert; every retry hits the unique violation and
-- the fulfiller treats it as an idempotent no-op.
--
-- NULLs are still allowed (Postgres permits multiple NULLs under UNIQUE), so
-- legacy/unpaid rows are unaffected.
--
-- If any existing rows already share a stripe_payment_id (from the previous
-- duplicate-creating code), de-duplicate them first or these statements will
-- fail. Example:
--   delete from public.orders a using public.orders b
--   where a.ctid < b.ctid and a.stripe_payment_id = b.stripe_payment_id
--     and a.stripe_payment_id is not null;

alter table public.orders
    add constraint orders_stripe_payment_id_key unique (stripe_payment_id);

alter table public.transactions
    add constraint transactions_stripe_payment_id_key unique (stripe_payment_id);

-- Speeds up the atomic item claim ( ... where id = ? and status = 'available' ).
create index if not exists items_status_idx on public.items (status);

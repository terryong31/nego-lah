-- Add translations JSONB column to items table for trilingual localization (en, ms, zh)
alter table if exists public.items
add column if not exists translations jsonb default '{}'::jsonb;

notify pgrst, 'reload schema';

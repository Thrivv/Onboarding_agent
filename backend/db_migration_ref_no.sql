-- =====================================================
-- SUPERSEDED — kept only for history.
--
-- This file's content now lives at
-- supabase/migrations/20250601000000_add_ref_no_to_users.sql, as the first
-- entry in a tracked migration history (see supabase/README.md). Apply
-- schema changes from there going forward, via `supabase db push`, rather
-- than running loose .sql files by hand.
-- =====================================================

-- =====================================================
-- MIGRATION: Add ref_no (Reference Number) to users
-- Run once against your Supabase / Postgres database.
-- =====================================================

-- Add ref_no column — unique alphanumeric reference number
-- generated at registration time, shared across all documents
-- belonging to the same onboarding request.
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS ref_no TEXT UNIQUE;

-- Index for fast lookup by ref_no (used by document path resolution)
CREATE INDEX IF NOT EXISTS idx_users_ref_no
    ON public.users (ref_no);

-- Back-fill existing users with a generated ref_no so existing
-- accounts are not left with NULL (NULL would break path resolution).
UPDATE public.users
SET ref_no = replace(gen_random_uuid()::text, '-', '')
WHERE ref_no IS NULL;

-- Notify PostgREST of schema change
NOTIFY pgrst, 'reload schema';

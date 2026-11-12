-- =====================================================
-- MIGRATION: Add ref_no (Reference Number) to users
-- =====================================================
-- Moved here from backend/db_migration_ref_no.sql, unchanged, as the first
-- entry in a tracked migration history — see supabase/README.md for why and
-- how to add the next one. The filename's leading timestamp is a best-effort
-- placeholder for when this was actually applied (it predates this
-- reorganization); it does not need to be exact, only earlier than whatever
-- migration comes next.

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

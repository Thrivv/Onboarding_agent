-- =====================================================
-- MIGRATION: schema sync with current code + i18n (2026-09-23)
-- =====================================================
-- Non-destructive, idempotent. Same changes as supabase/complete_schema.sql
-- ("WHAT CHANGED" list there), as a delta for `supabase db push`.

-- Trigger functions: pin search_path (linter: function_search_path_mutable)
ALTER FUNCTION public.update_updated_at_column()             SET search_path = public;
ALTER FUNCTION public.update_product_packages_updated_at()   SET search_path = public;
ALTER FUNCTION public.update_onboarding_session_updated_at() SET search_path = public;

-- 1. users.preferred_language — EN/AR/ES UI language saved on the account
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS preferred_language TEXT NOT NULL DEFAULT 'english';
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_preferred_language_check;
ALTER TABLE public.users
    ADD CONSTRAINT users_preferred_language_check
    CHECK (preferred_language IN ('english', 'arabic', 'spanish'));

-- 2. key_individuals — columns the code writes + source values it uses
ALTER TABLE public.key_individuals ADD COLUMN IF NOT EXISTS system_role      TEXT;
ALTER TABLE public.key_individuals ADD COLUMN IF NOT EXISTS contact_email    TEXT;
ALTER TABLE public.key_individuals ADD COLUMN IF NOT EXISTS phone_number     TEXT;
ALTER TABLE public.key_individuals ADD COLUMN IF NOT EXISTS share_percentage TEXT;
ALTER TABLE public.key_individuals DROP CONSTRAINT IF EXISTS key_individuals_source_check;
ALTER TABLE public.key_individuals
    ADD CONSTRAINT key_individuals_source_check
    CHECK (source IN ('MOA_EXTRACTED', 'MANUALLY_ADDED', 'DOCUMENT_EXTRACTED', 'AI_ADDED', 'SO_OWNER'));

-- 3. chat_references — read/written by reference_service.py, never created
CREATE TABLE IF NOT EXISTS public.chat_references (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ref_id           TEXT NOT NULL UNIQUE,
    user_email       TEXT NOT NULL,
    session_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at       TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_references_ref_id     ON public.chat_references(ref_id);
CREATE INDEX IF NOT EXISTS idx_chat_references_user_email ON public.chat_references(user_email);
CREATE INDEX IF NOT EXISTS idx_chat_references_is_active  ON public.chat_references(is_active);
GRANT ALL ON public.chat_references TO postgres, anon, authenticated, service_role;

-- 4. chat_sessions — indexes + updated_at trigger
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_email ON public.chat_sessions(user_email);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_is_active  ON public.chat_sessions(is_active);
DROP TRIGGER IF EXISTS trg_chat_sessions_updated_at ON public.chat_sessions;
CREATE TRIGGER trg_chat_sessions_updated_at
    BEFORE UPDATE ON public.chat_sessions
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- 5. conversations — history query index (chat load / reload / language switch)
CREATE INDEX IF NOT EXISTS idx_conversations_email_channel_ts
    ON public.conversations(user_email, channel, timestamp DESC);

-- 7. unused SECURITY DEFINER RPCs: no anon/authenticated EXECUTE
DO $$
BEGIN
    IF to_regprocedure('public.upsert_document_section(text,text,jsonb)') IS NOT NULL THEN
        REVOKE ALL ON FUNCTION public.upsert_document_section(TEXT, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
        GRANT EXECUTE ON FUNCTION public.upsert_document_section(TEXT, TEXT, JSONB) TO postgres, service_role;
    END IF;
    IF to_regprocedure('public.append_chat_message(text,jsonb)') IS NOT NULL THEN
        REVOKE ALL ON FUNCTION public.append_chat_message(TEXT, JSONB) FROM PUBLIC, anon, authenticated;
        GRANT EXECUTE ON FUNCTION public.append_chat_message(TEXT, JSONB) TO postgres, service_role;
    END IF;
END;
$$;

-- 8. RLS + explicit service_role policy on every existing table
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users', 'sessions', 'chat_sessions', 'chat_references', 'conversations',
        'tampering_test_reports', 'tampering_module_results',
        'tampering_tampered_regions', 'tampering_llm_analysis',
        'fatca_declarations', 'key_individuals', 'pep_declarations',
        'product_packages', 'onboarding_ui_sessions'
    ]
    LOOP
        IF to_regclass('public.' || t) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
            EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_service_role_all', t);
            EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
                           t || '_service_role_all', t);
        END IF;
    END LOOP;
    IF to_regclass('public.onboarding_ui_sessions') IS NOT NULL THEN
        DROP POLICY IF EXISTS "ous_service_role_all" ON public.onboarding_ui_sessions;
    END IF;
END;
$$;

COMMENT ON COLUMN public.users.preferred_language IS
    'UI language (english|arabic|spanish). Written by POST /system/user-language on every toggle; '
    'adopted by a browser with no local choice (new device / fresh login).';
COMMENT ON COLUMN public.conversations.metadata IS
    'Structured data for rich message rendering (documents, tables, extractions, card triggers). '
    'i18n keys: "language" (language the row was written in), "i18n" {english,arabic,spanish} '
    '(all renderings of a catalog message, served directly on a language switch), '
    '"message_key" (catalog template id), "translations" {<lang>: text} (cached LLM translations).';

NOTIFY pgrst, 'reload schema';

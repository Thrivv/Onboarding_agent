-- =====================================================================
-- GrowX / DigiOB Onboarding — COMPLETE SCHEMA (target state)
-- Updated 2026-09-23 against the live Supabase project zpgxiosbruiwtgwladmu
-- (columns, constraints, indexes, triggers, functions, RLS and grants were
-- re-read live) AND against what the current backend code actually writes.
--
-- SAFE TO RUN ON THE LIVE DATABASE AS-IS:
--   * every statement is idempotent (IF NOT EXISTS / DROP ... IF EXISTS /
--     CREATE OR REPLACE), so re-running it is a no-op;
--   * nothing here deletes a table, a column or a row. The destructive
--     cleanup (unused columns, the dead onboarding_ui_sessions table) is in
--     the OPTIONAL section at the very bottom, commented out.
-- Also works on an empty database to build the whole schema from scratch.
--
-- WHAT CHANGED vs the 2026-08-14 snapshot
-- ---------------------------------------------------------------------
--  1. users.preferred_language (NEW) — EN/AR/ES UI language saved on the
--     account (POST/GET /system/user-language). Default 'english'.
--  2. key_individuals — the code writes 4 fields that had no column
--     (system_role, contact_email, phone_number, share_percentage) and two
--     `source` values the CHECK rejected ('AI_ADDED', 'SO_OWNER'). Because
--     the backend upserts the whole record, every Key Individual added from
--     an uploaded ID and every Single-Owner owner row was being REJECTED by
--     Supabase (only MOA_EXTRACTED rows exist live: 12 of 12). Columns added
--     and the CHECK widened.
--  3. chat_references (NEW) — reference_service.py / chat.py already read
--     and write it; it did not exist, so every lookup returned "not found".
--  4. chat_sessions — added the missing updated_at trigger and indexes on
--     user_email / is_active (lookups are by email).
--  5. conversations — composite index for the history query the chat runs
--     on every load and language switch (user_email + channel, newest first).
--  6. Trigger functions pinned to `search_path = public` (Supabase linter:
--     "function_search_path_mutable").
--  7. The two unused SECURITY DEFINER RPCs on onboarding_ui_sessions were
--     EXECUTE-able by anon/authenticated — revoked (linter warning).
--  8. RLS: explicit service_role policy on every table (behaviour unchanged —
--     the backend only uses the service-role key, which bypasses RLS — but it
--     clears the "RLS enabled, no policy" linter notice), RLS on the new table.
-- =====================================================================


-- =====================================================================
-- EXTENSIONS
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto"           WITH SCHEMA extensions;  -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"          WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA extensions;


-- =====================================================================
-- SHARED TRIGGER FUNCTIONS
-- =====================================================================

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.update_product_packages_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- Only used by onboarding_ui_sessions (see section 15).
CREATE OR REPLACE FUNCTION public.update_onboarding_session_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


-- =====================================================================
-- 1. USERS — core account + onboarding-state table
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.users (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email                       TEXT NOT NULL UNIQUE,
    password_hash               TEXT NOT NULL,
    role                        TEXT DEFAULT 'user'
                                    CHECK (role IN ('user', 'admin')),
    first_name                  TEXT,
    last_name                   TEXT,
    name                        TEXT,
    phone_number                TEXT,
    dob                         DATE,

    business_name               TEXT,
    account_type                TEXT CHECK (account_type IN ('Savings', 'Corporate')),
    ownership_type              TEXT,
    partnership_details         TEXT,
    annual_turnover             TEXT,
    -- Unused anywhere in backend/frontend — see OPTIONAL CLEANUP at the bottom.
    corporate_owner_type        TEXT
                                    CHECK (corporate_owner_type IN ('single_owner', 'multi_type1', 'multi_type2')),
    net_worth                   TEXT,   -- unused, see OPTIONAL CLEANUP
    annual_net_profit           TEXT,   -- unused, see OPTIONAL CLEANUP
    nature_of_business          JSONB,
    incorporation_country       TEXT,
    incorporation_city          TEXT,
    channel                     TEXT,

    onboarding_step             TEXT DEFAULT 'welcome',
    has_seen_ai_welcome         BOOLEAN DEFAULT FALSE,
    self_declaration_submitted  BOOLEAN DEFAULT FALSE,
    ref_no                      TEXT UNIQUE,

    document_stage              TEXT DEFAULT 'identification',
    document_status             TEXT DEFAULT 'pending'
                                    CHECK (document_status IN (
                                        'pending', 'processing', 'verified',
                                        'rejected', 'manual_review'
                                    )),
    document_confirmation_sent  BOOLEAN DEFAULT FALSE,
    confirmation_timestamp      TIMESTAMP WITH TIME ZONE,
    user_in_company_docs        BOOLEAN,
    user_doc_validation         JSONB,

    tampering_score             FLOAT DEFAULT 0.0,
    tampering_report_id         UUID,   -- FK added after tampering_test_reports exists
    requires_manual_review      BOOLEAN DEFAULT FALSE,
    tampering_checked_at        TIMESTAMP WITH TIME ZONE,

    -- NEW (2026-09-23): UI language, written on every EN/AR/ES toggle.
    preferred_language          TEXT NOT NULL DEFAULT 'english',

    created_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Existing databases: CREATE TABLE IF NOT EXISTS does not add new columns.
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS preferred_language TEXT NOT NULL DEFAULT 'english';
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_preferred_language_check;
ALTER TABLE public.users
    ADD CONSTRAINT users_preferred_language_check
    CHECK (preferred_language IN ('english', 'arabic', 'spanish'));

CREATE INDEX IF NOT EXISTS idx_users_email                 ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_users_role                  ON public.users(role);
CREATE INDEX IF NOT EXISTS idx_users_onboarding            ON public.users(onboarding_step);
CREATE INDEX IF NOT EXISTS idx_users_account_type          ON public.users(account_type);
CREATE INDEX IF NOT EXISTS idx_users_document_status       ON public.users(document_status);
CREATE INDEX IF NOT EXISTS idx_users_requires_review       ON public.users(requires_manual_review);
CREATE INDEX IF NOT EXISTS idx_users_confirmation_ts       ON public.users(confirmation_timestamp);
CREATE INDEX IF NOT EXISTS idx_users_tampering_report      ON public.users(tampering_report_id);
CREATE INDEX IF NOT EXISTS idx_users_ai_welcome            ON public.users(has_seen_ai_welcome);
CREATE INDEX IF NOT EXISTS idx_users_incorporation_country ON public.users(incorporation_country);
CREATE INDEX IF NOT EXISTS idx_users_ref_no                ON public.users(ref_no);

DROP TRIGGER IF EXISTS trg_users_updated_at ON public.users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

COMMENT ON COLUMN public.users.preferred_language IS
    'UI language (english|arabic|spanish). Written by POST /system/user-language on every toggle; '
    'adopted by a browser with no local choice (new device / fresh login).';


-- =====================================================================
-- 2. SESSIONS — backend auth sessions (login tokens)
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.sessions (
    session_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    session_token   TEXT UNIQUE,
    refresh_token   TEXT,
    expires_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    ip_address      TEXT,
    user_agent      TEXT,
    last_activity   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id       ON public.sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_email         ON public.sessions(email);
CREATE INDEX IF NOT EXISTS idx_sessions_token         ON public.sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at    ON public.sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_is_active     ON public.sessions(is_active);
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON public.sessions(last_activity);

DROP TRIGGER IF EXISTS trg_sessions_updated_at ON public.sessions;
CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON public.sessions
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


-- =====================================================================
-- 3. CHAT_SESSIONS — "resume onboarding later" (REF-YYYY-XXXXXX),
--    driven by chat_session_service.py
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID REFERENCES public.users(id) ON DELETE CASCADE,
    user_email       TEXT NOT NULL,
    reference_number TEXT NOT NULL UNIQUE,
    last_message_id  UUID,
    is_active        BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- NEW: lookups are by user email; updated_at was never maintained.
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_email ON public.chat_sessions(user_email);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_is_active  ON public.chat_sessions(is_active);

DROP TRIGGER IF EXISTS trg_chat_sessions_updated_at ON public.chat_sessions;
CREATE TRIGGER trg_chat_sessions_updated_at
    BEFORE UPDATE ON public.chat_sessions
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


-- =====================================================================
-- 4. CHAT_REFERENCES — second "resume later" implementation
--    (MBK-YYYYMMDD-XXXXXX), driven by reference_service.py and read by
--    api/routes/chat.py (resolve_reference).
-- =====================================================================
-- NEW: did not exist live — every write failed silently and every lookup
-- returned "not found". Columns match exactly what reference_service.py
-- writes (ref_id, user_email, session_snapshot, created_at, expires_at,
-- is_active).

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


-- =====================================================================
-- 5. CONVERSATIONS — chat/message log
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email       TEXT NOT NULL,
    role             TEXT CHECK (role IN ('user', 'agent')),
    message          TEXT,
    channel          TEXT DEFAULT 'web'
                         CHECK (channel IN (
                             'web', 'chat', 'email', 'api',
                             'document_upload', 'ai_assistant'
                         )),
    metadata         JSONB DEFAULT NULL,
    timestamp        TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    chat_session_id  UUID REFERENCES public.chat_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversations_email     ON public.conversations(user_email);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON public.conversations(timestamp);
CREATE INDEX IF NOT EXISTS idx_conversations_role      ON public.conversations(role);
CREATE INDEX IF NOT EXISTS idx_conversations_channel   ON public.conversations(channel);
CREATE INDEX IF NOT EXISTS idx_conversations_metadata  ON public.conversations USING GIN (metadata);
-- NEW: GET /conversation-logs/{email}?channel=chat — newest first. Runs on
-- every chat load, reload and language switch.
CREATE INDEX IF NOT EXISTS idx_conversations_email_channel_ts
    ON public.conversations(user_email, channel, timestamp DESC);

COMMENT ON COLUMN public.conversations.metadata IS
    'Structured data for rich message rendering (documents, tables, extractions, card triggers). '
    'i18n keys: "language" (language the row was written in), "i18n" {english,arabic,spanish} '
    '(all renderings of a catalog message, served directly on a language switch), '
    '"message_key" (catalog template id), "translations" {<lang>: text} (cached LLM translations).';


-- =====================================================================
-- 6-9. TAMPERING / DOCUMENT FORENSICS
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.tampering_test_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email      TEXT,
    document_name   TEXT NOT NULL,
    document_type   TEXT,
    file_path       TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    overall_score   FLOAT NOT NULL,
    decision        TEXT NOT NULL CHECK (decision IN ('ACCEPT', 'ESCALATE', 'REJECT')),
    status          TEXT NOT NULL CHECK (status IN ('AUTHENTIC', 'REVIEW_REQUIRED', 'TAMPERED')),
    processing_time FLOAT,
    reason          TEXT,
    case_id         TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tamper_reports_created_at ON public.tampering_test_reports(created_at);
CREATE INDEX IF NOT EXISTS idx_tamper_reports_decision   ON public.tampering_test_reports(decision);
CREATE INDEX IF NOT EXISTS idx_tamper_reports_status     ON public.tampering_test_reports(status);
CREATE INDEX IF NOT EXISTS idx_tamper_reports_user_email ON public.tampering_test_reports(user_email);
CREATE INDEX IF NOT EXISTS idx_tamper_reports_doc_type   ON public.tampering_test_reports(document_type);

-- Deferred FK from users.tampering_report_id, now that this table exists.
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS fk_users_tampering_report;
ALTER TABLE public.users
    ADD CONSTRAINT fk_users_tampering_report
        FOREIGN KEY (tampering_report_id)
        REFERENCES public.tampering_test_reports(id)
        ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.tampering_module_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_report_id  UUID NOT NULL REFERENCES public.tampering_test_reports(id) ON DELETE CASCADE,
    module_name     TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PASS', 'ESCALATE', 'FAIL')),
    score           FLOAT NOT NULL,
    reason          TEXT,
    evidence        JSONB,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tamper_modules_report_id ON public.tampering_module_results(test_report_id);
CREATE INDEX IF NOT EXISTS idx_tamper_modules_name      ON public.tampering_module_results(module_name);
CREATE INDEX IF NOT EXISTS idx_tamper_modules_status    ON public.tampering_module_results(status);

CREATE TABLE IF NOT EXISTS public.tampering_tampered_regions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_report_id      UUID NOT NULL REFERENCES public.tampering_test_reports(id) ON DELETE CASCADE,
    module_name         TEXT NOT NULL,
    region_coordinates  JSONB NOT NULL,
    confidence          FLOAT NOT NULL,
    tampering_type      TEXT,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tamper_regions_report_id ON public.tampering_tampered_regions(test_report_id);

CREATE TABLE IF NOT EXISTS public.tampering_llm_analysis (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_report_id    UUID NOT NULL REFERENCES public.tampering_test_reports(id) ON DELETE CASCADE,
    analysis_text     TEXT NOT NULL,
    tampered_sections JSONB,
    recommendations   TEXT,
    generated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tamper_llm_report_id ON public.tampering_llm_analysis(test_report_id);


-- =====================================================================
-- 10. FATCA_DECLARATIONS
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.fatca_declarations (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    user_email                  TEXT NOT NULL,
    account_type                TEXT CHECK (account_type IN ('single_owner', 'multi_type1', 'multi_type2')),
    commercial_license_id       TEXT,
    fatca_applicable            BOOLEAN NOT NULL DEFAULT FALSE,
    entity_type                 TEXT,
    country_of_tax_residence    TEXT DEFAULT 'UAE',
    passive_nffe_us_ownership   TEXT,
    entity_incorporated_in_usa  BOOLEAN,
    entity_has_us_ownership     BOOLEAN,
    address_or_phone_in_usa     BOOLEAN,
    payment_instruction_to_usa  BOOLEAN,
    income_from_us_sources      BOOLEAN,
    irs_form_obtained           BOOLEAN,
    us_tax_id                   TEXT,
    created_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fatca_user_id    ON public.fatca_declarations(user_id);
CREATE INDEX IF NOT EXISTS idx_fatca_user_email ON public.fatca_declarations(user_email);

DROP TRIGGER IF EXISTS trg_fatca_updated_at ON public.fatca_declarations;
CREATE TRIGGER trg_fatca_updated_at
    BEFORE UPDATE ON public.fatca_declarations
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


-- =====================================================================
-- 11. KEY_INDIVIDUALS
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.key_individuals (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email                  TEXT NOT NULL,
    first_name                  TEXT NOT NULL,
    middle_name                 TEXT,
    last_name                   TEXT NOT NULL,
    display_name                TEXT,
    email                       TEXT,
    country                     TEXT DEFAULT 'UAE',
    country_code                TEXT,
    mobile_number               TEXT NOT NULL,
    telephone_number            TEXT,
    nationality                 TEXT,
    id_type                     TEXT CHECK (id_type IN ('EID', 'PASSPORT')),
    id_number                   TEXT NOT NULL,
    id_expiry_date              DATE,
    authentication_type         TEXT,
    date_of_birth               DATE,
    role                        TEXT,
    is_authorised_signatory     BOOLEAN NOT NULL DEFAULT FALSE,
    is_ubo                      BOOLEAN NOT NULL DEFAULT FALSE,
    document_id                 TEXT,
    verification_status         TEXT DEFAULT 'pending'
                                    CHECK (verification_status IN ('pending', 'verified', 'failed')),
    source                      TEXT DEFAULT 'MANUALLY_ADDED'
                                    CHECK (source IN (
                                        'MOA_EXTRACTED', 'MANUALLY_ADDED', 'DOCUMENT_EXTRACTED',
                                        'AI_ADDED', 'SO_OWNER'
                                    )),
    role_assigned_from_mismatch BOOLEAN DEFAULT FALSE,
    extracted_name              TEXT,
    extracted_business_name     TEXT,

    -- NEW (2026-09-23): collected by the KI details card (POST /ki/contact-info)
    -- and carried on the KI record; previously had no column, so the whole
    -- upsert was rejected.
    system_role                 TEXT,   -- 'Self Admin' | 'Maker' | 'Approver'
    contact_email               TEXT,
    phone_number                TEXT,   -- with country code, e.g. +971501234567
    share_percentage            TEXT,   -- as the code writes it: 25, 48.0 or '100%'

    created_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Existing databases: add the new columns and widen the source CHECK.
ALTER TABLE public.key_individuals ADD COLUMN IF NOT EXISTS system_role      TEXT;
ALTER TABLE public.key_individuals ADD COLUMN IF NOT EXISTS contact_email    TEXT;
ALTER TABLE public.key_individuals ADD COLUMN IF NOT EXISTS phone_number     TEXT;
ALTER TABLE public.key_individuals ADD COLUMN IF NOT EXISTS share_percentage TEXT;

ALTER TABLE public.key_individuals DROP CONSTRAINT IF EXISTS key_individuals_source_check;
ALTER TABLE public.key_individuals
    ADD CONSTRAINT key_individuals_source_check
    CHECK (source IN (
        'MOA_EXTRACTED',       -- from the MOA / Commercial License partner list
        'MANUALLY_ADDED',      -- POST /ki/add
        'DOCUMENT_EXTRACTED',  -- role assigned from a name-mismatch document
        'AI_ADDED',            -- added from an uploaded EID/Passport (POST /ki/add-ai)
        'SO_OWNER'             -- Single Owner's own record (POST /ki/so-as-selection)
    ));

CREATE INDEX IF NOT EXISTS idx_ki_user_email ON public.key_individuals(user_email);
CREATE INDEX IF NOT EXISTS idx_ki_source     ON public.key_individuals(source);
CREATE INDEX IF NOT EXISTS idx_ki_is_as      ON public.key_individuals(is_authorised_signatory);

DROP TRIGGER IF EXISTS trg_ki_updated_at ON public.key_individuals;
CREATE TRIGGER trg_ki_updated_at
    BEFORE UPDATE ON public.key_individuals
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


-- =====================================================================
-- 12. PEP_DECLARATIONS
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.pep_declarations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID REFERENCES public.users(id) ON DELETE CASCADE,
    user_email              TEXT NOT NULL,
    domestic_pep            BOOLEAN NOT NULL DEFAULT FALSE,
    domestic_pep_name       TEXT,
    domestic_pep_position   TEXT,
    foreign_pep             BOOLEAN NOT NULL DEFAULT FALSE,
    foreign_pep_country     TEXT,
    foreign_pep_name        TEXT,
    foreign_pep_position    TEXT,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pep_user_email ON public.pep_declarations(user_email);
CREATE INDEX IF NOT EXISTS idx_pep_user_id    ON public.pep_declarations(user_id);

DROP TRIGGER IF EXISTS trg_pep_updated_at ON public.pep_declarations;
CREATE TRIGGER trg_pep_updated_at
    BEFORE UPDATE ON public.pep_declarations
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


-- =====================================================================
-- 13. PRODUCT_PACKAGES
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.product_packages (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email          TEXT        NOT NULL UNIQUE,
    selected_package    TEXT        NOT NULL,
    availed_products    JSONB       NOT NULL DEFAULT '[]',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_product_packages_user_email ON public.product_packages(user_email);

DROP TRIGGER IF EXISTS trg_product_packages_updated_at ON public.product_packages;
CREATE TRIGGER trg_product_packages_updated_at
    BEFORE UPDATE ON public.product_packages
    FOR EACH ROW EXECUTE FUNCTION public.update_product_packages_updated_at();


-- =====================================================================
-- 14. ONBOARDING_UI_SESSIONS — UNUSED (0 rows, no code references).
--     Kept only because it physically exists live; drop it with the
--     OPTIONAL CLEANUP at the bottom when you're ready.
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.onboarding_ui_sessions (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id            TEXT        UNIQUE NOT NULL,
    user_id               UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    email                 TEXT        NOT NULL,
    current_step          TEXT        NOT NULL DEFAULT 'chat',
    chat_history          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    ui_state              JSONB       NOT NULL DEFAULT '{"sections":{}}'::jsonb,
    declaration_complete  BOOLEAN     NOT NULL DEFAULT FALSE,
    fatca_complete        BOOLEAN     NOT NULL DEFAULT FALSE,
    pep_complete          BOOLEAN     NOT NULL DEFAULT FALSE,
    is_active             BOOLEAN     NOT NULL DEFAULT TRUE,
    metadata              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ous_email_active
    ON public.onboarding_ui_sessions(email, is_active) WHERE is_active = TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ous_session_id
    ON public.onboarding_ui_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_ous_ui_state_gin
    ON public.onboarding_ui_sessions USING GIN (ui_state);

DROP TRIGGER IF EXISTS trg_ous_updated_at ON public.onboarding_ui_sessions;
CREATE TRIGGER trg_ous_updated_at
    BEFORE UPDATE ON public.onboarding_ui_sessions
    FOR EACH ROW EXECUTE FUNCTION public.update_onboarding_session_updated_at();

CREATE OR REPLACE FUNCTION public.upsert_document_section(
    p_session_id TEXT, p_doc_type TEXT, p_section_data JSONB
) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_current_ui_state JSONB; v_merged_section JSONB; v_updated_ui_state JSONB;
BEGIN
    SELECT ui_state INTO v_current_ui_state FROM public.onboarding_ui_sessions
     WHERE session_id = p_session_id AND is_active = TRUE FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Session not found or inactive: %', p_session_id; END IF;
    v_merged_section := COALESCE((v_current_ui_state -> 'sections' -> p_doc_type) || p_section_data, p_section_data);
    v_updated_ui_state := jsonb_set(COALESCE(v_current_ui_state, '{"sections":{}}'::jsonb),
        ARRAY['sections', p_doc_type], v_merged_section, TRUE);
    UPDATE public.onboarding_ui_sessions SET ui_state = v_updated_ui_state, updated_at = NOW()
     WHERE session_id = p_session_id AND is_active = TRUE;
    RETURN v_updated_ui_state;
END;
$$;

CREATE OR REPLACE FUNCTION public.append_chat_message(
    p_session_id TEXT, p_message JSONB
) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_current_history JSONB; v_updated_history JSONB;
BEGIN
    SELECT chat_history INTO v_current_history FROM public.onboarding_ui_sessions
     WHERE session_id = p_session_id AND is_active = TRUE FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Session not found or inactive: %', p_session_id; END IF;
    v_updated_history := COALESCE(v_current_history, '[]'::jsonb) || jsonb_build_array(p_message);
    UPDATE public.onboarding_ui_sessions SET chat_history = v_updated_history, updated_at = NOW()
     WHERE session_id = p_session_id AND is_active = TRUE;
    RETURN v_updated_history;
END;
$$;

-- SECURITY DEFINER functions must not be callable by anon/authenticated
-- (they were — Supabase linter warning). Backend-only from here on.
REVOKE ALL ON FUNCTION public.upsert_document_section(TEXT, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.append_chat_message(TEXT, JSONB)          FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_document_section(TEXT, TEXT, JSONB) TO postgres, service_role;
GRANT EXECUTE ON FUNCTION public.append_chat_message(TEXT, JSONB)          TO postgres, service_role;


-- =====================================================================
-- PERMISSIONS (unchanged from live: the backend always uses the
-- service-role key; RLS below is what actually narrows anon/authenticated)
-- =====================================================================

GRANT ALL ON ALL TABLES    IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES    TO postgres, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO postgres, anon, authenticated, service_role;


-- =====================================================================
-- ROW LEVEL SECURITY
-- =====================================================================
-- RLS on every table. anon/authenticated get NO policy, so they are denied
-- by default; service_role (the backend's key) gets an explicit allow-all
-- policy. Access is the same as before — service_role bypasses RLS in
-- Supabase anyway — but every table now has a policy, which clears the
-- "RLS enabled, no policy" linter notice and documents the intent.

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users', 'sessions', 'chat_sessions', 'chat_references', 'conversations',
        'tampering_test_reports', 'tampering_module_results',
        'tampering_tampered_regions', 'tampering_llm_analysis',
        'fatca_declarations', 'key_individuals', 'pep_declarations',
        'product_packages', 'onboarding_ui_sessions'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_service_role_all', t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
            t || '_service_role_all', t
        );
    END LOOP;
END;
$$;

-- The pre-existing policy on onboarding_ui_sessions is superseded by
-- onboarding_ui_sessions_service_role_all above (identical rule).
DROP POLICY IF EXISTS "ous_service_role_all" ON public.onboarding_ui_sessions;


-- =====================================================================
-- RELOAD PostgREST SCHEMA CACHE (so the API sees the new columns/table)
-- =====================================================================

NOTIFY pgrst, 'reload schema';


-- =====================================================================
-- OPTIONAL CLEANUP — DESTRUCTIVE, NOT RUN BY DEFAULT
-- =====================================================================
-- Remove the leading "-- " from a block to run it. Take a backup first;
-- dropped columns/tables cannot be recovered.
--
-- (a) users columns confirmed unused by backend and frontend:
-- ALTER TABLE public.users DROP COLUMN IF EXISTS corporate_owner_type;
-- ALTER TABLE public.users DROP COLUMN IF EXISTS net_worth;
-- ALTER TABLE public.users DROP COLUMN IF EXISTS annual_net_profit;
--
-- (b) onboarding_ui_sessions — 0 rows, no code references:
-- DROP FUNCTION IF EXISTS public.upsert_document_section(TEXT, TEXT, JSONB);
-- DROP FUNCTION IF EXISTS public.append_chat_message(TEXT, JSONB);
-- DROP TABLE    IF EXISTS public.onboarding_ui_sessions;
-- DROP FUNCTION IF EXISTS public.update_onboarding_session_updated_at();
-- NOTIFY pgrst, 'reload schema';

-- ============================================================================
-- OpenRecruiting — consolidated database schema
--
-- Apply this ONCE to a fresh Supabase project (SQL Editor → paste → Run).
-- See docs/setup/supabase.md for the full walkthrough.
--
-- PROVENANCE
--   Generated, not hand-written. The 132 sequential migrations plus the
--   data-fixes/ script from the original private repo were replayed in order
--   against a clean Postgres 17 / Supabase instance, and the resulting public
--   schema was dumped. Database identifiers were then de-branded (see below).
--
-- REPLAY NOTES (why the source migrations are not shipped individually)
--   The originals are re-runnable "paste into the SQL editor" scripts: several
--   open with `DROP TRIGGER/POLICY IF EXISTS ... ON <table>`. In Postgres the
--   IF EXISTS clause guards the trigger/policy, NOT the relation, so those
--   statements raise "relation does not exist" when replayed against an empty
--   database. Exactly 20 such statements did so, all in the drop-preamble of
--   01-auth-users.sql (lines 14-37), which then creates those same tables a few
--   lines later. No CREATE, ALTER, INSERT or function definition failed, so the
--   replayed schema is complete. No migration was skipped.
--
-- DE-BRANDED IDENTIFIERS
--   Columns and defaults carrying the original vendor name were renamed in
--   lockstep with the application code. The current, canonical names are:
--     profiles.is_staff                        (staff flag)
--     feedback_access_tokens.is_registered_user
--     rounds.ai_screenable / .ai_screenable_reason
--     ats_entity_links.native_type / .native_id (local side of an ATS link)
--     requisitions.source / candidates.source default 'native'
--       CHECK constraint accepts ('native','ats_sync')
--
--   One rename needed more than a search-and-replace: public.is_admin()
--   declared a local variable whose name collided with the new column name.
--   It is now v_is_staff, and the column reference is alias-qualified.
--
-- SECURITY
--   The REVOKE EXECUTE ... FROM authenticated, PUBLIC statements on the
--   SECURITY DEFINER functions are load-bearing. Do not strip them: they are
--   what keeps those functions callable only by service_role.
-- ============================================================================

-- Extensions. Schema placement mirrors a stock Supabase project: uuid-ossp and
-- pgcrypto live in "extensions"; pgvector is used as public.vector(1536).
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto   WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS vector     WITH SCHEMA public;

--
-- PostgreSQL database dump
--


-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.7 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;


--
-- Name: intake_modality; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.intake_modality AS ENUM (
    'voice',
    'text'
);


--
-- Name: intake_session_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.intake_session_status AS ENUM (
    'created',
    'prefilling',
    'ready',
    'active',
    'submitted',
    'published',
    'abandoned'
);


--
-- Name: add_candidate_with_backfill(uuid, text, text, text, text, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.add_candidate_with_backfill(p_req_id uuid, p_name text, p_email text, p_phone text, p_resume_url text, p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_req_status      TEXT;
    v_candidate_id    UUID;
    v_candidate_row   JSONB;
    v_counts          JSONB;
BEGIN
    -- 1. Verify requisition exists for this org.
    SELECT status
    INTO v_req_status
    FROM requisitions
    WHERE id = p_req_id
      AND organization_id = p_org_id
      AND deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    IF v_req_status = 'closed' THEN
        RAISE EXCEPTION 'REQ_CLOSED' USING ERRCODE = 'P0001';
    END IF;

    IF v_req_status <> 'planned' THEN
        RAISE EXCEPTION 'REQ_NOT_PLANNED' USING ERRCODE = 'P0001';
    END IF;

    -- 2. Insert the candidate.
    INSERT INTO candidates (
        requisition_id, name, email, phone, resume_url, status
    )
    VALUES (
        p_req_id, p_name, p_email, p_phone, p_resume_url, 'active'
    )
    RETURNING id INTO v_candidate_id;

    -- 3. Eager-backfill: one pending CR per active shared round.
    -- ON CONFLICT references the partial unique index
    -- idx_candidate_rounds_unique_non_generic (candidate_id, round_id)
    -- WHERE source_type <> 'untracked_generic' — must restate the
    -- predicate so Postgres picks the partial index.
    INSERT INTO candidate_rounds (candidate_id, round_id, status)
    SELECT v_candidate_id, r.id, 'pending'
    FROM rounds r
    WHERE r.requisition_id = p_req_id
      AND r.for_candidate_id IS NULL
      AND r.removed_from_plan_at IS NULL
      AND r.deleted_at IS NULL
    ON CONFLICT (candidate_id, round_id)
      WHERE source_type <> 'untracked_generic'
      DO NOTHING;

    -- 4. Build the candidate response row.
    SELECT to_jsonb(c)
    INTO v_candidate_row
    FROM candidates c
    WHERE c.id = v_candidate_id;

    -- 5. Compute the post-insert role counts (mirrors the role-header endpoint).
    SELECT jsonb_build_object(
        'candidates_total',    COUNT(*) FILTER (WHERE c.deleted_at IS NULL),
        'candidates_active',   COUNT(*) FILTER (WHERE c.deleted_at IS NULL AND c.status = 'active'),
        'candidates_hired',    COUNT(*) FILTER (WHERE c.deleted_at IS NULL AND c.status = 'hired'),
        'candidates_rejected', COUNT(*) FILTER (WHERE c.deleted_at IS NULL AND c.status = 'rejected'),
        'rounds_total',        (
            SELECT COUNT(*)
            FROM rounds r
            WHERE r.requisition_id = p_req_id
              AND r.for_candidate_id IS NULL
              AND r.removed_from_plan_at IS NULL
              AND r.deleted_at IS NULL
        )
    )
    INTO v_counts
    FROM candidates c
    WHERE c.requisition_id = p_req_id;

    RETURN jsonb_build_object(
        'candidate', v_candidate_row,
        'counts',    v_counts
    );
END;
$$;


--
-- Name: add_custom_round(uuid, uuid, text, text, integer, text, jsonb, jsonb, jsonb, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.add_custom_round(p_req_id uuid, p_candidate_id uuid, p_name text, p_category text, p_duration_minutes integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_req_status      TEXT;
    v_cand_status     TEXT;
    v_round_id        UUID;
    v_round_number    INT;
    v_cr_id           UUID;
    v_skills_arr      TEXT[];
    v_guidelines      JSONB;
    v_round_row       JSONB;
    v_cr_row          JSONB;
BEGIN
    -- 1. Verify requisition exists for this org.
    SELECT status
    INTO v_req_status
    FROM requisitions
    WHERE id = p_req_id
      AND organization_id = p_org_id
      AND deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    IF v_req_status = 'closed' THEN
        RAISE EXCEPTION 'REQ_CLOSED' USING ERRCODE = 'P0001';
    END IF;

    -- 2. Verify candidate belongs to this requisition AND is not deleted.
    SELECT status
    INTO v_cand_status
    FROM candidates
    WHERE id = p_candidate_id
      AND requisition_id = p_req_id
      AND deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- 3. Refuse to add a custom round to a non-active candidate.
    IF v_cand_status <> 'active' THEN
        RAISE EXCEPTION 'CANDIDATE_INACTIVE' USING ERRCODE = 'P0001';
    END IF;

    -- 4. (CHANGED from migration 83): Compute next round_number across BOTH
    -- shared plan rounds AND this candidate's existing custom rounds, scoped to
    -- the requisition. This guarantees the new custom round always appends
    -- after the shared rounds rather than colliding at round_number = 1.
    --
    -- Inclusion criteria:
    --   for_candidate_id IS NULL       → shared rounds in the plan
    --   for_candidate_id = p_candidate_id → this candidate's custom rounds
    -- Excludes other candidates' custom rounds (different for_candidate_id).
    -- removed_from_plan_at IS NULL excludes soft-removed shared rounds.
    -- Custom rounds always have removed_from_plan_at NULL (they can only be
    -- hard-deleted), so this filter is a safe no-op on the custom side.
    SELECT COALESCE(MAX(round_number), 0) + 1
    INTO v_round_number
    FROM rounds
    WHERE requisition_id = p_req_id
      AND deleted_at IS NULL
      AND (for_candidate_id IS NULL OR for_candidate_id = p_candidate_id)
      AND removed_from_plan_at IS NULL;

    -- 5. Coerce skills JSONB to TEXT[] (rounds.skills is a Postgres text array).
    v_skills_arr := CASE
        WHEN p_skills IS NULL OR jsonb_typeof(p_skills) = 'null' THEN '{}'::text[]
        WHEN jsonb_typeof(p_skills) = 'array' THEN
            ARRAY(SELECT jsonb_array_elements_text(p_skills))
        ELSE '{}'::text[]
    END;

    v_guidelines := COALESCE(p_guidelines, '[]'::jsonb);
    IF jsonb_typeof(v_guidelines) <> 'array' THEN
        v_guidelines := '[]'::jsonb;
    END IF;

    -- 6. Insert the custom round.
    INSERT INTO rounds (
        requisition_id, round_number, name, category, duration_minutes,
        description, skills, guidelines, for_candidate_id
    )
    VALUES (
        p_req_id, v_round_number, p_name, p_category,
        COALESCE(p_duration_minutes, 45),
        p_description, v_skills_arr, v_guidelines, p_candidate_id
    )
    RETURNING id INTO v_round_id;

    -- 7. Insert feedback_questions if provided.
    IF p_feedback_questions IS NOT NULL
       AND jsonb_typeof(p_feedback_questions) = 'array'
       AND jsonb_array_length(p_feedback_questions) > 0
    THEN
        INSERT INTO feedback_questions (round_id, question_number, heading, description)
        SELECT
            v_round_id,
            COALESCE(
                NULLIF((q->>'question_number'), '')::int,
                (row_number() OVER (ORDER BY ord))::int
            ),
            q->>'heading',
            q->>'description'
        FROM jsonb_array_elements(p_feedback_questions) WITH ORDINALITY AS t(q, ord);
    END IF;

    -- 8. Insert one pending candidate_round for this candidate + new round.
    -- No ON CONFLICT — the round is brand new; no race.
    INSERT INTO candidate_rounds (candidate_id, round_id, status)
    VALUES (p_candidate_id, v_round_id, 'pending')
    RETURNING id INTO v_cr_id;

    -- 9. Build the round response (mirrors plan-tab shape + custom fields).
    SELECT jsonb_build_object(
        'id',               r.id,
        'round_number',     r.round_number,
        'name',             r.name,
        'category',         r.category,
        'duration_minutes', r.duration_minutes,
        'description',      r.description,
        'skills',           COALESCE(to_jsonb(r.skills), '[]'::jsonb),
        'guidelines',       COALESCE(r.guidelines, '[]'::jsonb),
        'is_custom',        (r.for_candidate_id IS NOT NULL),
        'for_candidate_id', r.for_candidate_id,
        'feedback_questions', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id',              fq.id,
                'question_number', fq.question_number,
                'heading',         fq.heading,
                'description',     fq.description
            ) ORDER BY fq.question_number)
            FROM feedback_questions fq
            WHERE fq.round_id = r.id AND fq.deleted_at IS NULL
        ), '[]'::jsonb)
    )
    INTO v_round_row
    FROM rounds r
    WHERE r.id = v_round_id;

    SELECT to_jsonb(cr)
    INTO v_cr_row
    FROM candidate_rounds cr
    WHERE cr.id = v_cr_id;

    RETURN jsonb_build_object(
        'round',           v_round_row,
        'candidate_round', v_cr_row
    );
END;
$$;


--
-- Name: add_shared_round(uuid, text, text, integer, integer, text, jsonb, jsonb, jsonb, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.add_shared_round(p_req_id uuid, p_name text, p_category text, p_duration_minutes integer, p_position integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_round_id      UUID;
    v_round_number  INT;
    v_skills_arr    TEXT[];
    v_guidelines    JSONB;
    v_result        JSONB;
BEGIN
    -- 1. Verify the requisition belongs to this org.
    IF NOT EXISTS (
        SELECT 1
        FROM requisitions
        WHERE id = p_req_id
          AND organization_id = p_org_id
          AND deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- 2. Compute the target round_number.
    IF p_position IS NOT NULL AND p_position > 0 THEN
        -- Offset-then-settle: shift everything at p_position and above by a
        -- large constant first to avoid violating the partial unique index
        -- during the +1 settle.
        UPDATE rounds
        SET round_number = round_number + 100000,
            updated_at = NOW()
        WHERE requisition_id = p_req_id
          AND for_candidate_id IS NULL
          AND removed_from_plan_at IS NULL
          AND deleted_at IS NULL
          AND round_number >= p_position;

        UPDATE rounds
        SET round_number = round_number - 100000 + 1,
            updated_at = NOW()
        WHERE requisition_id = p_req_id
          AND for_candidate_id IS NULL
          AND removed_from_plan_at IS NULL
          AND deleted_at IS NULL
          AND round_number >= p_position + 100000;

        v_round_number := p_position;
    ELSE
        SELECT COALESCE(MAX(round_number), 0) + 1
        INTO v_round_number
        FROM rounds
        WHERE requisition_id = p_req_id
          AND for_candidate_id IS NULL
          AND removed_from_plan_at IS NULL
          AND deleted_at IS NULL;
    END IF;

    -- 3. Coerce skills JSONB to TEXT[] (rounds.skills is a Postgres text array).
    v_skills_arr := CASE
        WHEN p_skills IS NULL OR jsonb_typeof(p_skills) = 'null' THEN '{}'::text[]
        WHEN jsonb_typeof(p_skills) = 'array' THEN
            ARRAY(SELECT jsonb_array_elements_text(p_skills))
        ELSE '{}'::text[]
    END;

    -- Default guidelines to empty JSONB array if NULL/missing.
    v_guidelines := COALESCE(p_guidelines, '[]'::jsonb);
    IF jsonb_typeof(v_guidelines) <> 'array' THEN
        v_guidelines := '[]'::jsonb;
    END IF;

    -- 4. INSERT the round.
    INSERT INTO rounds (
        requisition_id, round_number, name, category, duration_minutes,
        description, skills, guidelines
    )
    VALUES (
        p_req_id, v_round_number, p_name, p_category,
        COALESCE(p_duration_minutes, 45),
        p_description, v_skills_arr, v_guidelines
    )
    RETURNING id INTO v_round_id;

    -- 5. INSERT feedback_questions if provided (array of {heading, description, question_number?}).
    IF p_feedback_questions IS NOT NULL
       AND jsonb_typeof(p_feedback_questions) = 'array'
       AND jsonb_array_length(p_feedback_questions) > 0
    THEN
        INSERT INTO feedback_questions (round_id, question_number, heading, description)
        SELECT
            v_round_id,
            COALESCE(
                NULLIF((q->>'question_number'), '')::int,
                (row_number() OVER (ORDER BY ord))::int
            ),
            q->>'heading',
            q->>'description'
        FROM jsonb_array_elements(p_feedback_questions) WITH ORDINALITY AS t(q, ord);
    END IF;

    -- 6. Eager backfill of candidate_rounds for every active candidate.
    -- Note the ON CONFLICT clause targets the named unique constraint, not
    -- a bare column tuple. unique_candidate_round is declared in migration 02.
    INSERT INTO candidate_rounds (candidate_id, round_id, status)
    SELECT c.id, v_round_id, 'pending'
    FROM candidates c
    WHERE c.requisition_id = p_req_id
      AND c.status = 'active'
      AND c.deleted_at IS NULL
    ON CONFLICT ON CONSTRAINT unique_candidate_round DO NOTHING;

    -- 7. Build the response (plan-tab shape).
    SELECT jsonb_build_object(
        'id',               r.id,
        'round_number',     r.round_number,
        'name',             r.name,
        'category',         r.category,
        'duration_minutes', r.duration_minutes,
        'description',      r.description,
        'skills',           COALESCE(to_jsonb(r.skills), '[]'::jsonb),
        'guidelines',       COALESCE(r.guidelines, '[]'::jsonb),
        'feedback_questions', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id',              fq.id,
                'question_number', fq.question_number,
                'heading',         fq.heading,
                'description',     fq.description
            ) ORDER BY fq.question_number)
            FROM feedback_questions fq
            WHERE fq.round_id = r.id AND fq.deleted_at IS NULL
        ), '[]'::jsonb)
    )
    INTO v_result
    FROM rounds r
    WHERE r.id = v_round_id;

    RETURN v_result;
END;
$$;


--
-- Name: admin_archive_organization(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.admin_archive_organization(p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_deleted_at  TIMESTAMPTZ := now();
    v_org_deleted TIMESTAMPTZ;
    v_user_ids    UUID[];
BEGIN
    SELECT deleted_at INTO v_org_deleted
    FROM organizations
    WHERE id = p_org_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Organization not found' USING ERRCODE = 'P0002';
    END IF;

    IF v_org_deleted IS NOT NULL THEN
        RAISE EXCEPTION 'ALREADY_ARCHIVED' USING ERRCODE = 'P0001';
    END IF;

    -- Soft-delete the org's currently-active profiles; capture their ids.
    WITH updated AS (
        UPDATE profiles
        SET deleted_at = v_deleted_at
        WHERE organization_id = p_org_id
          AND deleted_at IS NULL
        RETURNING id
    )
    SELECT COALESCE(array_agg(id), ARRAY[]::UUID[]) INTO v_user_ids FROM updated;

    UPDATE organizations
    SET deleted_at = v_deleted_at
    WHERE id = p_org_id;

    RETURN jsonb_build_object(
        'organization_id', p_org_id,
        'user_ids',        to_jsonb(v_user_ids)
    );
END;
$$;


--
-- Name: admin_restore_organization(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.admin_restore_organization(p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_org_deleted TIMESTAMPTZ;
    v_user_ids    UUID[];
BEGIN
    SELECT deleted_at INTO v_org_deleted
    FROM organizations
    WHERE id = p_org_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Organization not found' USING ERRCODE = 'P0002';
    END IF;

    IF v_org_deleted IS NULL THEN
        RAISE EXCEPTION 'NOT_ARCHIVED' USING ERRCODE = 'P0001';
    END IF;

    WITH updated AS (
        UPDATE profiles
        SET deleted_at = NULL
        WHERE organization_id = p_org_id
          AND deleted_at IS NOT NULL
        RETURNING id
    )
    SELECT COALESCE(array_agg(id), ARRAY[]::UUID[]) INTO v_user_ids FROM updated;

    UPDATE organizations
    SET deleted_at = NULL
    WHERE id = p_org_id;

    RETURN jsonb_build_object(
        'organization_id', p_org_id,
        'user_ids',        to_jsonb(v_user_ids)
    );
END;
$$;


--
-- Name: admin_set_structured_feedback(uuid, text, text, text, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.admin_set_structured_feedback(p_cr_id uuid, p_summary text, p_rating text, p_source text, p_feedback jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_round_id      UUID;
    v_valid_qids    UUID[];
    v_incoming_qid  UUID;
    v_incoming_ids  UUID[];
    v_entry         JSONB;
    v_fb_id         UUID;
    v_evidence      JSONB;
    v_updated_cr    JSONB;
    v_entries       JSONB;
BEGIN
    SELECT round_id INTO v_round_id
    FROM candidate_rounds
    WHERE id = p_cr_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Candidate round not found' USING ERRCODE = 'P0002';
    END IF;

    -- Set of valid (non-deleted) question ids for this round.
    SELECT COALESCE(array_agg(id), ARRAY[]::UUID[]) INTO v_valid_qids
    FROM feedback_questions
    WHERE round_id = v_round_id
      AND deleted_at IS NULL;

    -- Validate every incoming question id belongs to the round; collect the
    -- set of incoming feedback row ids (those that carry an id to update).
    v_incoming_ids := ARRAY[]::UUID[];
    IF p_feedback IS NOT NULL AND jsonb_typeof(p_feedback) = 'array' THEN
        FOR v_entry IN SELECT jsonb_array_elements(p_feedback)
        LOOP
            v_incoming_qid := (v_entry->>'feedback_question_id')::uuid;
            IF NOT (v_incoming_qid = ANY(v_valid_qids)) THEN
                RAISE EXCEPTION 'BAD_QUESTION' USING ERRCODE = 'P0001';
            END IF;
            IF v_entry ? 'id' AND v_entry->>'id' IS NOT NULL THEN
                v_incoming_ids := v_incoming_ids || (v_entry->>'id')::uuid;
            END IF;
        END LOOP;
    END IF;

    -- Round-level summary/rating.
    UPDATE candidate_rounds
    SET summary = p_summary,
        rating  = p_rating
    WHERE id = p_cr_id;

    -- Delete existing feedback rows for this round that are not in the incoming
    -- set (preserves the prior "removed-on-resubmit" semantics).
    DELETE FROM candidate_feedback
    WHERE candidate_round_id = p_cr_id
      AND NOT (id = ANY(v_incoming_ids));

    -- Insert or update each incoming entry.
    IF p_feedback IS NOT NULL AND jsonb_typeof(p_feedback) = 'array' THEN
        FOR v_entry IN SELECT jsonb_array_elements(p_feedback)
        LOOP
            v_incoming_qid := (v_entry->>'feedback_question_id')::uuid;

            v_evidence := v_entry->'evidence';
            IF v_evidence IS NULL OR jsonb_typeof(v_evidence) <> 'array' THEN
                v_evidence := '[]'::jsonb;
            END IF;

            v_fb_id := NULL;
            IF v_entry ? 'id' AND v_entry->>'id' IS NOT NULL THEN
                v_fb_id := (v_entry->>'id')::uuid;
            END IF;

            -- SECURITY: the existence check is scoped to THIS round so a feedback
            -- id from another round can never be matched and overwritten.
            IF v_fb_id IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM candidate_feedback
                   WHERE id = v_fb_id AND candidate_round_id = p_cr_id
               ) THEN
                UPDATE candidate_feedback
                SET feedback_question_id = v_incoming_qid,
                    feedback_text        = v_entry->>'feedback_data',
                    evidence             = v_evidence,
                    evidence_status      = v_entry->>'evidence_status',
                    source               = COALESCE(p_source, 'manual'),
                    updated_at           = now()
                WHERE id = v_fb_id
                  AND candidate_round_id = p_cr_id;
            ELSE
                INSERT INTO candidate_feedback (
                    candidate_round_id, feedback_question_id,
                    feedback_text, evidence, evidence_status, source
                )
                VALUES (
                    p_cr_id, v_incoming_qid,
                    v_entry->>'feedback_data',
                    v_evidence,
                    v_entry->>'evidence_status',
                    COALESCE(p_source, 'manual')
                );
            END IF;
        END LOOP;
    END IF;

    -- Return the updated CR plus the ordered feedback set (joined to the
    -- question metadata the router needs).
    SELECT to_jsonb(cr) INTO v_updated_cr
    FROM candidate_rounds cr WHERE cr.id = p_cr_id;

    SELECT COALESCE(jsonb_agg(row_to_json(f) ORDER BY f.created_at), '[]'::jsonb)
    INTO v_entries
    FROM (
        SELECT cf.*,
               jsonb_build_object(
                   'heading',         fq.heading,
                   'question_number', fq.question_number,
                   'description',     fq.description
               ) AS feedback_questions
        FROM candidate_feedback cf
        LEFT JOIN feedback_questions fq ON fq.id = cf.feedback_question_id
        WHERE cf.candidate_round_id = p_cr_id
    ) f;

    RETURN jsonb_build_object(
        'candidate_round', v_updated_cr,
        'entries',         v_entries
    );
END;
$$;


--
-- Name: admin_submit_candidate_feedback(uuid, text, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.admin_submit_candidate_feedback(p_cr_id uuid, p_source text, p_feedback jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_round_id      UUID;
    v_valid_qids    UUID[];
    v_entry         JSONB;
    v_incoming_qid  UUID;
    v_fb_id         UUID;
    v_written_ids   UUID[];
    v_new_id        UUID;
    v_rows          JSONB;
BEGIN
    SELECT round_id INTO v_round_id
    FROM candidate_rounds
    WHERE id = p_cr_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Candidate round not found' USING ERRCODE = 'P0002';
    END IF;

    -- Set of valid (non-deleted) question ids for this round.
    SELECT COALESCE(array_agg(id), ARRAY[]::UUID[]) INTO v_valid_qids
    FROM feedback_questions
    WHERE round_id = v_round_id
      AND deleted_at IS NULL;

    -- Validate every incoming question id belongs to the round BEFORE writing
    -- anything (the old code validated all items up front, then wrote).
    IF p_feedback IS NOT NULL AND jsonb_typeof(p_feedback) = 'array' THEN
        FOR v_entry IN SELECT jsonb_array_elements(p_feedback)
        LOOP
            v_incoming_qid := (v_entry->>'feedback_question_id')::uuid;
            IF NOT (v_incoming_qid = ANY(v_valid_qids)) THEN
                RAISE EXCEPTION 'BAD_QUESTION' USING ERRCODE = 'P0001';
            END IF;
        END LOOP;
    END IF;

    -- Insert or update each incoming entry, collecting the written row ids in
    -- payload order (a single row per entry, preserving the response order).
    v_written_ids := ARRAY[]::UUID[];
    IF p_feedback IS NOT NULL AND jsonb_typeof(p_feedback) = 'array' THEN
        FOR v_entry IN SELECT jsonb_array_elements(p_feedback)
        LOOP
            v_incoming_qid := (v_entry->>'feedback_question_id')::uuid;

            v_fb_id := NULL;
            IF v_entry ? 'id' AND v_entry->>'id' IS NOT NULL THEN
                v_fb_id := (v_entry->>'id')::uuid;
            END IF;

            IF v_fb_id IS NOT NULL THEN
                UPDATE candidate_feedback
                SET feedback_question_id = v_incoming_qid,
                    feedback_text        = v_entry->>'feedback_text',
                    source               = COALESCE(p_source, 'manual'),
                    updated_at           = now()
                WHERE id = v_fb_id
                  AND candidate_round_id = p_cr_id;

                IF NOT FOUND THEN
                    -- Old loop returned 404 for an update target that does not
                    -- exist on this candidate round.
                    RAISE EXCEPTION 'FEEDBACK_NOT_FOUND' USING ERRCODE = 'P0001';
                END IF;

                v_written_ids := v_written_ids || v_fb_id;
            ELSE
                INSERT INTO candidate_feedback (
                    candidate_round_id, feedback_question_id,
                    feedback_text, source
                )
                VALUES (
                    p_cr_id, v_incoming_qid,
                    v_entry->>'feedback_text',
                    COALESCE(p_source, 'manual')
                )
                RETURNING id INTO v_new_id;

                v_written_ids := v_written_ids || v_new_id;
            END IF;
        END LOOP;
    END IF;

    -- Return the written rows in the order they were written (payload order),
    -- so the router builds SubmitFeedbackResponse identically to the old code.
    SELECT COALESCE(jsonb_agg(row_to_json(cf) ORDER BY ord), '[]'::jsonb)
    INTO v_rows
    FROM unnest(v_written_ids) WITH ORDINALITY AS w(fb_id, ord)
    JOIN candidate_feedback cf ON cf.id = w.fb_id;

    RETURN v_rows;
END;
$$;


--
-- Name: ats_apply_dirty_update(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_apply_dirty_update(p_org_id uuid, p_requisition_id uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_link ats_entity_links%ROWTYPE;
    v_fields jsonb;
BEGIN
    SELECT * INTO v_link FROM ats_entity_links
     WHERE organization_id = p_org_id AND native_type = 'requisition'
       AND native_id = p_requisition_id;
    IF v_link.id IS NULL OR NOT v_link.ats_dirty OR v_link.ats_dirty_payload IS NULL THEN
        RETURN jsonb_build_object('action', 'noop');
    END IF;
    v_fields := v_link.ats_dirty_payload;

    UPDATE requisitions SET
        role_title = COALESCE(v_fields->>'role_title', role_title),
        role_location = COALESCE(v_fields->>'role_location', role_location),
        job_description = COALESCE(v_fields->>'job_description', job_description),
        experience_min_years = COALESCE((v_fields->>'experience_min_years')::int, experience_min_years),
        experience_max_years = COALESCE((v_fields->>'experience_max_years')::int, experience_max_years),
        ats_synced_at = now(), updated_at = now()
     WHERE id = p_requisition_id;

    UPDATE ats_entity_links
       SET ats_dirty = false, ats_dirty_payload = NULL, updated_at = now()
     WHERE id = v_link.id;
    RETURN jsonb_build_object('action', 'applied', 'id', p_requisition_id);
END; $$;


--
-- Name: ats_connect(uuid, text, text, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_connect(p_org_id uuid, p_provider text, p_integration_id text, p_user_id uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_id uuid;
BEGIN
    UPDATE ats_connections
       SET status = 'inactive', deactivated_at = now(), updated_at = now()
     WHERE organization_id = p_org_id
       AND status = 'active'
       AND knit_integration_id <> p_integration_id;

    INSERT INTO ats_connections (
        organization_id, provider, knit_integration_id, status,
        connected_by, connected_at, last_verified_at
    ) VALUES (
        p_org_id, p_provider, p_integration_id, 'active',
        p_user_id, now(), now()
    )
    ON CONFLICT (knit_integration_id) DO UPDATE SET
        organization_id = EXCLUDED.organization_id,
        provider = EXCLUDED.provider,
        status = 'active',
        connected_by = EXCLUDED.connected_by,
        connected_at = now(),
        last_verified_at = now(),
        deactivated_at = NULL,
        updated_at = now()
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;


--
-- Name: ats_enrich_candidate(uuid, uuid, jsonb, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_enrich_candidate(p_candidate_id uuid, p_org_id uuid, p_profile jsonb, p_resume_url text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE v_ok integer;
BEGIN
    UPDATE candidates c SET
        profile = p_profile,
        resume_url = COALESCE(p_resume_url, c.resume_url),
        enrichment_status = 'done', enrichment_error = NULL,
        enriched_at = now(), updated_at = now()
    FROM requisitions r
    WHERE c.id = p_candidate_id AND c.requisition_id = r.id AND r.organization_id = p_org_id;
    GET DIAGNOSTICS v_ok = ROW_COUNT;
    RETURN jsonb_build_object('updated', v_ok > 0);
END; $$;


--
-- Name: ats_import_job(uuid, uuid, text, text, jsonb, text, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_import_job(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_job_id text, p_fields jsonb, p_ats_status text, p_user_id uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_link ats_entity_links%ROWTYPE;
    v_req_id uuid;
    v_req_status text;
    v_req_deleted timestamptz;
BEGIN
    SELECT * INTO v_link FROM ats_entity_links
     WHERE organization_id = p_org_id AND ats_type = 'job' AND ats_id = p_ats_job_id;

    IF v_link.id IS NULL THEN
        INSERT INTO requisitions (
            organization_id, created_by, role_title, role_location,
            experience_min_years, experience_max_years, status,
            job_description, must_have_skills, good_to_have_skills,
            source, ats_provider, ats_synced_at
        ) VALUES (
            p_org_id, p_user_id,
            p_fields->>'role_title',
            COALESCE(p_fields->>'role_location', 'Not specified'),
            COALESCE((p_fields->>'experience_min_years')::int, 0),
            (p_fields->>'experience_max_years')::int,
            'intake_pending',
            p_fields->>'job_description',
            CASE WHEN p_fields ? 'must_have_skills'
                 THEN ARRAY(SELECT jsonb_array_elements_text(p_fields->'must_have_skills')) END,
            CASE WHEN p_fields ? 'good_to_have_skills'
                 THEN ARRAY(SELECT jsonb_array_elements_text(p_fields->'good_to_have_skills')) END,
            'ats_sync', p_provider, now()
        ) RETURNING id INTO v_req_id;

        INSERT INTO ats_entity_links (
            organization_id, connection_id, provider, native_type, native_id,
            ats_type, ats_id, ats_status, last_synced_at
        ) VALUES (
            p_org_id, p_connection_id, p_provider, 'requisition', v_req_id,
            'job', p_ats_job_id, p_ats_status, now()
        );
        RETURN jsonb_build_object('action', 'created', 'requisition_id', v_req_id);
    END IF;

    SELECT status, deleted_at INTO v_req_status, v_req_deleted
      FROM requisitions WHERE id = v_link.native_id;

    IF v_req_deleted IS NOT NULL OR v_req_status = 'closed' OR v_req_status IS NULL THEN
        UPDATE ats_entity_links
           SET ats_status = p_ats_status, last_synced_at = now(), updated_at = now()
         WHERE id = v_link.id;
        RETURN jsonb_build_object('action', 'skipped', 'requisition_id', v_link.native_id);
    END IF;

    IF v_req_status IN ('draft', 'intake_pending') THEN
        UPDATE requisitions SET
            role_title = COALESCE(p_fields->>'role_title', role_title),
            role_location = COALESCE(p_fields->>'role_location', role_location),
            job_description = COALESCE(p_fields->>'job_description', job_description),
            experience_min_years = COALESCE((p_fields->>'experience_min_years')::int, experience_min_years),
            experience_max_years = COALESCE((p_fields->>'experience_max_years')::int, experience_max_years),
            ats_synced_at = now(), updated_at = now()
         WHERE id = v_link.native_id;
        UPDATE ats_entity_links
           SET ats_status = p_ats_status, ats_dirty = false, ats_dirty_payload = NULL,
               last_synced_at = now(), updated_at = now()
         WHERE id = v_link.id;
        RETURN jsonb_build_object('action', 'updated', 'requisition_id', v_link.native_id);
    END IF;

    -- planned: never mutate — flag for recruiter review
    UPDATE ats_entity_links
       SET ats_dirty = true, ats_dirty_payload = p_fields, ats_status = p_ats_status,
           last_synced_at = now(), updated_at = now()
     WHERE id = v_link.id;
    RETURN jsonb_build_object('action', 'flagged', 'requisition_id', v_link.native_id);
END; $$;


--
-- Name: ats_mark_deleted(uuid, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_mark_deleted(p_org_id uuid, p_ats_type text, p_ats_id text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_link ats_entity_links%ROWTYPE;
    v_req_status text;
BEGIN
    SELECT * INTO v_link FROM ats_entity_links
     WHERE organization_id = p_org_id AND ats_type = p_ats_type AND ats_id = p_ats_id;
    IF v_link.id IS NULL THEN
        RETURN jsonb_build_object('action', 'noop');
    END IF;

    UPDATE ats_entity_links SET ats_deleted = true, last_synced_at = now(),
           updated_at = now() WHERE id = v_link.id;

    IF v_link.native_type = 'requisition' THEN
        SELECT status INTO v_req_status FROM requisitions WHERE id = v_link.native_id;
        IF v_req_status IN ('draft', 'intake_pending') THEN
            UPDATE requisitions SET deleted_at = now(), updated_at = now()
             WHERE id = v_link.native_id AND deleted_at IS NULL;
            RETURN jsonb_build_object('action', 'soft_deleted', 'id', v_link.native_id);
        END IF;
    END IF;
    RETURN jsonb_build_object('action', 'flagged', 'id', v_link.native_id);
END; $$;


--
-- Name: ats_promote_interviews(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_promote_interviews(p_requisition_id uuid, p_org uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_promoted jsonb := '[]'::jsonb;
    rec record;
    v_cr_id uuid;
    v_new_status text;
    v_interviewer jsonb;
BEGIN
    -- Guard: requisition belongs to the org.
    PERFORM 1 FROM requisitions
     WHERE id = p_requisition_id AND organization_id = p_org;
    IF NOT FOUND THEN
        RETURN '[]'::jsonb;
    END IF;

    FOR rec IN
        SELECT
            ai.id                AS interview_id,
            ai.ats_interview_event_id,
            ai.scheduled_start,
            ai.meeting_url,
            ai.interviewers,
            ai.notetaker_transcript_id,
            ai.status            AS ats_status,
            c.id                 AS candidate_id,
            c.name               AS candidate_name,
            m.round_id           AS round_id
        FROM ats_interviews ai
        JOIN ats_stage_round_map m
          ON m.requisition_id = p_requisition_id
         AND m.ats_stage_id   = ai.ats_stage_id
        JOIN ats_entity_links el
          ON el.organization_id = p_org
         AND el.native_type      = 'candidate'
         AND el.ats_type        = 'application'
         AND el.ats_id          = ai.ats_application_id
        JOIN candidates c
          ON c.id = el.native_id
         AND c.requisition_id = p_requisition_id
         AND c.deleted_at IS NULL
        WHERE ai.organization_id = p_org
          AND ai.candidate_round_id IS NULL  -- only not-yet-promoted interviews
    LOOP
        -- Map the Ashby event status onto candidate_rounds.status.
        v_new_status := CASE
            WHEN rec.ats_status = 'Complete'  THEN 'completed'
            WHEN rec.ats_status = 'Scheduled' THEN 'scheduled'
            ELSE 'scheduled'
        END;

        -- First interviewer entry (jsonb array of {email,name,ats_user_id}).
        v_interviewer := CASE
            WHEN jsonb_typeof(rec.interviewers) = 'array'
                 AND jsonb_array_length(rec.interviewers) > 0
            THEN rec.interviewers->0 ELSE NULL END;

        -- UPSERT the candidate_round: ATS candidates have none yet, so create it;
        -- on a re-promote (round already exists) refresh schedule/meeting/status.
        -- The partial unique index idx_candidate_rounds_unique_non_generic
        -- (candidate_id, round_id) WHERE source_type <> 'untracked_generic'
        -- backs this conflict target ('ats_scheduled' qualifies).
        INSERT INTO candidate_rounds (
            candidate_id, round_id, scheduled_at, meeting_url,
            interviewer_email, interviewer_name, status, source_type
        ) VALUES (
            rec.candidate_id, rec.round_id, rec.scheduled_start, rec.meeting_url,
            v_interviewer->>'email', v_interviewer->>'name', v_new_status, 'ats_scheduled'
        )
        ON CONFLICT (candidate_id, round_id) WHERE source_type <> 'untracked_generic'
        DO UPDATE SET
            scheduled_at      = EXCLUDED.scheduled_at,
            meeting_url       = COALESCE(EXCLUDED.meeting_url, candidate_rounds.meeting_url),
            interviewer_email = COALESCE(EXCLUDED.interviewer_email, candidate_rounds.interviewer_email),
            interviewer_name  = COALESCE(EXCLUDED.interviewer_name, candidate_rounds.interviewer_name),
            status            = EXCLUDED.status,
            updated_at        = now()
        RETURNING id INTO v_cr_id;

        UPDATE ats_interviews
           SET candidate_round_id = v_cr_id, updated_at = now()
         WHERE id = rec.interview_id;

        v_promoted := v_promoted || jsonb_build_object(
            'candidate_round_id',      v_cr_id,
            'scheduled_start',         rec.scheduled_start,
            'meeting_url',             rec.meeting_url,
            'notetaker_transcript_id', rec.notetaker_transcript_id,
            'status',                  v_new_status,
            'ats_interview_event_id',  rec.ats_interview_event_id,
            'candidate_name',          rec.candidate_name,
            'organization_id',         p_org
        );
    END LOOP;

    RETURN v_promoted;
END; $$;


--
-- Name: ats_upsert_candidate(uuid, uuid, text, text, text, jsonb, text, text, text, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_upsert_candidate(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_application_id text, p_ats_candidate_id text, p_fields jsonb, p_ats_status text, p_stage_id text, p_stage_name text, p_profile jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_link ats_entity_links%ROWTYPE;
    v_req_id uuid;
    v_cand_id uuid;
    v_cand_deleted timestamptz;
    v_old_status text;
    v_new_status text;
BEGIN
    SELECT * INTO v_link FROM ats_entity_links
     WHERE organization_id = p_org_id AND ats_type = 'application'
       AND ats_id = p_ats_application_id;
    v_new_status := COALESCE(p_fields->>'status', 'active');

    IF v_link.id IS NOT NULL THEN
        SELECT deleted_at, status INTO v_cand_deleted, v_old_status
          FROM candidates WHERE id = v_link.native_id;
        IF v_cand_deleted IS NOT NULL THEN
            RETURN jsonb_build_object('action', 'skipped', 'candidate_id', v_link.native_id);
        END IF;
        UPDATE candidates SET
            name   = COALESCE(p_fields->>'name', name),
            email  = COALESCE(p_fields->>'email', email),
            phone  = COALESCE(p_fields->>'phone', phone),
            status = COALESCE(p_fields->>'status', status),
            profile = CASE WHEN enrichment_status IS DISTINCT FROM 'done'
                           THEN COALESCE(profile, '{}'::jsonb) || p_profile
                           ELSE profile END,
            enrichment_status = CASE
                WHEN v_old_status IS DISTINCT FROM 'rejected' AND v_new_status = 'rejected'
                THEN 'pending' ELSE enrichment_status END,
            ats_synced_at = now(), updated_at = now()
         WHERE id = v_link.native_id;
        UPDATE ats_entity_links SET
            ats_status = p_ats_status, ats_stage_id = p_stage_id,
            ats_stage_name = p_stage_name, ats_candidate_id = p_ats_candidate_id,
            last_synced_at = now(), updated_at = now()
         WHERE id = v_link.id;
        RETURN jsonb_build_object('action', 'updated', 'candidate_id', v_link.native_id);
    END IF;

    SELECT native_id INTO v_req_id FROM ats_entity_links
     WHERE organization_id = p_org_id AND ats_type = 'job'
       AND ats_id = p_fields->>'ats_job_id';
    IF v_req_id IS NULL THEN
        RETURN jsonb_build_object('action', 'orphaned');
    END IF;

    INSERT INTO candidates (
        requisition_id, name, email, phone, status, source, ats_synced_at,
        profile, enrichment_status
    ) VALUES (
        v_req_id, p_fields->>'name', p_fields->>'email', p_fields->>'phone',
        v_new_status, 'ats_sync', now(),
        COALESCE(p_profile, '{}'::jsonb), 'pending'
    ) RETURNING id INTO v_cand_id;

    INSERT INTO ats_entity_links (
        organization_id, connection_id, provider, native_type, native_id,
        ats_type, ats_id, ats_candidate_id, ats_status, ats_stage_id,
        ats_stage_name, last_synced_at
    ) VALUES (
        p_org_id, p_connection_id, p_provider, 'candidate', v_cand_id,
        'application', p_ats_application_id, p_ats_candidate_id, p_ats_status,
        p_stage_id, p_stage_name, now()
    );
    RETURN jsonb_build_object('action', 'created', 'candidate_id', v_cand_id);
END; $$;


--
-- Name: ats_upsert_interview(uuid, uuid, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_upsert_interview(p_org uuid, p_connection uuid, p_fields jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_event_id text := p_fields->>'ats_interview_event_id';
    v_id uuid;
    v_inserted boolean;
BEGIN
    IF v_event_id IS NULL OR v_event_id = '' THEN
        RAISE EXCEPTION 'MISSING_EVENT_ID';
    END IF;

    INSERT INTO ats_interviews (
        organization_id, connection_id, provider,
        ats_application_id, ats_interview_event_id, ats_schedule_id,
        ats_interview_id, ats_stage_id, stage_name, interview_title,
        scheduled_start, scheduled_end, status, interviewers,
        meeting_url, feedback_link, has_submitted_feedback,
        notetaker_transcript_id, raw, last_synced_at
    ) VALUES (
        p_org, p_connection, COALESCE(p_fields->>'provider', 'ashby'),
        p_fields->>'ats_application_id', v_event_id, p_fields->>'ats_schedule_id',
        p_fields->>'ats_interview_id', p_fields->>'ats_stage_id',
        p_fields->>'stage_name', p_fields->>'interview_title',
        (p_fields->>'scheduled_start')::timestamptz,
        (p_fields->>'scheduled_end')::timestamptz,
        p_fields->>'status',
        COALESCE(p_fields->'interviewers', '[]'::jsonb),
        p_fields->>'meeting_url', p_fields->>'feedback_link',
        COALESCE((p_fields->>'has_submitted_feedback')::boolean, false),
        p_fields->>'notetaker_transcript_id',
        p_fields->'raw', now()
    )
    ON CONFLICT (organization_id, ats_interview_event_id) DO UPDATE SET
        connection_id = EXCLUDED.connection_id,
        ats_application_id = COALESCE(EXCLUDED.ats_application_id, ats_interviews.ats_application_id),
        ats_schedule_id = COALESCE(EXCLUDED.ats_schedule_id, ats_interviews.ats_schedule_id),
        ats_interview_id = COALESCE(EXCLUDED.ats_interview_id, ats_interviews.ats_interview_id),
        ats_stage_id = COALESCE(EXCLUDED.ats_stage_id, ats_interviews.ats_stage_id),
        stage_name = COALESCE(EXCLUDED.stage_name, ats_interviews.stage_name),
        interview_title = COALESCE(EXCLUDED.interview_title, ats_interviews.interview_title),
        scheduled_start = COALESCE(EXCLUDED.scheduled_start, ats_interviews.scheduled_start),
        scheduled_end = COALESCE(EXCLUDED.scheduled_end, ats_interviews.scheduled_end),
        status = COALESCE(EXCLUDED.status, ats_interviews.status),
        interviewers = EXCLUDED.interviewers,
        meeting_url = COALESCE(EXCLUDED.meeting_url, ats_interviews.meeting_url),
        feedback_link = COALESCE(EXCLUDED.feedback_link, ats_interviews.feedback_link),
        has_submitted_feedback = EXCLUDED.has_submitted_feedback,
        notetaker_transcript_id = COALESCE(EXCLUDED.notetaker_transcript_id, ats_interviews.notetaker_transcript_id),
        raw = COALESCE(EXCLUDED.raw, ats_interviews.raw),
        last_synced_at = now(),
        updated_at = now()
    RETURNING id, (xmax = 0) INTO v_id, v_inserted;

    RETURN jsonb_build_object('action', CASE WHEN v_inserted THEN 'inserted' ELSE 'updated' END, 'id', v_id);
END; $$;


--
-- Name: ats_upsert_stage_round_map(uuid, uuid, uuid, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ats_upsert_stage_round_map(p_org_id uuid, p_requisition_id uuid, p_round_id uuid, p_ats_stage_id text, p_ats_stage_name text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_ok boolean;
    v_id uuid;
    v_inserted boolean;
BEGIN
    -- Guard: round belongs to requisition, requisition belongs to org.
    SELECT true INTO v_ok
      FROM rounds rd JOIN requisitions r ON r.id = rd.requisition_id
     WHERE rd.id = p_round_id AND rd.requisition_id = p_requisition_id
       AND r.organization_id = p_org_id;
    IF v_ok IS NOT TRUE THEN
        RETURN jsonb_build_object('action', 'rejected', 'reason', 'round/req/org mismatch');
    END IF;

    INSERT INTO ats_stage_round_map (
        organization_id, requisition_id, ats_stage_id, ats_stage_name, round_id
    ) VALUES (
        p_org_id, p_requisition_id, p_ats_stage_id, p_ats_stage_name, p_round_id
    )
    ON CONFLICT (requisition_id, ats_stage_id) DO UPDATE SET
        round_id = EXCLUDED.round_id,
        ats_stage_name = EXCLUDED.ats_stage_name,
        organization_id = EXCLUDED.organization_id,
        updated_at = now()
    RETURNING id, (xmax = 0) INTO v_id, v_inserted;
    RETURN jsonb_build_object(
        'action', CASE WHEN v_inserted THEN 'created' ELSE 'updated' END,
        'id', v_id
    );
END; $$;


--
-- Name: cancel_candidate_round(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cancel_candidate_round(p_cr_id uuid, p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_cr_status   TEXT;
    v_updated_cr  JSONB;
BEGIN
    -- 1. Look up CR + verify org chain.
    SELECT cr.status
    INTO v_cr_status
    FROM candidate_rounds cr
    JOIN candidates  c ON c.id = cr.candidate_id
    JOIN requisitions q ON q.id = c.requisition_id
    WHERE cr.id = p_cr_id
      AND q.organization_id = p_org_id
      AND q.deleted_at IS NULL
      AND c.deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- 2. Cannot cancel a completed round (it's terminal — use /reprocess).
    IF v_cr_status = 'completed' THEN
        RAISE EXCEPTION 'ALREADY_COMPLETED' USING ERRCODE = 'P0001';
    END IF;

    -- 3. Idempotent: if already cancelled, just return the current row without
    -- writing. The Python handler will still try to clean up any in-flight bot.
    IF v_cr_status <> 'cancelled' THEN
        UPDATE candidate_rounds
        SET status     = 'cancelled',
            updated_at = NOW()
        WHERE id = p_cr_id;
    END IF;

    SELECT to_jsonb(cr) INTO v_updated_cr
    FROM candidate_rounds cr WHERE cr.id = p_cr_id;

    RETURN jsonb_build_object(
        'candidate_round', v_updated_cr
    );
END;
$$;


--
-- Name: claim_feedback_processing(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.claim_feedback_processing(p_cr_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  v_count integer;
BEGIN
  UPDATE public.candidate_rounds
     SET processing_status = 'processing',
         processing_started_at = now(),
         updated_at = now()
   WHERE id = p_cr_id
     AND (processing_status IS NULL OR processing_status <> 'processing');

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count > 0;
END;
$$;


--
-- Name: claim_intake_processing(uuid, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.claim_intake_processing(p_requisition_id uuid, p_stale_seconds integer DEFAULT 300) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_current_status text;
    v_started_at timestamptz;
BEGIN
    SELECT intake_processing_status, intake_processing_started_at
    INTO v_current_status, v_started_at
    FROM requisitions
    WHERE id = p_requisition_id AND deleted_at IS NULL
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN false;
    END IF;

    IF v_current_status = 'processing' AND v_started_at IS NOT NULL THEN
        IF EXTRACT(EPOCH FROM (now() - v_started_at)) < p_stale_seconds THEN
            RETURN false;
        END IF;
    END IF;

    UPDATE requisitions SET
        intake_processing_status = 'processing',
        intake_processing_started_at = now(),
        intake_processing_error = NULL,
        intake_processing_stage = 'summarizing'
    WHERE id = p_requisition_id;

    RETURN true;
END;
$$;


--
-- Name: cortex_backfill_org_event(text, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_backfill_org_event(event_type text, org_id uuid) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  inserted INT := 0;
BEGIN
  IF event_type = 'feedback_debrief_available' THEN
    INSERT INTO cortex_events (event_type, source_id, org_id, source_table, last_touch_at)
    SELECT 'feedback_debrief_available', cr.id, r.organization_id, 'backfill',
           COALESCE(cr.processing_completed_at, cr.updated_at)
    FROM candidate_rounds cr
    JOIN rounds rnd ON rnd.id = cr.round_id
    JOIN requisitions r ON r.id = rnd.requisition_id
    WHERE r.organization_id = cortex_backfill_org_event.org_id
      AND cr.processing_status = 'completed'
      AND COALESCE(cr.processing_completed_at, cr.updated_at) < now() - interval '48 hours'
    ON CONFLICT (event_type, source_id) DO NOTHING;
    GET DIAGNOSTICS inserted = ROW_COUNT;
    RETURN inserted;
  ELSIF event_type = 'intake_transcript_available' THEN
    INSERT INTO cortex_events (event_type, source_id, org_id, source_table, last_touch_at)
    SELECT 'intake_transcript_available', r.id, r.organization_id, 'backfill',
           COALESCE(r.intake_processing_completed_at, r.updated_at)
    FROM requisitions r
    WHERE r.organization_id = cortex_backfill_org_event.org_id
      AND r.intake_processing_status = 'completed'
      AND COALESCE(r.intake_processing_completed_at, r.updated_at) < now() - interval '48 hours'
    ON CONFLICT (event_type, source_id) DO NOTHING;
    GET DIAGNOSTICS inserted = ROW_COUNT;
    RETURN inserted;
  ELSIF event_type = 'decision_made' THEN
    INSERT INTO cortex_events (event_type, source_id, org_id, source_table, last_touch_at)
    SELECT 'decision_made', c.id, r.organization_id, 'backfill', c.updated_at
    FROM candidates c
    JOIN requisitions r ON r.id = c.requisition_id
    WHERE r.organization_id = cortex_backfill_org_event.org_id
      AND c.final_verdict IS NOT NULL
      AND c.updated_at < now() - interval '48 hours'
    ON CONFLICT (event_type, source_id) DO NOTHING;
    GET DIAGNOSTICS inserted = ROW_COUNT;
    RETURN inserted;
  ELSE
    RAISE EXCEPTION 'unknown event_type: %', event_type;
  END IF;
END;
$$;


--
-- Name: cortex_emit_candidate_event(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_emit_candidate_event() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_org_id UUID;
BEGIN
  SELECT organization_id INTO v_org_id FROM requisitions WHERE id = NEW.requisition_id;

  IF v_org_id IS NULL THEN
    RETURN NEW;
  END IF;

  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'decision_made',
    NEW.id,
    v_org_id,
    TG_TABLE_NAME,
    jsonb_build_object('candidate_id', NEW.id, 'requisition_id', NEW.requisition_id),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  RETURN NEW;
END;
$$;


--
-- Name: cortex_emit_candidate_feedback_event(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_emit_candidate_feedback_event() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_org_id UUID;
  v_target_round UUID;
BEGIN
  v_target_round := COALESCE(NEW.candidate_round_id, OLD.candidate_round_id);

  SELECT r.organization_id INTO v_org_id
  FROM candidate_rounds cr
  JOIN rounds rnd ON rnd.id = cr.round_id
  JOIN requisitions r ON r.id = rnd.requisition_id
  WHERE cr.id = v_target_round;

  IF v_org_id IS NULL THEN
    RETURN COALESCE(NEW, OLD);
  END IF;

  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'feedback_debrief_available',
    v_target_round,
    v_org_id,
    TG_TABLE_NAME,
    jsonb_build_object('candidate_round_id', v_target_round),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'feedback_completed',
    v_target_round,
    v_org_id,
    TG_TABLE_NAME,
    jsonb_build_object('candidate_round_id', v_target_round),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  RETURN COALESCE(NEW, OLD);
END;
$$;


--
-- Name: cortex_emit_candidate_round_event(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_emit_candidate_round_event() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_org_id UUID;
BEGIN
  SELECT r.organization_id INTO v_org_id
  FROM rounds rnd
  JOIN requisitions r ON r.id = rnd.requisition_id
  WHERE rnd.id = NEW.round_id;

  IF v_org_id IS NULL THEN
    RETURN NEW;
  END IF;

  -- Episodic (LLM-extracted concepts via FeedbackDebriefHandler)
  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'feedback_debrief_available',
    NEW.id,
    v_org_id,
    TG_TABLE_NAME,
    jsonb_build_object('candidate_id', NEW.candidate_id, 'round_id', NEW.round_id),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  -- Structured (FeedbackHandler creates Candidate-INTERVIEWED_IN-Round-ASSESSES-Competency)
  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'feedback_completed',
    NEW.id,
    v_org_id,
    TG_TABLE_NAME,
    jsonb_build_object('candidate_id', NEW.candidate_id, 'round_id', NEW.round_id),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  RETURN NEW;
END;
$$;


--
-- Name: cortex_emit_requisition_event(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_emit_requisition_event() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
  -- Episodic (LLM-extracted intake concepts via IntakeHandler)
  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'intake_transcript_available',
    NEW.id,
    NEW.organization_id,
    TG_TABLE_NAME,
    jsonb_build_object('requisition_id', NEW.id),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  -- Structured (PlanHandler creates Org-HOSTS-Requisition-HAS_ROUND-Round-ASSESSES-Competency)
  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'plan_created',
    NEW.id,
    NEW.organization_id,
    TG_TABLE_NAME,
    jsonb_build_object('requisition_id', NEW.id),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  RETURN NEW;
END;
$$;


--
-- Name: cortex_emit_round_event(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_emit_round_event() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_org_id UUID;
BEGIN
  SELECT organization_id INTO v_org_id FROM requisitions WHERE id = NEW.requisition_id;

  IF v_org_id IS NULL THEN
    RETURN NEW;
  END IF;

  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'intake_transcript_available',
    NEW.requisition_id,
    v_org_id,
    TG_TABLE_NAME,
    jsonb_build_object('requisition_id', NEW.requisition_id, 'round_id', NEW.id),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'plan_created',
    NEW.requisition_id,
    v_org_id,
    TG_TABLE_NAME,
    jsonb_build_object('requisition_id', NEW.requisition_id, 'round_id', NEW.id),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  RETURN NEW;
END;
$$;


--
-- Name: cortex_emit_transcript_event(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_emit_transcript_event() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_org_id UUID;
BEGIN
  SELECT r.organization_id INTO v_org_id
  FROM candidate_rounds cr
  JOIN rounds rnd ON rnd.id = cr.round_id
  JOIN requisitions r ON r.id = rnd.requisition_id
  WHERE cr.id = NEW.candidate_round_id;

  IF v_org_id IS NULL THEN
    RETURN NEW;
  END IF;

  INSERT INTO cortex_events (event_type, source_id, org_id, source_table, payload_keys, last_touch_at)
  VALUES (
    'interview_transcript_available',
    NEW.candidate_round_id,
    v_org_id,
    TG_TABLE_NAME,
    jsonb_build_object('candidate_round_id', NEW.candidate_round_id),
    NOW()
  )
  ON CONFLICT (event_type, source_id) DO UPDATE SET last_touch_at = NOW();

  RETURN NEW;
END;
$$;


--
-- Name: cortex_events_for_org_unpublished(uuid, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_events_for_org_unpublished(p_org_id uuid, p_limit integer) RETURNS TABLE(id uuid, event_type text, source_id uuid, org_id uuid, last_touch_at timestamp with time zone, publish_count integer)
    LANGUAGE sql STABLE
    AS $$
  SELECT id, event_type, source_id, org_id, last_touch_at, publish_count
  FROM cortex_events
  WHERE org_id = p_org_id
    AND (published_at IS NULL OR last_touch_at > published_at)
  ORDER BY last_touch_at ASC
  LIMIT p_limit;
$$;


--
-- Name: cortex_events_settled(timestamp with time zone, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cortex_events_settled(cutoff timestamp with time zone, "limit" integer) RETURNS TABLE(id uuid, event_type text, source_id uuid, org_id uuid, last_touch_at timestamp with time zone, publish_count integer)
    LANGUAGE sql STABLE
    AS $$
  SELECT id, event_type, source_id, org_id, last_touch_at, publish_count
  FROM cortex_events
  WHERE (published_at IS NULL OR last_touch_at > published_at)
    AND last_touch_at < cutoff
  ORDER BY last_touch_at ASC
  LIMIT "limit";
$$;


--
-- Name: debrief_commit_draft(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.debrief_commit_draft(p_packet_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_req_id       uuid;
    v_status       text;
    v_cands        uuid[];
    v_sorted_cands uuid[];
    v_lock_key     text;
BEGIN
    -- Pin the natural key + current status from the target row.
    SELECT requisition_id, status, candidate_ids
    INTO v_req_id, v_status, v_cands
    FROM debrief_packets
    WHERE id = p_packet_id;

    IF v_req_id IS NULL OR v_status <> 'draft' THEN
        RAISE EXCEPTION 'Debrief draft not found' USING ERRCODE = 'P0002';
    END IF;

    -- Serialize concurrent commits/generates for the SAME (requisition_id,
    -- candidate SET). Sort the candidate_ids so the lock key is order-independent
    -- ({A,B} == {B,A}), matching the set-equality supersede predicate below. The
    -- transaction-scoped lock auto-releases on commit/rollback.
    SELECT array_agg(c ORDER BY c) INTO v_sorted_cands FROM unnest(v_cands) AS c;
    v_lock_key := v_req_id::text || ':' || array_to_string(v_sorted_cands, ',');
    PERFORM pg_advisory_xact_lock(hashtextextended(v_lock_key, 0));

    -- 1. Supersede the prior fresh packet for the same (req, candidate SET).
    UPDATE debrief_packets
    SET status = 'superseded', updated_at = now()
    WHERE requisition_id = v_req_id
      AND status = 'fresh'
      AND id <> p_packet_id
      AND candidate_ids @> v_cands
      AND v_cands @> candidate_ids;

    -- 2. Commit THIS draft row to fresh.
    UPDATE debrief_packets
    SET status     = 'fresh',
        updated_at = now()
    WHERE id = p_packet_id;
END $$;


--
-- Name: debrief_conversation_append_turn(uuid, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.debrief_conversation_append_turn(p_packet_id uuid, p_turn jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE v_org uuid; v_turns jsonb; v_idx int;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext(p_packet_id::text));
    SELECT organization_id INTO v_org FROM debrief_packets WHERE id = p_packet_id;
    IF v_org IS NULL THEN RAISE EXCEPTION 'packet not found'; END IF;
    INSERT INTO debrief_conversations (packet_id, organization_id)
        VALUES (p_packet_id, v_org)
        ON CONFLICT (packet_id) DO NOTHING;
    SELECT turns INTO v_turns FROM debrief_conversations WHERE packet_id = p_packet_id FOR UPDATE;
    v_idx := jsonb_array_length(v_turns);
    v_turns := v_turns || (p_turn || jsonb_build_object('idx', v_idx));
    UPDATE debrief_conversations SET turns = v_turns, updated_at = now() WHERE packet_id = p_packet_id;
    RETURN (p_turn || jsonb_build_object('idx', v_idx));
END; $$;


--
-- Name: debrief_supersede_and_insert(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.debrief_supersede_and_insert(p jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_packet_id    uuid := (p->>'packet_id')::uuid;
    v_req_id       uuid;
    v_org_id       uuid;
    v_cands        uuid[];
    v_sorted_cands uuid[];
    v_lock_key     text;
BEGIN
    -- Pin the natural key from the persisted target row (authoritative over the
    -- payload, so a reordered candidate_ids array still supersedes correctly).
    SELECT requisition_id, organization_id, candidate_ids
    INTO v_req_id, v_org_id, v_cands
    FROM debrief_packets
    WHERE id = v_packet_id;

    IF v_req_id IS NULL THEN
        RAISE EXCEPTION 'Debrief packet not found' USING ERRCODE = 'P0002';
    END IF;

    -- Serialize concurrent generates for the SAME (requisition_id, candidate SET).
    -- Sort the candidate_ids so the lock key is order-independent ({A,B} == {B,A}),
    -- matching the order-independent set-equality supersede predicate below. The
    -- transaction-scoped lock auto-releases on commit/rollback.
    SELECT array_agg(c ORDER BY c) INTO v_sorted_cands FROM unnest(v_cands) AS c;
    v_lock_key := v_req_id::text || ':' || array_to_string(v_sorted_cands, ',');
    PERFORM pg_advisory_xact_lock(hashtextextended(v_lock_key, 0));

    -- 1. Supersede prior fresh packets for the same (req, candidate SET).
    UPDATE debrief_packets
    SET status = 'superseded', updated_at = now()
    WHERE requisition_id = v_req_id
      AND status = 'fresh'
      AND id <> v_packet_id
      AND candidate_ids @> v_cands
      AND v_cands @> candidate_ids;

    -- 2. Finalize the target row.
    UPDATE debrief_packets
    SET status       = 'fresh',
        packet       = (p->'packet'),
        generation_error = NULL,
        generated_at = now(),
        updated_at   = now()
    WHERE id = v_packet_id;

    RETURN jsonb_build_object('packet_id', v_packet_id, 'status', 'fresh');
END $$;


--
-- Name: delete_candidate_round(uuid, uuid, uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.delete_candidate_round(p_req_id uuid, p_candidate_id uuid, p_cr_id uuid, p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_cr_status        TEXT;
    v_cr_candidate_id  UUID;
    v_round_id         UUID;
    v_for_candidate_id UUID;
    v_deleted_round_id UUID;
BEGIN
    -- 1. Look up CR + round + verify the org chain.
    SELECT cr.status, cr.candidate_id, cr.round_id, r.for_candidate_id
    INTO v_cr_status, v_cr_candidate_id, v_round_id, v_for_candidate_id
    FROM candidate_rounds cr
    JOIN candidates c   ON c.id = cr.candidate_id
    JOIN requisitions q ON q.id = c.requisition_id
    JOIN rounds r       ON r.id = cr.round_id
    WHERE cr.id = p_cr_id
      AND c.requisition_id = p_req_id
      AND q.organization_id = p_org_id
      AND q.deleted_at IS NULL
      AND c.deleted_at IS NULL
      AND r.deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- 2. URL consistency: candidate_id in the URL must match the CR's owner.
    IF v_cr_candidate_id <> p_candidate_id THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- 3. Only pending CRs may be removed via this endpoint.
    IF v_cr_status <> 'pending' THEN
        RAISE EXCEPTION 'NOT_PENDING' USING ERRCODE = 'P0001';
    END IF;

    -- 4. Defensive cleanup: drop any feedback referencing this CR.
    DELETE FROM candidate_feedback
    WHERE candidate_round_id = p_cr_id;

    -- 5. Delete the candidate_round.
    DELETE FROM candidate_rounds
    WHERE id = p_cr_id;

    -- 6. If the round is custom, also delete it. Custom rounds exist 1:1 with
    -- their CR; orphaning them serves no purpose.
    IF v_for_candidate_id IS NOT NULL THEN
        DELETE FROM rounds
        WHERE id = v_round_id;
        v_deleted_round_id := v_round_id;
    ELSE
        v_deleted_round_id := NULL;
    END IF;

    RETURN jsonb_build_object(
        'deleted_cr_id',    p_cr_id,
        'deleted_round_id', v_deleted_round_id
    );
END;
$$;


--
-- Name: delete_shared_round(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.delete_shared_round(p_round_id uuid, p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_round                 RECORD;
    v_remaining_active      INT;
    v_pending_crs_deleted   INT;
BEGIN
    -- 1. Lookup the round + verify org via JOIN.
    SELECT r.id, r.requisition_id, r.for_candidate_id, r.removed_from_plan_at,
           r.deleted_at
    INTO v_round
    FROM rounds r
    JOIN requisitions req ON req.id = r.requisition_id
    WHERE r.id = p_round_id
      AND req.organization_id = p_org_id
      AND req.deleted_at IS NULL;

    IF NOT FOUND OR v_round.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- 2. Reject custom rounds — they have their own delete path in PR 4.
    IF v_round.for_candidate_id IS NOT NULL THEN
        RAISE EXCEPTION 'WRONG_PATH' USING ERRCODE = 'P0001';
    END IF;

    -- 3. Idempotency: already removed. Handler returns 200 with prior state.
    IF v_round.removed_from_plan_at IS NOT NULL THEN
        RAISE EXCEPTION 'ALREADY_REMOVED' USING ERRCODE = 'P0001';
    END IF;

    -- 4. Refuse to delete the last active shared round.
    SELECT COUNT(*)::int
    INTO v_remaining_active
    FROM rounds
    WHERE requisition_id = v_round.requisition_id
      AND id <> p_round_id
      AND for_candidate_id IS NULL
      AND removed_from_plan_at IS NULL
      AND deleted_at IS NULL;

    IF v_remaining_active = 0 THEN
        RAISE EXCEPTION 'LAST_ROUND' USING ERRCODE = 'P0001';
    END IF;

    -- 5. Soft-remove from plan.
    UPDATE rounds
    SET removed_from_plan_at = NOW(),
        updated_at = NOW()
    WHERE id = p_round_id;

    -- 6. Delete only pending candidate_rounds. Preserve everything else.
    WITH del AS (
        DELETE FROM candidate_rounds
        WHERE round_id = p_round_id
          AND status = 'pending'
        RETURNING 1
    )
    SELECT COUNT(*)::int INTO v_pending_crs_deleted FROM del;

    RETURN jsonb_build_object(
        'deleted_round_id', p_round_id,
        'pending_crs_deleted', v_pending_crs_deleted
    );
END;
$$;


--
-- Name: execute_readonly_query(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.execute_readonly_query(query_text text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    result JSONB;
    normalized TEXT;
    statement TEXT;
    statements TEXT[];
BEGIN
    normalized := TRIM(query_text);

    IF LENGTH(normalized) = 0 THEN
        RAISE EXCEPTION 'Empty query';
    END IF;

    IF LENGTH(normalized) > 10000 THEN
        RAISE EXCEPTION 'Query too long (max 10000 characters)';
    END IF;

    statements := string_to_array(normalized, ';');
    FOREACH statement IN ARRAY statements
    LOOP
        statement := UPPER(LTRIM(statement));
        IF LENGTH(statement) = 0 THEN
            CONTINUE;
        END IF;
        IF NOT (statement LIKE 'SELECT%' OR statement LIKE 'WITH%') THEN
            RAISE EXCEPTION 'Only SELECT/WITH statements allowed. Got: %', LEFT(statement, 30);
        END IF;
    END LOOP;

    SET LOCAL transaction_read_only = true;

    EXECUTE 'SELECT jsonb_agg(row_to_json(t)) FROM (' || normalized || ') t' INTO result;
    RETURN COALESCE(result, '[]'::jsonb);
END;
$$;


--
-- Name: get_candidate_packet(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_candidate_packet(p_candidate_id uuid, p_org_id uuid) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
  WITH cand AS (
    SELECT c.*
    FROM candidates c
    JOIN requisitions r ON r.id = c.requisition_id
    WHERE c.id = p_candidate_id
      AND r.organization_id = p_org_id
      AND c.deleted_at IS NULL
      AND r.deleted_at IS NULL
  ),
  rnds AS (
    SELECT DISTINCT r.*
    FROM rounds r
    JOIN cand c ON c.requisition_id = r.requisition_id
    LEFT JOIN candidate_rounds cr
      ON cr.round_id = r.id AND cr.candidate_id = c.id
    WHERE r.deleted_at IS NULL
      AND (
        (r.for_candidate_id IS NULL AND r.removed_from_plan_at IS NULL)
        OR r.for_candidate_id = c.id
        OR cr.id IS NOT NULL
      )
  ),
  rnd_crs AS (
    SELECT
      r.id                    AS round_id,
      r.requisition_id        AS round_requisition_id,
      r.round_number,
      r.name                  AS round_name,
      r.category,
      r.duration_minutes,
      r.description,
      r.skills,
      r.guidelines,
      r.for_candidate_id,
      r.removed_from_plan_at,
      r.assessment_template_id,
      cr.id                   AS cr_id,
      cr.candidate_id         AS cr_candidate_id,
      cr.status               AS cr_status,
      cr.scorecard_status,
      cr.rating,
      cr.summary,
      cr.question_summaries,
      cr.authenticity_signals,
      cr.scheduled_at,
      cr.scheduling_timezone,
      cr.completed_at,
      cr.interviewer_email,
      cr.meeting_url,
      COALESCE(cr.interviewer_name, p.full_name) AS interviewer_name
    FROM rnds r
    LEFT JOIN candidate_rounds cr
      ON cr.round_id = r.id AND cr.candidate_id = p_candidate_id
    LEFT JOIN profiles p
      ON p.email = cr.interviewer_email
  )
  SELECT jsonb_build_object(
    'candidate', to_jsonb((SELECT c FROM cand c)),
    'rounds', (
      SELECT jsonb_agg(jsonb_build_object(
        'round', jsonb_build_object(
          'id',                  rc.round_id,
          'requisition_id',      rc.round_requisition_id,
          'round_number',        rc.round_number,
          'name',                rc.round_name,
          'category',            rc.category,
          'duration_minutes',    rc.duration_minutes,
          'description',         rc.description,
          'skills',              rc.skills,
          'guidelines',          rc.guidelines,
          'is_custom',           (rc.for_candidate_id IS NOT NULL),
          'for_candidate_id',    rc.for_candidate_id,
          'removed_from_plan_at', rc.removed_from_plan_at
        ),
        'candidate_round', CASE WHEN rc.cr_id IS NULL THEN NULL ELSE jsonb_build_object(
          'id',                  rc.cr_id,
          'candidate_id',        rc.cr_candidate_id,
          'round_id',            rc.round_id,
          'status',              rc.cr_status,
          'scorecard_status',    rc.scorecard_status,
          'rating',              rc.rating,
          'summary',             rc.summary,
          'question_summaries',  rc.question_summaries,
          'authenticity_signals', rc.authenticity_signals,
          'scheduled_at',        rc.scheduled_at,
          'scheduling_timezone', rc.scheduling_timezone,
          'completed_at',        rc.completed_at,
          'interviewer_email',   rc.interviewer_email,
          'interviewer_name',    rc.interviewer_name,
          'meeting_url',         rc.meeting_url
        ) END,
        'feedback_questions', (
          SELECT jsonb_agg(jsonb_build_object(
            'id',              fq.id,
            'question_number', fq.question_number,
            'heading',         fq.heading,
            'description',     fq.description,
            'summary',         rc.question_summaries->>(fq.question_number::text),
            'feedback_entries', (
              SELECT jsonb_agg(jsonb_build_object(
                'id',                  cf.id,
                'feedback_question_id', cf.feedback_question_id,
                'feedback_text',       cf.feedback_text,
                'evidence',            cf.evidence,
                'evidence_status',     cf.evidence_status,
                'source',              cf.source,
                'created_at',          cf.created_at
              ) ORDER BY cf.created_at)
              FROM candidate_feedback cf
              WHERE cf.feedback_question_id = fq.id
                AND cf.candidate_round_id = rc.cr_id
            )
          ) ORDER BY fq.question_number)
          FROM feedback_questions fq
          WHERE fq.round_id = rc.round_id AND fq.deleted_at IS NULL
        ),
        'assessment', CASE WHEN rc.assessment_template_id IS NOT NULL THEN jsonb_build_object(
          'template', (SELECT to_jsonb(t) FROM assessment_templates t WHERE t.id = rc.assessment_template_id),
          'instance', (SELECT to_jsonb(i) FROM assessment_instances i
                        WHERE i.round_id = rc.round_id AND i.candidate_id = p_candidate_id
                          AND i.status <> 'expired'
                        ORDER BY i.created_at DESC LIMIT 1)
        ) ELSE NULL END,
        'recording', CASE WHEN rc.cr_id IS NULL THEN NULL ELSE (
          SELECT jsonb_build_object(
            'status',           rb.status,
            'duration_seconds', rb.recording_duration_seconds,
            'has_transcript',   EXISTS (SELECT 1 FROM transcripts WHERE candidate_round_id = rc.cr_id)
          )
          FROM recall_bots rb
          WHERE rb.candidate_round_id = rc.cr_id
          ORDER BY rb.created_at DESC LIMIT 1
        ) END
      ) ORDER BY rc.round_number)
      FROM rnd_crs rc
    )
  );
$$;


--
-- Name: get_dashboard_summary(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_dashboard_summary(p_org_id uuid) RETURNS json
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  v_now TIMESTAMPTZ := NOW();
  v_today_start TIMESTAMPTZ := DATE_TRUNC('day', v_now);
  v_today_end TIMESTAMPTZ := v_today_start + INTERVAL '1 day';
  v_week_start TIMESTAMPTZ := DATE_TRUNC('week', v_now);
  v_week_end TIMESTAMPTZ := v_week_start + INTERVAL '7 days';
  v_last_week_start TIMESTAMPTZ := v_week_start - INTERVAL '7 days';
  v_active_roles_count INT;
  v_total_candidates INT;
  v_interviews_this_week INT;
  v_interviews_last_week INT;
  v_interviews_today INT;
  v_avg_feedback_minutes NUMERIC;
  v_top_roles JSON;
  v_recent_activity JSON;
BEGIN
  SELECT COUNT(*) INTO v_active_roles_count
  FROM public.requisitions r
  WHERE r.organization_id = p_org_id
    AND r.status = 'planned'
    AND r.deleted_at IS NULL
    AND r.is_system_template = false;

  SELECT COUNT(*) INTO v_total_candidates
  FROM public.candidates c
  JOIN public.requisitions r ON c.requisition_id = r.id
  WHERE r.organization_id = p_org_id
    AND r.deleted_at IS NULL
    AND r.is_system_template = false
    AND c.deleted_at IS NULL;

  SELECT
    COALESCE(SUM(CASE WHEN cr.scheduled_at >= v_week_start AND cr.scheduled_at < v_week_end THEN 1 ELSE 0 END), 0),
    COALESCE(SUM(CASE WHEN cr.scheduled_at >= v_last_week_start AND cr.scheduled_at < v_week_start THEN 1 ELSE 0 END), 0),
    COALESCE(SUM(CASE WHEN cr.scheduled_at >= v_today_start AND cr.scheduled_at < v_today_end THEN 1 ELSE 0 END), 0)
  INTO v_interviews_this_week, v_interviews_last_week, v_interviews_today
  FROM public.candidate_rounds cr
  JOIN public.candidates c ON cr.candidate_id = c.id
  JOIN public.requisitions r ON c.requisition_id = r.id
  WHERE r.organization_id = p_org_id
    AND r.deleted_at IS NULL
    AND r.is_system_template = false
    AND c.deleted_at IS NULL
    AND cr.scheduled_at IS NOT NULL
    AND cr.source_type = 'standard';

  SELECT COALESCE(ROUND(AVG(
    EXTRACT(EPOCH FROM (cr.completed_at - COALESCE(cr.started_at, cr.scheduled_at))) / 60
  )), 0) INTO v_avg_feedback_minutes
  FROM public.candidate_rounds cr
  JOIN public.candidates c ON cr.candidate_id = c.id
  JOIN public.requisitions r ON c.requisition_id = r.id
  WHERE r.organization_id = p_org_id
    AND r.deleted_at IS NULL
    AND r.is_system_template = false
    AND c.deleted_at IS NULL
    AND cr.completed_at IS NOT NULL
    AND COALESCE(cr.started_at, cr.scheduled_at) IS NOT NULL
    AND cr.completed_at > COALESCE(cr.started_at, cr.scheduled_at)
    AND EXTRACT(EPOCH FROM (cr.completed_at - COALESCE(cr.started_at, cr.scheduled_at))) / 60 BETWEEN 0 AND 30
    AND cr.source_type = 'standard';

  SELECT COALESCE(JSON_AGG(t), '[]'::JSON) INTO v_top_roles
  FROM (
    SELECT
      r.id,
      r.role_title,
      r.role_location,
      COUNT(c.id) AS candidate_count,
      r.status
    FROM public.requisitions r
    LEFT JOIN public.candidates c ON c.requisition_id = r.id AND c.deleted_at IS NULL
    WHERE r.organization_id = p_org_id
      AND r.status = 'planned'
      AND r.deleted_at IS NULL
      AND r.is_system_template = false
    GROUP BY r.id, r.role_title, r.role_location, r.status
    ORDER BY r.created_at DESC
    LIMIT 3
  ) t;

  SELECT COALESCE(JSON_AGG(b ORDER BY b.timestamp DESC), '[]'::JSON) INTO v_recent_activity
  FROM (
    SELECT * FROM (
      (SELECT
        'feedback_submitted' AS type,
        'Feedback Submitted' AS title,
        '**' || c.name || '** — ' || COALESCE(rd.name, 'Interview') || ' for **' || COALESCE(r.role_title, '') || '**.' AS description,
        COALESCE(cr.completed_at, cr.created_at) AS timestamp,
        cr.rating
      FROM public.candidate_rounds cr
      JOIN public.candidates c ON cr.candidate_id = c.id
      JOIN public.requisitions r ON c.requisition_id = r.id
      LEFT JOIN public.rounds rd ON cr.round_id = rd.id
      WHERE r.organization_id = p_org_id
        AND r.deleted_at IS NULL
        AND r.is_system_template = false
        AND c.deleted_at IS NULL
        AND cr.status = 'completed'
        AND cr.source_type = 'standard'
      ORDER BY COALESCE(cr.completed_at, cr.created_at) DESC
      LIMIT 8)

      UNION ALL

      (SELECT
        'interview_scheduled' AS type,
        'Interview Scheduled' AS title,
        COALESCE(rd.name, 'Interview') || ' with **' || c.name || '** confirmed.' AS description,
        COALESCE(cr.scheduled_at, cr.created_at) AS timestamp,
        NULL AS rating
      FROM public.candidate_rounds cr
      JOIN public.candidates c ON cr.candidate_id = c.id
      JOIN public.requisitions r ON c.requisition_id = r.id
      LEFT JOIN public.rounds rd ON cr.round_id = rd.id
      WHERE r.organization_id = p_org_id
        AND r.deleted_at IS NULL
        AND r.is_system_template = false
        AND c.deleted_at IS NULL
        AND cr.status != 'completed'
        AND cr.scheduled_at IS NOT NULL
        AND cr.source_type = 'standard'
      ORDER BY cr.scheduled_at DESC
      LIMIT 5)

      UNION ALL

      (SELECT
        'role_created' AS type,
        'Hiring Plan Created' AS title,
        '**' || COALESCE(r.role_title, 'Role') || '** added to pipeline.' AS description,
        r.created_at AS timestamp,
        NULL AS rating
      FROM public.requisitions r
      WHERE r.organization_id = p_org_id
        AND r.deleted_at IS NULL
        AND r.is_system_template = false
        AND r.status IN ('planned', 'intake_pending')
      ORDER BY r.created_at DESC
      LIMIT 5)

      UNION ALL

      (SELECT
        'candidate_added' AS type,
        'New Candidate' AS title,
        '**' || COALESCE(c.name, 'Candidate') || '** added to **' || COALESCE(r.role_title, '') || '**.' AS description,
        c.created_at AS timestamp,
        NULL AS rating
      FROM public.candidates c
      JOIN public.requisitions r ON c.requisition_id = r.id
      WHERE r.organization_id = p_org_id
        AND r.deleted_at IS NULL
        AND r.is_system_template = false
        AND c.deleted_at IS NULL
      ORDER BY c.created_at DESC
      LIMIT 5)
    ) a
    ORDER BY a.timestamp DESC
    LIMIT 8
  ) b;

  RETURN JSON_BUILD_OBJECT(
    'active_roles_count', v_active_roles_count,
    'total_candidates', v_total_candidates,
    'interviews_this_week', v_interviews_this_week,
    'interviews_last_week', v_interviews_last_week,
    'interviews_today', v_interviews_today,
    'interviews_trend', v_interviews_this_week - v_interviews_last_week,
    'avg_feedback_minutes', COALESCE(v_avg_feedback_minutes, 0),
    'avg_feedback_hours', CASE WHEN v_avg_feedback_minutes > 0 THEN ROUND(v_avg_feedback_minutes / 60.0, 1) ELSE 0 END,
    'top_roles', v_top_roles,
    'recent_activity', v_recent_activity
  );
END;
$$;


--
-- Name: get_role_pipeline(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_role_pipeline(p_req_id uuid, p_org_id uuid) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
  WITH cands AS (
    SELECT c.id, c.name, c.email, c.status, c.final_verdict, c.created_at
    FROM candidates c
    JOIN requisitions r ON r.id = c.requisition_id
    WHERE c.requisition_id = p_req_id
      AND r.organization_id = p_org_id
      AND c.deleted_at IS NULL
      AND r.deleted_at IS NULL
    ORDER BY c.created_at DESC
  ),
  cand_rounds AS (
    SELECT cr.*, r.round_number, r.name AS round_name, r.category, r.duration_minutes,
           (r.for_candidate_id IS NOT NULL) AS is_custom,
           r.for_candidate_id,
           -- Aliased distinct from cr.interviewer_name (migration 92) so
           -- both can coexist in the CTE without collision. Outer query
           -- COALESCEs them.
           p.full_name AS interviewer_profile_name
    FROM candidate_rounds cr
    JOIN rounds r ON r.id = cr.round_id
    LEFT JOIN profiles p ON p.email = cr.interviewer_email
    WHERE cr.candidate_id IN (SELECT id FROM cands)
  )
  SELECT jsonb_build_object(
    'candidates', COALESCE(jsonb_agg(c_data), '[]'::jsonb)
  )
  FROM (
    SELECT jsonb_build_object(
      'id',              c.id,
      'name',            c.name,
      'email',           c.email,
      'status',          c.status,
      'final_verdict',   c.final_verdict,
      'created_at',      c.created_at,
      'candidate_rounds', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
          'id',                 cr.id,
          'round_id',           cr.round_id,
          'status',             cr.status,
          'scorecard_status',   cr.scorecard_status,
          'rating',             cr.rating,
          'summary',            cr.summary,
          'question_summaries', cr.question_summaries,
          'scheduled_at',       cr.scheduled_at,
          'completed_at',       cr.completed_at,
          'interviewer_email',  cr.interviewer_email,
          'interviewer_name',   COALESCE(cr.interviewer_name, cr.interviewer_profile_name),
          'meeting_url',        cr.meeting_url,
          'round', jsonb_build_object(
            'id',               cr.round_id,
            'round_number',     cr.round_number,
            'name',             cr.round_name,
            'category',         cr.category,
            'duration_minutes', cr.duration_minutes,
            'is_custom',        cr.is_custom,
            'for_candidate_id', cr.for_candidate_id
          )
        ) ORDER BY cr.round_number)
        FROM cand_rounds cr
        WHERE cr.candidate_id = c.id
      ), '[]'::jsonb)
    ) AS c_data
    FROM cands c
    ORDER BY c.created_at DESC
  ) sub;
$$;


--
-- Name: increment_blog_likes(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.increment_blog_likes(post_slug text) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    likes_count INTEGER;
BEGIN
    UPDATE blog_posts SET likes = likes + 1 WHERE slug = post_slug RETURNING likes INTO likes_count;
    RETURN likes_count;
END;
$$;


--
-- Name: intake_session_heartbeat(uuid, uuid, boolean); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.intake_session_heartbeat(p_session_id uuid, p_user_id uuid, p_paused boolean) RETURNS timestamp with time zone
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  v_now timestamptz := now();
BEGIN
  UPDATE intake_sessions
     SET last_heartbeat_at = v_now,
         paused            = p_paused
   WHERE id = p_session_id
     AND user_id = p_user_id
     AND active_modality IS NOT NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'heartbeat_no_lock'
      USING ERRCODE = 'P0001';
  END IF;
  RETURN v_now;
END;
$$;


--
-- Name: intake_sessions_append_turn(uuid, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.intake_sessions_append_turn(p_session_id uuid, p_turn jsonb) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
    UPDATE intake_sessions
    SET turns = turns || jsonb_build_array(p_turn),
        updated_at = now()
    WHERE id = p_session_id;
END;
$$;


--
-- Name: intake_sessions_merge_answers(uuid, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.intake_sessions_merge_answers(p_session_id uuid, p_patch jsonb) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
    v_current   JSONB;
    v_qid       TEXT;
    v_qpatch    JSONB;
    v_qexisting JSONB;
    v_qmerged   JSONB;
BEGIN
    SELECT COALESCE(current_answers, '{}'::jsonb) INTO v_current
    FROM intake_sessions WHERE id = p_session_id;

    FOR v_qid, v_qpatch IN SELECT * FROM jsonb_each(p_patch)
    LOOP
        v_qexisting := COALESCE(v_current -> v_qid, '{}'::jsonb);
        -- Merge existing question fields first, then overlay patch fields.
        v_qmerged   := v_qexisting || v_qpatch;
        v_current   := jsonb_set(v_current, ARRAY[v_qid], v_qmerged, true);
    END LOOP;

    UPDATE intake_sessions
    SET current_answers = v_current,
        updated_at      = now()
    WHERE id = p_session_id;
END;
$$;


--
-- Name: intake_sessions_set_stage(uuid, text, text, jsonb, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.intake_sessions_set_stage(p_session_id uuid, p_stage_name text, p_status text, p_output jsonb DEFAULT NULL::jsonb, p_error text DEFAULT NULL::text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
    v_existing JSONB;
    v_idx INT;
    v_new_entry JSONB;
BEGIN
    SELECT process_stages INTO v_existing FROM intake_sessions WHERE id = p_session_id;

    v_new_entry := jsonb_build_object(
        'name', p_stage_name,
        'status', p_status,
        'output', p_output,
        'error', p_error,
        'updated_at', now()
    );

    -- Find existing stage with same name; if present, replace; else append.
    SELECT idx - 1 INTO v_idx
    FROM jsonb_array_elements(v_existing) WITH ORDINALITY AS arr(elem, idx)
    WHERE arr.elem->>'name' = p_stage_name
    LIMIT 1;

    IF v_idx IS NOT NULL THEN
        UPDATE intake_sessions
        SET process_stages = jsonb_set(v_existing, ARRAY[v_idx::text], v_new_entry),
            updated_at = now()
        WHERE id = p_session_id;
    ELSE
        UPDATE intake_sessions
        SET process_stages = COALESCE(v_existing, '[]'::jsonb) || jsonb_build_array(v_new_entry),
            updated_at = now()
        WHERE id = p_session_id;
    END IF;
END;
$$;


--
-- Name: is_admin(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_admin() RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_is_staff BOOLEAN;
BEGIN
    -- The column and the variable must not share a name: plpgsql would resolve
    -- the bare identifier to the variable and raise "column reference is ambiguous".
    SELECT p.is_staff INTO v_is_staff
    FROM public.profiles p
    WHERE p.id = (SELECT auth.uid())
    AND p.deleted_at IS NULL;

    RETURN COALESCE(v_is_staff, FALSE);
END;
$$;


--
-- Name: release_stale_intake_modality_locks(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.release_stale_intake_modality_locks(p_stale_minutes integer DEFAULT 5) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  v_count int;
BEGIN
  WITH released AS (
    UPDATE intake_sessions
       SET active_modality = NULL,
           paused          = false
     WHERE active_modality IS NOT NULL
       AND (last_heartbeat_at IS NULL
            OR last_heartbeat_at < now() - (p_stale_minutes || ' minutes')::interval)
    RETURNING id
  )
  SELECT count(*) INTO v_count FROM released;
  RETURN v_count;
END;
$$;


--
-- Name: reorder_requisition_rounds(uuid, uuid[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.reorder_requisition_rounds(p_requisition_id uuid, p_ordered_round_ids uuid[]) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_req_exists boolean;
    v_active_ids uuid[];
    v_n          integer := array_length(p_ordered_round_ids, 1);
    v_distinct   integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM requisitions
        WHERE id = p_requisition_id AND deleted_at IS NULL
    ) INTO v_req_exists;

    IF NOT v_req_exists THEN
        RAISE EXCEPTION 'Requisition not found' USING ERRCODE = 'P0002';
    END IF;

    -- The active rounds for this requisition, as a sorted set.
    SELECT COALESCE(array_agg(id ORDER BY id), ARRAY[]::uuid[])
    INTO v_active_ids
    FROM rounds
    WHERE requisition_id = p_requisition_id
      AND deleted_at IS NULL;

    IF v_n IS NULL OR v_n = 0 OR array_length(v_active_ids, 1) IS NULL THEN
        RAISE EXCEPTION 'Requisition not found' USING ERRCODE = 'P0002';
    END IF;

    -- Reject duplicate ids in the payload (a 1..N permutation has no dupes).
    SELECT count(DISTINCT x) INTO v_distinct
    FROM unnest(p_ordered_round_ids) AS x;
    IF v_distinct <> v_n THEN
        RAISE EXCEPTION 'INVALID_PERMUTATION' USING ERRCODE = 'P0001';
    END IF;

    -- The payload id set must be EXACTLY the active round set (no missing/extra).
    IF NOT (
        v_active_ids @> p_ordered_round_ids
        AND p_ordered_round_ids @> v_active_ids
    ) THEN
        RAISE EXCEPTION 'INCOMPLETE_REORDER' USING ERRCODE = 'P0001';
    END IF;

    -- Phase 1: park every active round at a negative number to clear the
    -- (requisition_id, round_number) collision space. Single statement, in-tx.
    UPDATE rounds
    SET round_number = -round_number
    WHERE requisition_id = p_requisition_id
      AND deleted_at IS NULL;

    -- Phase 2: assign final 1..N by array position. Still inside the same tx, so
    -- the negative interim values are never visible to any other transaction.
    UPDATE rounds AS r
    SET round_number = ord.pos
    FROM (
        SELECT id, ordinality AS pos
        FROM unnest(p_ordered_round_ids) WITH ORDINALITY AS u(id, ordinality)
    ) AS ord
    WHERE r.id = ord.id
      AND r.requisition_id = p_requisition_id
      AND r.deleted_at IS NULL;

    RETURN jsonb_build_object('message', 'Rounds reordered successfully');
END;
$$;


--
-- Name: reorder_shared_rounds(uuid, jsonb, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.reorder_shared_rounds(p_req_id uuid, p_order jsonb, p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_current_count INT;
    v_proposed_count INT;
    v_distinct_count INT;
    v_min_num INT;
    v_max_num INT;
    v_mismatch_count INT;
    v_result JSONB;
BEGIN
    -- 1. Verify the requisition belongs to this org.
    IF NOT EXISTS (
        SELECT 1
        FROM requisitions
        WHERE id = p_req_id
          AND organization_id = p_org_id
          AND deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- 2. Basic shape check: must be a non-empty array.
    IF p_order IS NULL OR jsonb_typeof(p_order) <> 'array'
       OR jsonb_array_length(p_order) = 0 THEN
        RAISE EXCEPTION 'INVALID_ORDER' USING ERRCODE = 'P0001';
    END IF;

    -- 3. Verify every round_id in p_order belongs to this requisition AND is
    --    an active shared round.
    SELECT COUNT(*)::int
    INTO v_mismatch_count
    FROM jsonb_array_elements(p_order) AS o
    LEFT JOIN rounds r ON r.id = (o->>'round_id')::uuid
                       AND r.requisition_id = p_req_id
                       AND r.for_candidate_id IS NULL
                       AND r.removed_from_plan_at IS NULL
                       AND r.deleted_at IS NULL
    WHERE r.id IS NULL;

    IF v_mismatch_count > 0 THEN
        RAISE EXCEPTION 'INVALID_ROUND' USING ERRCODE = 'P0001';
    END IF;

    -- 4. Count the requisition's active shared rounds; must match payload size.
    SELECT COUNT(*)::int
    INTO v_current_count
    FROM rounds
    WHERE requisition_id = p_req_id
      AND for_candidate_id IS NULL
      AND removed_from_plan_at IS NULL
      AND deleted_at IS NULL;

    v_proposed_count := jsonb_array_length(p_order);

    IF v_current_count <> v_proposed_count THEN
        RAISE EXCEPTION 'INCOMPLETE_REORDER' USING ERRCODE = 'P0001';
    END IF;

    -- 5. Verify round_numbers form a permutation of 1..N.
    SELECT COUNT(DISTINCT (o->>'round_number')::int),
           MIN((o->>'round_number')::int),
           MAX((o->>'round_number')::int)
    INTO v_distinct_count, v_min_num, v_max_num
    FROM jsonb_array_elements(p_order) AS o;

    IF v_distinct_count <> v_proposed_count
       OR v_min_num <> 1
       OR v_max_num <> v_proposed_count THEN
        RAISE EXCEPTION 'INVALID_PERMUTATION' USING ERRCODE = 'P0001';
    END IF;

    -- 6. Offset-then-settle: park every affected round_number above the index
    --    predicate's collision range, then settle in one UPDATE per row.
    UPDATE rounds
    SET round_number = round_number + 100000,
        updated_at = NOW()
    WHERE requisition_id = p_req_id
      AND for_candidate_id IS NULL
      AND removed_from_plan_at IS NULL
      AND deleted_at IS NULL;

    UPDATE rounds
    SET round_number = (o->>'round_number')::int,
        updated_at = NOW()
    FROM jsonb_array_elements(p_order) o
    WHERE rounds.id = (o->>'round_id')::uuid
      AND rounds.requisition_id = p_req_id
      AND rounds.for_candidate_id IS NULL
      AND rounds.removed_from_plan_at IS NULL
      AND rounds.deleted_at IS NULL;

    -- 7. Return the new ordering + a max(updated_at) for the next If-Match.
    SELECT jsonb_build_object(
        'rounds', COALESCE(jsonb_agg(jsonb_build_object(
            'id', r.id,
            'round_number', r.round_number,
            'updated_at', r.updated_at
        ) ORDER BY r.round_number), '[]'::jsonb),
        'etag', MAX(r.updated_at)
    )
    INTO v_result
    FROM rounds r
    WHERE r.requisition_id = p_req_id
      AND r.for_candidate_id IS NULL
      AND r.removed_from_plan_at IS NULL
      AND r.deleted_at IS NULL;

    RETURN v_result;
END;
$$;


--
-- Name: reschedule_candidate_round(uuid, timestamp with time zone, text, text, text, boolean, uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.reschedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text DEFAULT NULL::text, p_meeting_url text DEFAULT NULL::text, p_clear_meeting_url boolean DEFAULT false, p_org_id uuid DEFAULT NULL::uuid, p_scheduling_timezone text DEFAULT NULL::text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_cr_status        TEXT;
    v_prev_meeting_url TEXT;
    v_candidate_name   TEXT;
    v_updated_cr       JSONB;
BEGIN
    IF p_scheduled_at IS NOT NULL
       AND p_scheduled_at < (NOW() - INTERVAL '1 minute') THEN
        RAISE EXCEPTION 'SCHEDULED_IN_PAST' USING ERRCODE = 'P0001';
    END IF;

    SELECT cr.status, cr.meeting_url, c.name
    INTO v_cr_status, v_prev_meeting_url, v_candidate_name
    FROM candidate_rounds cr
    JOIN candidates  c ON c.id = cr.candidate_id
    JOIN requisitions q ON q.id = c.requisition_id
    WHERE cr.id = p_cr_id
      AND q.organization_id = p_org_id
      AND q.deleted_at IS NULL
      AND c.deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    IF v_cr_status <> 'scheduled' THEN
        RAISE EXCEPTION 'NOT_RESCHEDULABLE' USING ERRCODE = 'P0001';
    END IF;

    UPDATE candidate_rounds
    SET scheduled_at        = COALESCE(p_scheduled_at, scheduled_at),
        interviewer_email   = COALESCE(p_interviewer_email, interviewer_email),
        interviewer_name    = COALESCE(p_interviewer_name,  interviewer_name),
        meeting_url         = CASE
                                WHEN p_clear_meeting_url THEN NULL
                                ELSE COALESCE(p_meeting_url, meeting_url)
                              END,
        scheduling_timezone = COALESCE(p_scheduling_timezone, scheduling_timezone),
        updated_at          = NOW()
    WHERE id = p_cr_id;

    SELECT to_jsonb(cr) INTO v_updated_cr
    FROM candidate_rounds cr WHERE cr.id = p_cr_id;

    RETURN jsonb_build_object(
        'candidate_round',  v_updated_cr,
        'prev_meeting_url', v_prev_meeting_url,
        'candidate_name',   v_candidate_name
    );
END;
$$;


--
-- Name: schedule_candidate_round(uuid, timestamp with time zone, text, text, text, integer, jsonb, uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.schedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text DEFAULT NULL::text, p_meeting_url text DEFAULT NULL::text, p_duration_minutes integer DEFAULT NULL::integer, p_assessment_instance jsonb DEFAULT NULL::jsonb, p_org_id uuid DEFAULT NULL::uuid, p_scheduling_timezone text DEFAULT NULL::text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_cr_status              TEXT;
    v_existing_scheduled_at  TIMESTAMPTZ;
    v_existing_email         TEXT;
    v_round_id               UUID;
    v_candidate_id           UUID;
    v_req_status             TEXT;
    v_template_id            UUID;
    v_candidate_name         TEXT;
    v_candidate_email        TEXT;
    v_updated_cr             JSONB;
    v_new_instance           JSONB;
BEGIN
    IF p_scheduled_at IS NOT NULL
       AND p_scheduled_at < (NOW() - INTERVAL '1 minute') THEN
        RAISE EXCEPTION 'SCHEDULED_IN_PAST' USING ERRCODE = 'P0001';
    END IF;

    SELECT cr.status, cr.scheduled_at, cr.interviewer_email,
           cr.round_id, cr.candidate_id, q.status,
           r.assessment_template_id, c.name, c.email
    INTO v_cr_status, v_existing_scheduled_at, v_existing_email,
         v_round_id, v_candidate_id, v_req_status,
         v_template_id, v_candidate_name, v_candidate_email
    FROM candidate_rounds cr
    JOIN candidates  c ON c.id = cr.candidate_id
    JOIN requisitions q ON q.id = c.requisition_id
    JOIN rounds      r ON r.id = cr.round_id
    WHERE cr.id = p_cr_id
      AND q.organization_id = p_org_id
      AND q.deleted_at IS NULL
      AND c.deleted_at IS NULL
      AND r.deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    IF v_req_status = 'closed' THEN
        RAISE EXCEPTION 'REQ_CLOSED' USING ERRCODE = 'P0001';
    END IF;

    -- Idempotent same-state return (migration 87 behaviour).
    IF v_cr_status = 'scheduled'
       AND v_existing_scheduled_at IS NOT DISTINCT FROM p_scheduled_at
       AND v_existing_email        IS NOT DISTINCT FROM p_interviewer_email
    THEN
        SELECT to_jsonb(cr) INTO v_updated_cr
        FROM candidate_rounds cr WHERE cr.id = p_cr_id;
        RETURN jsonb_build_object(
            'candidate_round',     v_updated_cr,
            'assessment_instance', NULL,
            'candidate_name',      v_candidate_name
        );
    END IF;

    IF v_cr_status NOT IN ('pending', 'cancelled') THEN
        RAISE EXCEPTION 'NOT_SCHEDULABLE' USING ERRCODE = 'P0001';
    END IF;

    UPDATE candidate_rounds
    SET status              = 'scheduled',
        scheduled_at        = p_scheduled_at,
        meeting_url         = COALESCE(p_meeting_url,         meeting_url),
        interviewer_email   = COALESCE(p_interviewer_email,   interviewer_email),
        interviewer_name    = COALESCE(p_interviewer_name,    interviewer_name),
        scheduling_timezone = COALESCE(p_scheduling_timezone, scheduling_timezone),
        updated_at          = NOW()
    WHERE id = p_cr_id;

    SELECT to_jsonb(cr) INTO v_updated_cr
    FROM candidate_rounds cr WHERE cr.id = p_cr_id;

    IF v_template_id IS NOT NULL
       AND p_assessment_instance IS NOT NULL
       AND jsonb_typeof(p_assessment_instance) = 'object'
    THEN
        UPDATE assessment_instances
        SET status     = 'expired',
            updated_at = NOW()
        WHERE round_id     = v_round_id
          AND candidate_id = v_candidate_id
          AND status NOT IN ('expired', 'evaluated', 'submitted');

        INSERT INTO assessment_instances (
            id, template_id, candidate_id, round_id,
            candidate_email, candidate_name,
            access_code, access_code_hash, access_code_expires_at,
            status, expires_at
        )
        VALUES (
            p_assessment_instance->>'id',
            (p_assessment_instance->>'template_id')::uuid,
            v_candidate_id,
            v_round_id,
            COALESCE(p_assessment_instance->>'candidate_email', v_candidate_email),
            COALESCE(p_assessment_instance->>'candidate_name',  v_candidate_name),
            p_assessment_instance->>'access_code',
            p_assessment_instance->>'access_code_hash',
            (p_assessment_instance->>'access_code_expires_at')::timestamptz,
            COALESCE(p_assessment_instance->>'status', 'pending'),
            (p_assessment_instance->>'expires_at')::timestamptz
        )
        RETURNING to_jsonb(assessment_instances.*) INTO v_new_instance;
    END IF;

    RETURN jsonb_build_object(
        'candidate_round',     v_updated_cr,
        'assessment_instance', v_new_instance,
        'candidate_name',      v_candidate_name
    );
END;
$$;


--
-- Name: screening_create_invite(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.screening_create_invite(p jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  v_req_id        uuid := (p->>'requisition_id')::uuid;
  v_round_id      uuid := (p->>'round_id')::uuid;
  v_email         text := lower(p->>'email');
  v_name          text := COALESCE(NULLIF(p->>'name',''), split_part(p->>'email','@',1));
  v_created_by    uuid := NULLIF(p->>'created_by','')::uuid;
  v_token         text := p->>'token';
  v_expires_at    timestamptz := (p->>'expires_at')::timestamptz;
  v_candidate_id  uuid;
  v_cr_id         uuid;
  v_invite_id     uuid;
BEGIN
  -- 1. Upsert candidate by (requisition_id, email).
  INSERT INTO candidates (requisition_id, name, email, status)
  VALUES (v_req_id, v_name, v_email, 'active')
  ON CONFLICT (requisition_id, email) WHERE deleted_at IS NULL
    DO UPDATE SET updated_at = now()
  RETURNING id INTO v_candidate_id;

  -- 2. Upsert the screening candidate_round.
  INSERT INTO candidate_rounds (candidate_id, round_id, status, source_type, created_by_user_id)
  VALUES (v_candidate_id, v_round_id, 'pending', 'ai_screening', v_created_by)
  ON CONFLICT (candidate_id, round_id) WHERE source_type <> 'untracked_generic'
    DO NOTHING;

  SELECT id INTO v_cr_id
  FROM candidate_rounds
  WHERE candidate_id = v_candidate_id AND round_id = v_round_id
    AND source_type <> 'untracked_generic'
  LIMIT 1;

  -- 3. Drop any prior active (unverified) invite for this round so the partial
  --    unique index uq_screening_invite_active does not reject the re-invite.
  DELETE FROM screening_invites
  WHERE candidate_round_id = v_cr_id AND session_token IS NULL;

  -- 4. Insert the invite row (token + X-day window minted in Python).
  INSERT INTO screening_invites (token, candidate_round_id, candidate_email, expires_at)
  VALUES (v_token, v_cr_id, v_email, v_expires_at)
  RETURNING id INTO v_invite_id;

  RETURN jsonb_build_object(
    'candidate_id', v_candidate_id,
    'candidate_round_id', v_cr_id,
    'invite_id', v_invite_id,
    'token', v_token
  );
END $$;


--
-- Name: screening_invite_existing(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.screening_invite_existing(p jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  v_cr_id       uuid := (p->>'candidate_round_id')::uuid;
  v_email       text := lower(p->>'email');
  v_token       text := p->>'token';
  v_expires_at  timestamptz := (p->>'expires_at')::timestamptz;
  v_invite_id   uuid;
BEGIN
  DELETE FROM screening_invites
  WHERE candidate_round_id = v_cr_id AND session_token IS NULL;

  INSERT INTO screening_invites (token, candidate_round_id, candidate_email, expires_at)
  VALUES (v_token, v_cr_id, v_email, v_expires_at)
  RETURNING id INTO v_invite_id;

  RETURN jsonb_build_object(
    'candidate_round_id', v_cr_id,
    'invite_id', v_invite_id,
    'token', v_token
  );
END $$;


--
-- Name: screening_save_config(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.screening_save_config(p jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE cfg_id uuid;
BEGIN
  INSERT INTO round_screening_configs
    (round_id, requisition_id, enabled, voice, follow_up_style,
     est_duration_minutes, validity_days, deploy_scope, created_by, updated_at)
  VALUES ((p->>'round_id')::uuid,(p->>'requisition_id')::uuid,
     COALESCE((p->>'enabled')::bool,false), COALESCE(p->>'voice','aura-luna-en'),
     COALESCE(p->>'follow_up_style','adaptive_probes'),
     NULLIF(p->>'est_duration_minutes','')::int,
     COALESCE((p->>'validity_days')::int,7),
     COALESCE(p->>'deploy_scope','manual'),
     NULLIF(p->>'created_by','')::uuid, now())
  ON CONFLICT (round_id) DO UPDATE SET
     enabled=EXCLUDED.enabled, voice=EXCLUDED.voice,
     follow_up_style=EXCLUDED.follow_up_style,
     est_duration_minutes=EXCLUDED.est_duration_minutes,
     validity_days=EXCLUDED.validity_days, deploy_scope=EXCLUDED.deploy_scope,
     updated_at=now()
  RETURNING id INTO cfg_id;

  DELETE FROM round_screening_questions WHERE round_screening_config_id = cfg_id;
  INSERT INTO round_screening_questions
    (round_screening_config_id, order_index, title, prompt, probe, signal, dimension, duration_minutes)
  SELECT cfg_id, (q->>'order_index')::int, q->>'title', q->>'prompt', q->>'probe',
         q->>'signal', q->>'dimension', NULLIF(q->>'duration_minutes','')::int
  FROM jsonb_array_elements(COALESCE(p->'questions','[]'::jsonb)) q;

  RETURN jsonb_build_object('config_id', cfg_id);
END $$;


--
-- Name: set_active_modality(uuid, text, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_active_modality(p_session_id uuid, p_modality text, p_user_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_won boolean;
BEGIN
    UPDATE intake_sessions
       SET active_modality = p_modality::intake_modality,
           updated_at      = now()
     WHERE id = p_session_id
       AND user_id = p_user_id
       AND (active_modality IS NULL OR active_modality = p_modality::intake_modality)
    RETURNING true INTO v_won;

    RETURN COALESCE(v_won, false);
END;
$$;


--
-- Name: submit_human_feedback(uuid, jsonb, text, text, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.submit_human_feedback(p_cr_id uuid, p_entries jsonb, p_rating text, p_summary text, p_org_id uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_cr_status     TEXT;
    v_round_id      UUID;
    v_entry         JSONB;
    v_q_id          UUID;
    v_q_valid       BOOLEAN;
    v_inserted      JSONB := '[]'::jsonb;
    v_row           JSONB;
    v_evidence      JSONB;
    v_updated_cr    JSONB;
BEGIN
    -- 1. Look up CR + verify org chain.
    SELECT cr.status, cr.round_id
    INTO v_cr_status, v_round_id
    FROM candidate_rounds cr
    JOIN candidates  c ON c.id = cr.candidate_id
    JOIN requisitions q ON q.id = c.requisition_id
    WHERE cr.id = p_cr_id
      AND q.organization_id = p_org_id
      AND q.deleted_at IS NULL
      AND c.deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- 2. Status gate — only scheduled / in_progress accept feedback submission.
    -- completed: must use /reprocess. cancelled: ignored. pending: not yet scheduled.
    IF v_cr_status NOT IN ('scheduled', 'in_progress') THEN
        RAISE EXCEPTION 'NOT_OPEN' USING ERRCODE = 'P0001';
    END IF;

    -- 3. Validate every question belongs to this round.
    IF p_entries IS NOT NULL AND jsonb_typeof(p_entries) = 'array' THEN
        FOR v_entry IN SELECT jsonb_array_elements(p_entries)
        LOOP
            v_q_id := (v_entry->>'feedback_question_id')::uuid;

            SELECT TRUE INTO v_q_valid
            FROM feedback_questions fq
            WHERE fq.id = v_q_id
              AND fq.round_id = v_round_id
              AND fq.deleted_at IS NULL;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'BAD_QUESTION' USING ERRCODE = 'P0001';
            END IF;
        END LOOP;
    END IF;

    -- 4. Insert/update candidate_feedback rows. We delete any prior manual rows
    -- for the same (cr, question) so resubmission produces a clean state — a
    -- human re-clicking "Submit feedback" should not pile up duplicates.
    IF p_entries IS NOT NULL AND jsonb_typeof(p_entries) = 'array' THEN
        FOR v_entry IN SELECT jsonb_array_elements(p_entries)
        LOOP
            v_q_id := (v_entry->>'feedback_question_id')::uuid;

            DELETE FROM candidate_feedback
            WHERE candidate_round_id  = p_cr_id
              AND feedback_question_id = v_q_id
              AND source = 'manual';

            -- evidence is a JSONB array of strings — accept any JSON type and
            -- coerce to '[]' if missing/not-array.
            v_evidence := v_entry->'evidence';
            IF v_evidence IS NULL OR jsonb_typeof(v_evidence) <> 'array' THEN
                v_evidence := '[]'::jsonb;
            END IF;

            INSERT INTO candidate_feedback (
                candidate_round_id, feedback_question_id,
                feedback_text, evidence, evidence_status, source
            )
            VALUES (
                p_cr_id, v_q_id,
                v_entry->>'feedback_text',
                v_evidence,
                v_entry->>'evidence_status',
                'manual'
            )
            RETURNING to_jsonb(candidate_feedback.*) INTO v_row;

            v_inserted := v_inserted || jsonb_build_array(v_row);
        END LOOP;
    END IF;

    -- 5. Transition CR to completed.
    UPDATE candidate_rounds
    SET status            = 'completed',
        rating            = p_rating,
        summary           = p_summary,
        scorecard_status  = 'complete',
        completed_at      = NOW(),
        updated_at        = NOW()
    WHERE id = p_cr_id;

    SELECT to_jsonb(cr) INTO v_updated_cr
    FROM candidate_rounds cr WHERE cr.id = p_cr_id;

    RETURN jsonb_build_object(
        'candidate_round', v_updated_cr,
        'entries',         v_inserted
    );
END;
$$;


--
-- Name: sync_profile_invitation_status(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sync_profile_invitation_status() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
    IF NEW.email_confirmed_at IS NOT NULL AND OLD.email_confirmed_at IS NULL THEN
        UPDATE public.profiles
        SET invitation_status = 'signed_up',
            updated_at = NOW()
        WHERE id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: undo_untracked_link(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.undo_untracked_link(p_org_id uuid, p_source_cr_id uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  v_import public.untracked_interview_imports;
  v_target_cr uuid;
  v_snapshot jsonb;
  v_round jsonb;
  v_restored boolean := false;
BEGIN
  -- The honored (active) attempt for this source, scoped to the org.
  SELECT * INTO v_import
  FROM public.untracked_interview_imports
  WHERE source_generic_candidate_round_id = p_source_cr_id
    AND organization_id = p_org_id
    AND superseded_at IS NULL
    AND import_status <> 'dismissed'
  ORDER BY created_at DESC
  LIMIT 1;

  IF v_import.id IS NULL THEN
    RAISE EXCEPTION 'no active untracked link to undo' USING ERRCODE = 'P0002';
  END IF;

  v_target_cr := v_import.target_candidate_round_id;
  v_snapshot := v_import.prior_round_snapshot;

  -- Copied interview transcript + any feedback token minted against the target
  -- round are always removed (the round is being disassociated).
  DELETE FROM public.transcripts WHERE candidate_round_id = v_target_cr;
  DELETE FROM public.feedback_access_tokens WHERE candidate_round_id = v_target_cr;

  IF v_snapshot IS NOT NULL AND (v_snapshot ? 'round') THEN
    -- Merge overwrote an existing round: restore it from the snapshot.
    v_round := v_snapshot->'round';
    UPDATE public.candidate_rounds SET
      status = COALESCE(v_round->>'status', 'pending'),
      source_type = COALESCE(v_round->>'source_type', 'standard'),
      origin_candidate_round_id = (v_round->>'origin_candidate_round_id')::uuid,
      origin_detection_id = (v_round->>'origin_detection_id')::uuid,
      scheduled_at = (v_round->>'scheduled_at')::timestamptz,
      completed_at = (v_round->>'completed_at')::timestamptz,
      interviewer_email = v_round->>'interviewer_email',
      interviewer_name = v_round->>'interviewer_name',
      meeting_url = v_round->>'meeting_url',
      recording_url = v_round->>'recording_url',
      transcript_url = v_round->>'transcript_url',
      rating = v_round->>'rating',
      summary = v_round->>'summary',
      question_summaries = COALESCE(v_round->'question_summaries', '{}'::jsonb),
      scorecard_status = COALESCE(v_round->>'scorecard_status', 'pending'),
      processing_status = COALESCE(v_round->>'processing_status', 'none'),
      processing_started_at = NULL,
      processing_completed_at = NULL,
      processing_error = NULL,
      updated_at = now()
    WHERE id = v_target_cr;

    -- Drop feedback written after the merge, restore the snapshotted rows.
    DELETE FROM public.candidate_feedback WHERE candidate_round_id = v_target_cr;
    INSERT INTO public.candidate_feedback
      (id, candidate_round_id, feedback_question_id, feedback_text,
       evidence, evidence_status, source, created_at)
    SELECT
      COALESCE((f->>'id')::uuid, gen_random_uuid()),
      v_target_cr,
      (f->>'feedback_question_id')::uuid,
      f->>'feedback_text',
      COALESCE(f->'evidence', '[]'::jsonb),
      f->>'evidence_status',
      COALESCE(f->>'source', 'bot'),
      COALESCE((f->>'created_at')::timestamptz, now())
    FROM jsonb_array_elements(COALESCE(v_snapshot->'feedback', '[]'::jsonb)) AS f;

    v_restored := true;
  ELSE
    -- The round was created for this association (new candidate): cancel it
    -- (never delete — keeps any feedback restorable, mirrors the link path).
    UPDATE public.candidate_rounds
      SET status = 'cancelled', updated_at = now()
    WHERE id = v_target_cr;
  END IF;

  -- Supersede the import so list_untracked sees no active attempt -> "available".
  UPDATE public.untracked_interview_imports
    SET superseded_at = now(), updated_at = now()
  WHERE id = v_import.id;

  RETURN jsonb_build_object(
    'untracked_id', p_source_cr_id,
    'target_candidate_round_id', v_target_cr,
    'restored_prior_scorecard', v_restored
  );
END;
$$;


--
-- Name: update_assessment_evaluations_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_assessment_evaluations_updated_at() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_assessment_instances_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_assessment_instances_updated_at() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_assessment_templates_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_assessment_templates_updated_at() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public'
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: use_credit_atomic(uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.use_credit_atomic(p_org_id uuid, p_credit_type text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_row RECORD;
    v_remaining int;
BEGIN
    SELECT id, total, used INTO v_row
    FROM usage_credits
    WHERE organization_id = p_org_id AND credit_type = p_credit_type
    FOR UPDATE;

    IF NOT FOUND THEN
        INSERT INTO usage_credits (organization_id, credit_type, total, used, period_start)
        VALUES (p_org_id, p_credit_type, 1, 1, now());
        RETURN 'free_default';
    END IF;

    IF v_row.total = -1 THEN
        UPDATE usage_credits SET used = used + 1 WHERE id = v_row.id;
        RETURN 'monthly';
    END IF;

    v_remaining := v_row.total - v_row.used;
    IF v_remaining > 0 THEN
        UPDATE usage_credits SET used = used + 1 WHERE id = v_row.id;
        RETURN 'monthly';
    END IF;

    SELECT id, remaining INTO v_row
    FROM topup_credits
    WHERE organization_id = p_org_id AND credit_type = p_credit_type AND remaining > 0
    ORDER BY purchased_at
    LIMIT 1
    FOR UPDATE;

    IF FOUND THEN
        UPDATE topup_credits SET remaining = remaining - 1 WHERE id = v_row.id;
        RETURN 'topup';
    END IF;

    RETURN 'exhausted';
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slack_user_id text NOT NULL,
    slack_channel_id text NOT NULL,
    organization_id uuid NOT NULL,
    messages jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    active_context jsonb DEFAULT '{}'::jsonb,
    memory_summaries jsonb DEFAULT '{}'::jsonb,
    warm_context jsonb DEFAULT '{}'::jsonb
);


--
-- Name: agent_memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_memories (
    id text NOT NULL,
    user_id text NOT NULL,
    content text NOT NULL,
    embedding public.vector(1536),
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: agent_pending_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_pending_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id text NOT NULL,
    channel_id text NOT NULL,
    channel_type text DEFAULT 'slack'::text NOT NULL,
    organization_id uuid NOT NULL,
    task_type text NOT NULL,
    watch_table text NOT NULL,
    watch_id uuid NOT NULL,
    watch_field text NOT NULL,
    watch_value text NOT NULL,
    skill text,
    next_step integer,
    context jsonb DEFAULT '{}'::jsonb,
    status text DEFAULT 'waiting'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: assessment_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.assessment_evaluations (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    assessment_instance_id text NOT NULL,
    candidate_round_id uuid NOT NULL,
    category_name text NOT NULL,
    category_index integer NOT NULL,
    score integer,
    notes text,
    evidence jsonb DEFAULT '[]'::jsonb,
    evaluator_id uuid,
    source character varying DEFAULT 'manual'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT assessment_evaluations_score_check CHECK (((score >= 1) AND (score <= 5))),
    CONSTRAINT assessment_evaluations_source_check CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'ai'::character varying, 'system'::character varying])::text[])))
);


--
-- Name: assessment_instances; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.assessment_instances (
    id text NOT NULL,
    template_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    round_id uuid,
    candidate_email text NOT NULL,
    candidate_name text,
    access_code text NOT NULL,
    access_code_hash text NOT NULL,
    access_code_expires_at timestamp with time zone NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    email_sent_at timestamp with time zone,
    authenticated_at timestamp with time zone,
    started_at timestamp with time zone,
    submitted_at timestamp with time zone,
    work_data jsonb DEFAULT '{}'::jsonb,
    submission_data jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    evaluation_result jsonb,
    evaluation_notes text,
    evaluated_at timestamp with time zone,
    evaluator_id uuid,
    CONSTRAINT assessment_instances_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'email_sent'::text, 'authenticated'::text, 'in_progress'::text, 'submitted'::text, 'expired'::text, 'evaluated'::text])))
);


--
-- Name: COLUMN assessment_instances.evaluation_result; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.assessment_instances.evaluation_result IS 'Stores the complete evaluation result as JSONB with structure: {
  overall_score: number,
  overall_percentage: number,
  total_possible_points: number,
  passing_threshold: number,
  passed: boolean,
  category_scores: [{
    category_name: string,
    category_index: number,
    score: number,
    max_score: number,
    percentage: number,
    weight_percentage: number,
    criterion_scores: [{
      criterion_id: string,
      criterion_name: string,
      score: number,
      max_points: number,
      level: "excellent" | "good" | "adequate" | "poor",
      notes: string
    }]
  }]
}';


--
-- Name: assessment_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.assessment_templates (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    title text NOT NULL,
    description text,
    role_seniority text,
    tools_enabled text[] DEFAULT ARRAY['whiteboard'::text],
    time_limit_minutes integer DEFAULT 45,
    task_definition jsonb DEFAULT '{}'::jsonb NOT NULL,
    evaluation_rubric jsonb DEFAULT '{}'::jsonb NOT NULL,
    version text DEFAULT '1.0'::text,
    parent_template_id uuid,
    status text DEFAULT 'draft'::text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT assessment_templates_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'published'::text, 'archived'::text])))
);


--
-- Name: ats_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ats_connections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    provider text NOT NULL,
    category text DEFAULT 'ATS'::text NOT NULL,
    knit_integration_id text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    connected_by uuid,
    connected_at timestamp with time zone DEFAULT now() NOT NULL,
    deactivated_at timestamp with time zone,
    last_verified_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ats_connections_status_check CHECK ((status = ANY (ARRAY['active'::text, 'inactive'::text, 'error'::text])))
);


--
-- Name: ats_entity_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ats_entity_links (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    connection_id uuid NOT NULL,
    provider text NOT NULL,
    native_type text NOT NULL,
    native_id uuid NOT NULL,
    ats_type text NOT NULL,
    ats_id text NOT NULL,
    ats_candidate_id text,
    ats_status text,
    ats_stage_id text,
    ats_stage_name text,
    ats_dirty boolean DEFAULT false NOT NULL,
    ats_dirty_payload jsonb,
    ats_deleted boolean DEFAULT false NOT NULL,
    last_synced_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ats_entity_links_ats_type_check CHECK ((ats_type = ANY (ARRAY['job'::text, 'application'::text]))),
    CONSTRAINT ats_entity_links_native_type_check CHECK ((native_type = ANY (ARRAY['requisition'::text, 'candidate'::text])))
);


--
-- Name: ats_interviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ats_interviews (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    connection_id uuid NOT NULL,
    provider text NOT NULL,
    ats_application_id text,
    ats_interview_event_id text NOT NULL,
    ats_schedule_id text,
    ats_interview_id text,
    ats_stage_id text,
    stage_name text,
    interview_title text,
    scheduled_start timestamp with time zone,
    scheduled_end timestamp with time zone,
    status text,
    interviewers jsonb DEFAULT '[]'::jsonb NOT NULL,
    meeting_url text,
    feedback_link text,
    has_submitted_feedback boolean DEFAULT false NOT NULL,
    notetaker_transcript_id text,
    transcript_status text DEFAULT 'none'::text NOT NULL,
    transcript_source text,
    candidate_round_id uuid,
    recall_bot_scheduled boolean DEFAULT false NOT NULL,
    raw jsonb,
    last_synced_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ats_stage_round_map; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ats_stage_round_map (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    requisition_id uuid NOT NULL,
    ats_stage_id text NOT NULL,
    ats_stage_name text,
    round_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ats_webhook_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ats_webhook_events (
    event_id text NOT NULL,
    event_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone,
    integration_id text,
    processing_error text,
    retry_count integer DEFAULT 0 NOT NULL
);


--
-- Name: blog_posts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blog_posts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug text NOT NULL,
    title text NOT NULL,
    excerpt text NOT NULL,
    content text NOT NULL,
    thumbnail_url text,
    author_name text DEFAULT 'OpenRecruiting Team'::text NOT NULL,
    author_avatar text,
    author_id uuid,
    tags text[] DEFAULT '{}'::text[],
    likes integer DEFAULT 0,
    status text DEFAULT 'draft'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    hero_image_url text,
    CONSTRAINT blog_posts_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'published'::text])))
);


--
-- Name: calendar_event_detections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.calendar_event_detections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    profile_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    recall_calendar_id text NOT NULL,
    recall_event_id text NOT NULL,
    platform_event_id text,
    event_title text,
    event_start timestamp with time zone NOT NULL,
    event_end timestamp with time zone NOT NULL,
    meeting_url text,
    meeting_platform text,
    external_attendees jsonb DEFAULT '[]'::jsonb,
    internal_attendees jsonb DEFAULT '[]'::jsonb,
    detection_status text DEFAULT 'detected'::text NOT NULL,
    detection_confidence double precision,
    detection_signals jsonb DEFAULT '{}'::jsonb,
    matched_requisition_id uuid,
    matched_candidate_id uuid,
    matched_candidate_round_id uuid,
    candidate_was_created boolean DEFAULT false,
    slack_channel_id text,
    slack_message_ts text,
    reminder_count integer DEFAULT 0,
    last_reminded_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    notified_at timestamp with time zone,
    responded_at timestamp with time zone,
    undo_expires_at timestamp with time zone,
    platform_id text,
    ical_uid text,
    last_notified_signature text,
    last_change_notified_at timestamp with time zone,
    last_reminded_reason text,
    reminder_policy_version text,
    identity_source text,
    identity_base_key text,
    identity_instance_key text,
    identity_key text
);


--
-- Name: COLUMN calendar_event_detections.platform_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.platform_id IS 'Recall-normalized provider event id (Google/Outlook stable id).';


--
-- Name: COLUMN calendar_event_detections.ical_uid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.ical_uid IS 'RFC-5545 iCal UID used for reconnect-safe dedupe and cross-provider stability.';


--
-- Name: COLUMN calendar_event_detections.last_notified_signature; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.last_notified_signature IS 'Last material-change signature used to dedupe Slack notifications for this event.';


--
-- Name: COLUMN calendar_event_detections.last_change_notified_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.last_change_notified_at IS 'Timestamp of the most recent additive change notification (for coalescing).';


--
-- Name: COLUMN calendar_event_detections.last_reminded_reason; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.last_reminded_reason IS 'Reason label for the last reminder decision (e.g., t_minus_2h, at_detection_inside_window).';


--
-- Name: COLUMN calendar_event_detections.reminder_policy_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.reminder_policy_version IS 'Policy tag used to identify which reminder strategy generated reminder metadata.';


--
-- Name: COLUMN calendar_event_detections.identity_source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.identity_source IS 'Canonical identity source: one of ical_uid/platform_id/recall_event_id.';


--
-- Name: COLUMN calendar_event_detections.identity_base_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.identity_base_key IS 'Stable key for the selected identity source.';


--
-- Name: COLUMN calendar_event_detections.identity_instance_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.identity_instance_key IS 'Recurring instance discriminator (series_id@original_start) when available.';


--
-- Name: COLUMN calendar_event_detections.identity_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.calendar_event_detections.identity_key IS 'Canonical compound identity key: {source}:{base}[#{instance}] used for idempotent dedupe.';


--
-- Name: calendar_intelligence_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.calendar_intelligence_state (
    key text NOT NULL,
    value text,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: candidate_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.candidate_feedback (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    candidate_round_id uuid NOT NULL,
    feedback_question_id uuid NOT NULL,
    feedback_text text,
    evidence jsonb DEFAULT '[]'::jsonb,
    evidence_status character varying(50),
    source character varying(50) DEFAULT 'manual'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT candidate_feedback_evidence_status_check CHECK (((evidence_status IS NULL) OR ((evidence_status)::text = ANY ((ARRAY['supported'::character varying, 'verified'::character varying, 'contradicted'::character varying, 'partial'::character varying, 'none'::character varying])::text[])))),
    CONSTRAINT candidate_feedback_source_check CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'bot'::character varying])::text[])))
);


--
-- Name: TABLE candidate_feedback; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.candidate_feedback IS 'Stores feedback entries for each question. Rating is tracked at the round level in candidate_rounds.rating';


--
-- Name: COLUMN candidate_feedback.evidence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_feedback.evidence IS 'Array of evidence strings supporting feedback';


--
-- Name: COLUMN candidate_feedback.evidence_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_feedback.evidence_status IS 'Evidence status: verified, contradicted, partial, none';


--
-- Name: candidate_rounds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.candidate_rounds (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    candidate_id uuid NOT NULL,
    round_id uuid NOT NULL,
    status character varying(50) DEFAULT 'pending'::character varying NOT NULL,
    scheduled_at timestamp with time zone,
    completed_at timestamp with time zone,
    bot_session_id character varying(255),
    transcript_url text,
    recording_url text,
    outcome character varying(50),
    outcome_notes text,
    summary text,
    rating character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    meeting_url text,
    processing_status text DEFAULT 'none'::text,
    processing_started_at timestamp with time zone,
    processing_completed_at timestamp with time zone,
    processing_error text,
    started_at timestamp with time zone,
    recall_bot_id text,
    question_summaries jsonb,
    competency_snapshots text,
    interviewer_email character varying(255),
    interviewer_email_verified boolean DEFAULT false,
    created_by_user_id uuid,
    scorecard_status character varying(50) DEFAULT 'pending'::character varying,
    feedback_approved_at timestamp with time zone,
    feedback_approved_by_email character varying(255),
    scorecard_transcript text,
    scheduling_timezone text,
    scheduling_locked_at timestamp with time zone,
    prep_reminder_sent boolean DEFAULT false,
    source_type text DEFAULT 'standard'::text NOT NULL,
    origin_detection_id uuid,
    origin_candidate_round_id uuid,
    feedback_voice_session_token uuid,
    feedback_voice_session_status character varying(20),
    feedback_voice_session_started_at timestamp with time zone,
    feedback_voice_session_error text,
    overall_feedback jsonb DEFAULT '[]'::jsonb,
    interviewer_name text,
    screening_voice_session_token uuid,
    screening_voice_session_status character varying(20),
    screening_voice_session_started_at timestamp with time zone,
    screening_voice_session_error text,
    authenticity_signals jsonb,
    CONSTRAINT candidate_rounds_outcome_check CHECK (((outcome IS NULL) OR ((outcome)::text = ANY ((ARRAY['advance'::character varying, 'reject'::character varying, 'hold'::character varying])::text[])))),
    CONSTRAINT candidate_rounds_processing_status_check CHECK ((processing_status = ANY (ARRAY['none'::text, 'processing'::text, 'completed'::text, 'failed'::text]))),
    CONSTRAINT candidate_rounds_rating_check CHECK (((rating IS NULL) OR ((rating)::text = ANY ((ARRAY['strong_yes'::character varying, 'yes'::character varying, 'maybe'::character varying, 'no'::character varying, 'strong_no'::character varying])::text[])))),
    CONSTRAINT candidate_rounds_scorecard_status_check CHECK (((scorecard_status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying, 'complete'::character varying])::text[]))),
    CONSTRAINT candidate_rounds_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'scheduled'::character varying, 'in_progress'::character varying, 'completed'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT chk_candidate_rounds_source_type CHECK ((source_type = ANY (ARRAY['standard'::text, 'untracked_generic'::text, 'untracked_copy'::text, 'ai_screening'::text, 'ats_scheduled'::text])))
);


--
-- Name: COLUMN candidate_rounds.summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.summary IS 'Summary of the round evaluation';


--
-- Name: COLUMN candidate_rounds.rating; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.rating IS 'Overall round rating: strong_yes, yes, maybe, no, strong_no';


--
-- Name: COLUMN candidate_rounds.meeting_url; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.meeting_url IS 'Video conferencing link for the scheduled interview (Zoom, Google Meet, etc.)';


--
-- Name: COLUMN candidate_rounds.question_summaries; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.question_summaries IS 'AI-generated summaries per feedback question, keyed by question_number';


--
-- Name: COLUMN candidate_rounds.competency_snapshots; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.competency_snapshots IS 'AI-generated competency snapshots from feedback analysis';


--
-- Name: COLUMN candidate_rounds.interviewer_email; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.interviewer_email IS 'Optional email address of the interviewer for feedback reminders';


--
-- Name: COLUMN candidate_rounds.interviewer_email_verified; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.interviewer_email_verified IS 'Whether the interviewer email has been verified';


--
-- Name: COLUMN candidate_rounds.created_by_user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.created_by_user_id IS 'User who scheduled this interview round';


--
-- Name: COLUMN candidate_rounds.scorecard_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.scorecard_status IS 'Status of feedback/scorecard processing: pending, processing, complete';


--
-- Name: COLUMN candidate_rounds.prep_reminder_sent; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.prep_reminder_sent IS 'Whether the automated 5-min-before prep reminder email has been sent to the interviewer';


--
-- Name: COLUMN candidate_rounds.source_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.source_type IS 'standard = normal pipeline, untracked_generic = auto-captured without role mapping, untracked_copy = imported from generic capture into a real requisition';


--
-- Name: COLUMN candidate_rounds.origin_detection_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.origin_detection_id IS 'calendar_event_detections.id that originated this candidate_round (generic capture or copy import).';


--
-- Name: COLUMN candidate_rounds.origin_candidate_round_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.candidate_rounds.origin_candidate_round_id IS 'For untracked_copy rows, source generic candidate_round id.';


--
-- Name: candidates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.candidates (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    requisition_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    email character varying(255) NOT NULL,
    phone character varying(50),
    resume_url text,
    status character varying(50) DEFAULT 'active'::character varying NOT NULL,
    final_verdict character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    source text DEFAULT 'native'::text NOT NULL,
    ats_synced_at timestamp with time zone,
    profile jsonb,
    enrichment_status text,
    enrichment_attempts integer DEFAULT 0 NOT NULL,
    enrichment_error text,
    enriched_at timestamp with time zone,
    CONSTRAINT candidates_enrichment_status_chk CHECK (((enrichment_status IS NULL) OR (enrichment_status = ANY (ARRAY['pending'::text, 'processing'::text, 'done'::text, 'failed'::text, 'skipped'::text])))),
    CONSTRAINT candidates_final_verdict_check CHECK (((final_verdict IS NULL) OR ((final_verdict)::text = ANY ((ARRAY['strong_hire'::character varying, 'hire'::character varying, 'no_hire'::character varying, 'strong_no_hire'::character varying])::text[])))),
    CONSTRAINT candidates_source_check CHECK ((source = ANY (ARRAY['native'::text, 'ats_sync'::text]))),
    CONSTRAINT candidates_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'hired'::character varying, 'rejected'::character varying, 'withdrawn'::character varying])::text[])))
);


--
-- Name: cortex_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cortex_events (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    event_type text NOT NULL,
    source_id uuid NOT NULL,
    org_id uuid NOT NULL,
    source_table text NOT NULL,
    payload_keys jsonb DEFAULT '{}'::jsonb NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_touch_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone,
    publish_count integer DEFAULT 0 NOT NULL,
    last_error text
);


--
-- Name: TABLE cortex_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cortex_events IS 'Cortex notification table. Per-source-table triggers UPSERT here on (event_type, source_id). Drained nightly to SQS by the cortex-backend brain_sync_cron.';


--
-- Name: cortex_force_publish_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cortex_force_publish_jobs (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    org_id uuid NOT NULL,
    status text NOT NULL,
    scanned integer DEFAULT 0 NOT NULL,
    published integer DEFAULT 0 NOT NULL,
    batches integer DEFAULT 0 NOT NULL,
    errors jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT cortex_force_publish_jobs_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'partial'::text])))
);


--
-- Name: TABLE cortex_force_publish_jobs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cortex_force_publish_jobs IS 'Tracks async force-publish runs kicked off by POST /ingest/org/force-publish. Cortex backend updates rows as the run progresses; clients poll GET /ingest/org/force-publish/{id} for status.';


--
-- Name: cortex_ingestion_record; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cortex_ingestion_record (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    event_type text NOT NULL,
    source_id uuid NOT NULL,
    org_id uuid NOT NULL,
    last_touch_at timestamp with time zone NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    nodes_count integer DEFAULT 0 NOT NULL,
    edges_count integer DEFAULT 0 NOT NULL,
    publish_count integer DEFAULT 1 NOT NULL
);


--
-- Name: TABLE cortex_ingestion_record; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cortex_ingestion_record IS 'Per-event ingestion ledger maintained by the cortex-backend service. Stores last_touch_at of latest successfully-ingested cortex_events row for (event_type, source_id). Drives re-edit detection.';


--
-- Name: cortex_org_ingest_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cortex_org_ingest_jobs (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    org_id uuid NOT NULL,
    status text NOT NULL,
    current_event_type text,
    events_total integer DEFAULT 0 NOT NULL,
    events_processed integer DEFAULT 0 NOT NULL,
    events_skipped integer DEFAULT 0 NOT NULL,
    nodes_created integer DEFAULT 0 NOT NULL,
    edges_created integer DEFAULT 0 NOT NULL,
    errors_count integer DEFAULT 0 NOT NULL,
    event_counts jsonb DEFAULT '{}'::jsonb NOT NULL,
    errors jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT cortex_org_ingest_jobs_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'partial'::text])))
);


--
-- Name: TABLE cortex_org_ingest_jobs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cortex_org_ingest_jobs IS 'Tracks async POST /ingest/org/async runs. Updated as the run progresses; clients poll GET /ingest/org/async/{id}.';


--
-- Name: debrief_conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.debrief_conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    packet_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    turns jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: debrief_insights; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.debrief_insights (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    packet_id uuid NOT NULL,
    requisition_id uuid,
    organization_id uuid NOT NULL,
    candidate_id uuid,
    kind character varying(40) NOT NULL,
    content text NOT NULL,
    content_hash text NOT NULL,
    triplet jsonb,
    sync_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT debrief_insights_sync_status_check CHECK (((sync_status)::text = ANY ((ARRAY['synced'::character varying, 'pending'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: debrief_packets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.debrief_packets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    requisition_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    created_by uuid,
    candidate_ids uuid[] NOT NULL,
    status character varying(20) DEFAULT 'generating'::character varying NOT NULL,
    packet jsonb,
    generation_error text,
    generated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT debrief_packets_status_check CHECK (((status)::text = ANY ((ARRAY['generating'::character varying, 'draft'::character varying, 'fresh'::character varying, 'superseded'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: feedback_access_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_access_tokens (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    token character varying(64) NOT NULL,
    candidate_round_id uuid NOT NULL,
    interviewer_email character varying(255) NOT NULL,
    is_registered_user boolean,
    otp_code character varying(6),
    otp_expires_at timestamp with time zone,
    otp_attempts integer DEFAULT 0,
    otp_locked_until timestamp with time zone,
    otp_last_sent_at timestamp with time zone,
    session_token text,
    session_expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_accessed_at timestamp with time zone,
    otp_success_count integer DEFAULT 0
);


--
-- Name: TABLE feedback_access_tokens; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.feedback_access_tokens IS 'Stores OTP state and session tokens for external interviewer feedback access';


--
-- Name: COLUMN feedback_access_tokens.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.id IS 'Primary key';


--
-- Name: COLUMN feedback_access_tokens.token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.token IS 'URL-safe token used in feedback link';


--
-- Name: COLUMN feedback_access_tokens.candidate_round_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.candidate_round_id IS 'Reference to the interview round for feedback';


--
-- Name: COLUMN feedback_access_tokens.interviewer_email; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.interviewer_email IS 'Email address of the interviewer';


--
-- Name: COLUMN feedback_access_tokens.is_registered_user; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.is_registered_user IS 'Cached lookup: true if email matches a signed-up platform user';


--
-- Name: COLUMN feedback_access_tokens.otp_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.otp_code IS 'Current 6-digit OTP code (NULL when no active OTP)';


--
-- Name: COLUMN feedback_access_tokens.otp_expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.otp_expires_at IS 'When the current OTP expires (10 minutes from creation)';


--
-- Name: COLUMN feedback_access_tokens.otp_attempts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.otp_attempts IS 'Number of failed OTP verification attempts';


--
-- Name: COLUMN feedback_access_tokens.otp_locked_until; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.otp_locked_until IS 'Account locked until this time after 3 failed attempts';


--
-- Name: COLUMN feedback_access_tokens.otp_last_sent_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.otp_last_sent_at IS 'When the last OTP was sent (for 60s rate limiting)';


--
-- Name: COLUMN feedback_access_tokens.session_token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.session_token IS 'JWT session token after successful OTP verification';


--
-- Name: COLUMN feedback_access_tokens.session_expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.session_expires_at IS 'When the session token expires (24 hours from creation)';


--
-- Name: COLUMN feedback_access_tokens.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.created_at IS 'When the feedback token was created';


--
-- Name: COLUMN feedback_access_tokens.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.updated_at IS 'Last modification timestamp';


--
-- Name: COLUMN feedback_access_tokens.last_accessed_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.feedback_access_tokens.last_accessed_at IS 'Last access timestamp for audit';


--
-- Name: feedback_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_questions (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    round_id uuid NOT NULL,
    question_number integer NOT NULL,
    heading character varying(500) NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: TABLE feedback_questions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.feedback_questions IS 'Stores evaluation criteria/questions for each interview round. Rating is tracked at the round level in candidate_rounds.rating';


--
-- Name: intake_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intake_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    requisition_id uuid NOT NULL,
    user_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    status public.intake_session_status DEFAULT 'created'::public.intake_session_status NOT NULL,
    active_modality public.intake_modality,
    entry_point text,
    form_data jsonb NOT NULL,
    questions_version text NOT NULL,
    questions_snapshot jsonb NOT NULL,
    prefilled_answers jsonb,
    current_answers jsonb,
    turns jsonb DEFAULT '[]'::jsonb NOT NULL,
    process_stages jsonb DEFAULT '[]'::jsonb NOT NULL,
    process_run_id uuid,
    process_status text DEFAULT 'idle'::text NOT NULL,
    process_error text,
    interview_plan jsonb,
    modalities_used text[] DEFAULT '{}'::text[] NOT NULL,
    duration_min numeric,
    submitted_at timestamp with time zone,
    published_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_heartbeat_at timestamp with time zone,
    paused boolean DEFAULT false NOT NULL
);


--
-- Name: mcp_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mcp_audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    org_id uuid,
    client_id text,
    tool_name text NOT NULL,
    query text,
    query_param_keys jsonb,
    status text NOT NULL,
    row_count integer,
    truncated boolean,
    error_message text,
    latency_ms integer NOT NULL,
    user_agent text,
    ip_address text,
    request_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE mcp_audit_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.mcp_audit_log IS 'Every Cortex MCP tool invocation. Service-role only; RLS denies all non-service access. Writes are fire-and-forget from cortex-mcp.';


--
-- Name: oauth_authorization_codes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_authorization_codes (
    code text NOT NULL,
    client_id text NOT NULL,
    user_id uuid NOT NULL,
    organization_id uuid,
    redirect_uri text NOT NULL,
    scope text NOT NULL,
    audience text NOT NULL,
    code_challenge text NOT NULL,
    code_challenge_method text DEFAULT 'S256'::text NOT NULL,
    consumed boolean DEFAULT false NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE oauth_authorization_codes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.oauth_authorization_codes IS 'Short-lived (5 min) authorization codes for the OAuth 2.1 authorization-code flow with PKCE. Service-role only; RLS denies all non-service access.';


--
-- Name: oauth_clients; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_clients (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    client_id text NOT NULL,
    client_name text,
    client_uri text,
    logo_uri text,
    redirect_uris jsonb DEFAULT '[]'::jsonb NOT NULL,
    grant_types jsonb DEFAULT '["authorization_code", "refresh_token"]'::jsonb NOT NULL,
    response_types jsonb DEFAULT '["code"]'::jsonb NOT NULL,
    token_endpoint_auth_method text DEFAULT 'none'::text NOT NULL,
    scope text DEFAULT 'cortex:read'::text NOT NULL,
    software_id text,
    software_version text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE oauth_clients; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.oauth_clients IS 'OAuth 2.1 clients registered via Dynamic Client Registration (RFC 7591). Each MCP-compatible client (Claude.ai, Claude Code, etc.) registers once per user to get its own client_id. Service-role only; RLS denies all non-service access.';


--
-- Name: oauth_refresh_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_refresh_tokens (
    token_hash text NOT NULL,
    client_id text NOT NULL,
    user_id uuid NOT NULL,
    organization_id uuid,
    scope text NOT NULL,
    audience text NOT NULL,
    revoked boolean DEFAULT false NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE oauth_refresh_tokens; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.oauth_refresh_tokens IS 'Long-lived refresh tokens. We store the SHA-256 hash of the token, not the token itself. Service-role only; RLS denies all non-service access.';


--
-- Name: org_generic_template_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.org_generic_template_bindings (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    organization_id uuid NOT NULL,
    template_key text NOT NULL,
    materialized_requisition_id uuid NOT NULL,
    materialized_round_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE org_generic_template_bindings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.org_generic_template_bindings IS 'Maps an organization to a materialized hidden requisition+round for a system template key.';


--
-- Name: organization_invites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organization_invites (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    email character varying(255) NOT NULL,
    invited_by uuid NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone DEFAULT (now() + '30 days'::interval),
    accepted_at timestamp with time zone,
    CONSTRAINT organization_invites_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'accepted'::character varying, 'cancelled'::character varying, 'expired'::character varying])::text[])))
);


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    name character varying(255) NOT NULL,
    domain character varying(255),
    description text,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    org_type character varying(20) DEFAULT 'team'::character varying,
    auto_join_enabled boolean DEFAULT true,
    blocked_domains text[] DEFAULT '{}'::text[],
    slack_features jsonb DEFAULT '{"assistant_read": false, "assistant_write": false, "calendar_notifications": true}'::jsonb,
    auto_join_untracked boolean DEFAULT false,
    intake_v2_features jsonb DEFAULT '{"intake_v2_enabled": false}'::jsonb,
    CONSTRAINT organizations_org_type_check CHECK (((org_type)::text = ANY ((ARRAY['personal'::character varying, 'team'::character varying, 'enterprise'::character varying])::text[])))
);


--
-- Name: COLUMN organizations.auto_join_untracked; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.organizations.auto_join_untracked IS 'When true, interviews with no role/round mapping are auto-captured into hidden generic requisition.';


--
-- Name: COLUMN organizations.intake_v2_features; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.organizations.intake_v2_features IS 'Per-org feature flags for v2 intake. Keys: intake_v2_enabled (bool).';


--
-- Name: personas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.personas (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    requisition_id uuid,
    name text,
    dimensions jsonb NOT NULL,
    composed_text text NOT NULL,
    derived_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_template boolean DEFAULT false NOT NULL
);


--
-- Name: plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plans (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    name character varying(50) NOT NULL,
    display_name character varying(100) NOT NULL,
    price_cents integer DEFAULT 0 NOT NULL,
    "interval" character varying(20) DEFAULT 'monthly'::character varying,
    intake_credits integer DEFAULT 1 NOT NULL,
    interview_credits integer DEFAULT 1 NOT NULL,
    slack_enabled boolean DEFAULT false,
    max_users integer DEFAULT 1,
    dodo_product_id character varying(255),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    google_calendar_enabled boolean DEFAULT false
);


--
-- Name: profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.profiles (
    id uuid NOT NULL,
    organization_id uuid,
    email character varying(255) NOT NULL,
    full_name character varying(255),
    is_staff boolean DEFAULT false,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    invitation_status character varying(50) DEFAULT 'invited'::character varying,
    onboarding_completed boolean DEFAULT false,
    avatar_url text,
    timezone text
);


--
-- Name: promotions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.promotions (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    code character varying(50) NOT NULL,
    percent_off integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true,
    start_date timestamp with time zone DEFAULT now(),
    end_date timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT promotions_percent_off_check CHECK (((percent_off >= 0) AND (percent_off <= 100)))
);


--
-- Name: recall_bots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recall_bots (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    candidate_round_id uuid,
    recall_bot_id text NOT NULL,
    meeting_url text NOT NULL,
    meeting_platform text DEFAULT 'google_meet'::text,
    bot_name text,
    scheduled_at timestamp with time zone,
    status text DEFAULT 'created'::text,
    joined_at timestamp with time zone,
    left_at timestamp with time zone,
    recording_url text,
    recording_duration_seconds integer,
    transcript_url text,
    transcript_ready boolean DEFAULT false,
    transcript_data jsonb,
    participants jsonb,
    status_history jsonb DEFAULT '[]'::jsonb,
    error_code text,
    error_sub_code text,
    error_message text,
    last_webhook_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    feedback_status text DEFAULT 'none'::text,
    feedback_started_at timestamp with time zone,
    feedback_completed_at timestamp with time zone,
    candidate_name text,
    candidate_participant_id integer,
    tracked_participants jsonb DEFAULT '[]'::jsonb,
    participant_utterances jsonb DEFAULT '{}'::jsonb,
    detected_candidate_participant_id integer,
    detection_confidence double precision,
    detection_reasoning text,
    detection_completed boolean DEFAULT false,
    voice_session_token uuid,
    voice_session_status text DEFAULT 'dormant'::text,
    requisition_id uuid,
    credit_charged boolean DEFAULT false,
    detection_id uuid,
    source text DEFAULT 'manual'::text,
    recording_url_expires_at timestamp with time zone,
    CONSTRAINT recall_bots_feedback_status_check CHECK ((feedback_status = ANY (ARRAY['none'::text, 'waiting_for_leave'::text, 'waiting_for_yes'::text, 'collecting'::text, 'completed'::text, 'partial'::text, 'skipped'::text, 'voice_active'::text]))),
    CONSTRAINT recall_bots_status_check CHECK ((status = ANY (ARRAY['created'::text, 'joining'::text, 'in_waiting_room'::text, 'in_call_not_recording'::text, 'in_call_recording'::text, 'call_ended'::text, 'processing'::text, 'done'::text, 'failed'::text, 'cancelled'::text]))),
    CONSTRAINT recall_bots_voice_session_status_check CHECK ((voice_session_status = ANY (ARRAY['dormant'::text, 'activating'::text, 'active'::text, 'completed'::text, 'error'::text])))
);


--
-- Name: requisitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.requisitions (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    organization_id uuid NOT NULL,
    created_by uuid,
    role_title character varying(255) NOT NULL,
    role_location character varying(255) NOT NULL,
    experience_min_years integer DEFAULT 0 NOT NULL,
    experience_max_years integer,
    status character varying(50) DEFAULT 'intake_pending'::character varying NOT NULL,
    intake_notes text,
    job_description text,
    must_have_skills text[] DEFAULT '{}'::text[],
    good_to_have_skills text[] DEFAULT '{}'::text[],
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    intake_transcript text,
    intake_processing_status character varying(50) DEFAULT NULL::character varying,
    intake_processing_error text,
    intake_processing_started_at timestamp with time zone,
    intake_processing_completed_at timestamp with time zone,
    intake_voice_session_token uuid,
    intake_voice_session_status character varying,
    intake_processing_stage character varying,
    intake_summary text,
    debrief_ai_summary jsonb,
    intake_credit_charged boolean DEFAULT false,
    is_system_template boolean DEFAULT false NOT NULL,
    template_key text,
    source text DEFAULT 'native'::text NOT NULL,
    ats_provider text,
    ats_synced_at timestamp with time zone,
    CONSTRAINT requisitions_intake_processing_status_check CHECK (((intake_processing_status)::text = ANY ((ARRAY['processing'::character varying, 'completed'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT requisitions_source_check CHECK ((source = ANY (ARRAY['native'::text, 'ats_sync'::text]))),
    CONSTRAINT requisitions_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'intake_pending'::character varying, 'planned'::character varying, 'closed'::character varying])::text[]))),
    CONSTRAINT valid_experience CHECK (((experience_max_years IS NULL) OR (experience_max_years >= experience_min_years)))
);


--
-- Name: COLUMN requisitions.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.requisitions.status IS 'Status: draft (v2 intake pre-publish) → intake_pending (v1 default, post-form) → planned → closed';


--
-- Name: COLUMN requisitions.is_system_template; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.requisitions.is_system_template IS 'True for system-managed hidden requisitions (e.g., untracked interview capture). Excluded from user-facing lists and dashboard metrics.';


--
-- Name: COLUMN requisitions.template_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.requisitions.template_key IS 'Template identity for system requisitions. Meaningful only when is_system_template = true.';


--
-- Name: round_screening_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.round_screening_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    round_id uuid NOT NULL,
    requisition_id uuid NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    voice text DEFAULT 'aura-luna-en'::text NOT NULL,
    follow_up_style text DEFAULT 'adaptive_probes'::text NOT NULL,
    est_duration_minutes integer,
    validity_days integer DEFAULT 7 NOT NULL,
    deploy_scope text DEFAULT 'manual'::text NOT NULL,
    persona_id uuid,
    persona_snapshot jsonb,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT round_screening_configs_deploy_scope_check CHECK ((deploy_scope = ANY (ARRAY['manual'::text, 'all_resume_passed'::text]))),
    CONSTRAINT round_screening_configs_validity_days_check CHECK (((validity_days >= 1) AND (validity_days <= 60)))
);


--
-- Name: round_screening_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.round_screening_questions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    round_screening_config_id uuid NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    title text NOT NULL,
    prompt text NOT NULL,
    probe text,
    signal text,
    dimension text,
    duration_minutes integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: rounds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rounds (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    requisition_id uuid NOT NULL,
    round_number integer NOT NULL,
    name character varying(255) NOT NULL,
    category text,
    duration_minutes integer DEFAULT 45 NOT NULL,
    description text,
    skills text[] DEFAULT '{}'::text[],
    guidelines jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    round_type text DEFAULT 'interview'::text,
    assessment_template_id uuid,
    default_interviewer_emails text[] DEFAULT '{}'::text[],
    for_candidate_id uuid,
    removed_from_plan_at timestamp with time zone,
    ai_screenable boolean DEFAULT false NOT NULL,
    ai_screenable_reason text,
    CONSTRAINT rounds_duration_minutes_check CHECK (((duration_minutes > 0) AND (duration_minutes <= 480)))
);


--
-- Name: screening_invites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_invites (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    token character varying(64) NOT NULL,
    candidate_round_id uuid NOT NULL,
    candidate_email text NOT NULL,
    otp_code character varying(6),
    otp_expires_at timestamp with time zone,
    otp_attempts integer DEFAULT 0 NOT NULL,
    otp_locked_until timestamp with time zone,
    otp_last_sent_at timestamp with time zone,
    otp_success_count integer DEFAULT 0 NOT NULL,
    session_token text,
    session_expires_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_accessed_at timestamp with time zone
);


--
-- Name: slack_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.slack_connections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slack_user_id text NOT NULL,
    slack_team_id text NOT NULL,
    profile_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    user_slack_features jsonb
);


--
-- Name: COLUMN slack_connections.user_slack_features; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.slack_connections.user_slack_features IS 'Per-user Slack feature overrides. NULL = inherit org defaults. Keys: calendar_notifications, assistant_read, assistant_write';


--
-- Name: slack_installations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.slack_installations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slack_team_id text NOT NULL,
    slack_team_name text,
    slack_team_domain text,
    bot_token_encrypted text NOT NULL,
    bot_user_id text,
    installed_by uuid,
    scopes text,
    is_active boolean DEFAULT true,
    installed_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    refresh_token_encrypted text,
    token_expires_at timestamp with time zone,
    token_issued_at timestamp with time zone,
    token_type text,
    auth_state text DEFAULT 'healthy'::text NOT NULL,
    last_auth_error_code text,
    last_auth_error_at timestamp with time zone,
    last_refresh_attempt_at timestamp with time zone,
    last_refresh_success_at timestamp with time zone,
    refresh_lock_at timestamp with time zone,
    refresh_lock_owner text,
    reauth_notified_at timestamp with time zone,
    CONSTRAINT slack_installations_auth_state_check CHECK ((auth_state = ANY (ARRAY['healthy'::text, 'refreshing'::text, 'needs_reauth'::text, 'disabled'::text])))
);


--
-- Name: subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subscriptions (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    organization_id uuid NOT NULL,
    plan_id uuid NOT NULL,
    status character varying(30) DEFAULT 'active'::character varying NOT NULL,
    dodo_subscription_id character varying(255),
    dodo_customer_id character varying(255),
    current_period_start timestamp with time zone,
    current_period_end timestamp with time zone,
    cancel_at_period_end boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    custom_price_cents integer,
    custom_intake_credits integer,
    custom_interview_credits integer,
    custom_max_users integer,
    is_manual boolean DEFAULT false
);


--
-- Name: topup_credits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topup_credits (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    organization_id uuid NOT NULL,
    credit_type character varying(30) DEFAULT 'interview'::character varying NOT NULL,
    amount integer DEFAULT 0 NOT NULL,
    remaining integer DEFAULT 0 NOT NULL,
    dodo_payment_id character varying(255),
    purchased_at timestamp with time zone DEFAULT now()
);


--
-- Name: topup_products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topup_products (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    name character varying(100) NOT NULL,
    credit_type character varying(30) DEFAULT 'interview'::character varying NOT NULL,
    credit_amount integer NOT NULL,
    price_cents integer NOT NULL,
    dodo_product_id character varying(255),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: transcripts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transcripts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    candidate_round_id uuid,
    recall_transcript_id text,
    provider text DEFAULT 'recallai'::text,
    full_text text,
    segments jsonb,
    raw_transcript_url text,
    word_count integer,
    duration_seconds integer,
    language text DEFAULT 'en'::text,
    processed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    feedback_transcript text,
    participant_metadata jsonb
);


--
-- Name: COLUMN transcripts.feedback_transcript; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transcripts.feedback_transcript IS 'Manual or override feedback transcript text. If set, used instead of computing from segments.';


--
-- Name: COLUMN transcripts.participant_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transcripts.participant_metadata IS 'Full participant list from Recall API with is_host, extra_data (contains platform-specific fields like participant_type for Teams, meeting_role for Google Meet)';


--
-- Name: untracked_interview_imports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.untracked_interview_imports (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    organization_id uuid NOT NULL,
    source_detection_id uuid NOT NULL,
    source_generic_candidate_id uuid NOT NULL,
    source_generic_candidate_round_id uuid NOT NULL,
    target_requisition_id uuid NOT NULL,
    target_round_id uuid NOT NULL,
    target_candidate_id uuid NOT NULL,
    target_candidate_round_id uuid NOT NULL,
    import_status text NOT NULL,
    error text,
    imported_by_user_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    superseded_at timestamp with time zone,
    prior_round_snapshot jsonb,
    CONSTRAINT untracked_interview_imports_import_status_check CHECK ((import_status = ANY (ARRAY['copied'::text, 'copied_pending_scorecard'::text, 'reprocessed'::text, 'reprocess_failed'::text, 'failed'::text])))
);


--
-- Name: TABLE untracked_interview_imports; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.untracked_interview_imports IS 'Audit trail for imports from generic captures into real requisitions.';


--
-- Name: COLUMN untracked_interview_imports.superseded_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.untracked_interview_imports.superseded_at IS 'UNTRACKED-MA: NULL = the active/honored association attempt for this untracked interview; non-null = a kept (restorable) prior attempt that was reassigned away.';


--
-- Name: usage_credits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_credits (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    organization_id uuid NOT NULL,
    credit_type character varying(30) NOT NULL,
    total integer DEFAULT 0 NOT NULL,
    used integer DEFAULT 0 NOT NULL,
    period_start timestamp with time zone DEFAULT now(),
    period_end timestamp with time zone
);


--
-- Name: user_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_connections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    profile_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    provider text NOT NULL,
    provider_account_id text,
    provider_email text,
    access_token_encrypted text NOT NULL,
    refresh_token_encrypted text NOT NULL,
    token_expires_at timestamp with time zone,
    scopes text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    recall_calendar_id text,
    calendar_watch_enabled boolean DEFAULT true,
    auto_join_untracked boolean DEFAULT false
);


--
-- Name: COLUMN user_connections.auto_join_untracked; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_connections.auto_join_untracked IS 'Per-user preference: when true, the platform auto-joins untracked interviews for this calendar connection.';


--
-- Name: user_conversation_history; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.user_conversation_history WITH (security_invoker='true') AS
 SELECT id AS conversation_id,
    user_id,
    organization_id,
    'intake'::text AS kind,
    concat('Intake: ', COALESCE((form_data ->> 'role_name'::text), 'Untitled'::text)) AS title,
    COALESCE((form_data ->> 'role_name'::text), 'Untitled'::text) AS role_name,
    ((form_data ->> 'experience_min'::text))::integer AS exp_min,
    ((form_data ->> 'experience_max'::text))::integer AS exp_max,
    (form_data ->> 'location'::text) AS location,
        CASE status
            WHEN 'published'::public.intake_session_status THEN 'completed'::text
            WHEN 'submitted'::public.intake_session_status THEN 'submitted'::text
            ELSE 'incomplete'::text
        END AS display_status,
    (status)::text AS detail_status,
    (active_modality)::text AS active_modality,
    requisition_id,
    updated_at AS last_activity_at,
    ('/intake/sessions/'::text || (id)::text) AS resume_url
   FROM public.intake_sessions
  WHERE (status <> 'abandoned'::public.intake_session_status);


--
-- Name: VIEW user_conversation_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.user_conversation_history IS 'Composable history surface; backs GET /api/v2/intake/sessions. Exposes role_name/exp_min/exp_max/location from form_data for rich lobby cards.';


--
-- Name: agent_conversations agent_conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_conversations
    ADD CONSTRAINT agent_conversations_pkey PRIMARY KEY (id);


--
-- Name: agent_conversations agent_conversations_slack_user_id_slack_channel_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_conversations
    ADD CONSTRAINT agent_conversations_slack_user_id_slack_channel_id_key UNIQUE (slack_user_id, slack_channel_id);


--
-- Name: agent_memories agent_memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_memories
    ADD CONSTRAINT agent_memories_pkey PRIMARY KEY (id);


--
-- Name: agent_pending_tasks agent_pending_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_pending_tasks
    ADD CONSTRAINT agent_pending_tasks_pkey PRIMARY KEY (id);


--
-- Name: assessment_evaluations assessment_evaluations_assessment_instance_id_category_inde_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_evaluations
    ADD CONSTRAINT assessment_evaluations_assessment_instance_id_category_inde_key UNIQUE (assessment_instance_id, category_index);


--
-- Name: assessment_evaluations assessment_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_evaluations
    ADD CONSTRAINT assessment_evaluations_pkey PRIMARY KEY (id);


--
-- Name: assessment_instances assessment_instances_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_instances
    ADD CONSTRAINT assessment_instances_pkey PRIMARY KEY (id);


--
-- Name: assessment_templates assessment_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_templates
    ADD CONSTRAINT assessment_templates_pkey PRIMARY KEY (id);


--
-- Name: ats_connections ats_connections_knit_integration_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_connections
    ADD CONSTRAINT ats_connections_knit_integration_id_key UNIQUE (knit_integration_id);


--
-- Name: ats_connections ats_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_connections
    ADD CONSTRAINT ats_connections_pkey PRIMARY KEY (id);


--
-- Name: ats_entity_links ats_entity_links_native_type_native_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_entity_links
    ADD CONSTRAINT ats_entity_links_native_type_native_id_key UNIQUE (native_type, native_id);


--
-- Name: ats_entity_links ats_entity_links_organization_id_ats_type_ats_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_entity_links
    ADD CONSTRAINT ats_entity_links_organization_id_ats_type_ats_id_key UNIQUE (organization_id, ats_type, ats_id);


--
-- Name: ats_entity_links ats_entity_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_entity_links
    ADD CONSTRAINT ats_entity_links_pkey PRIMARY KEY (id);


--
-- Name: ats_interviews ats_interviews_organization_id_ats_interview_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_interviews
    ADD CONSTRAINT ats_interviews_organization_id_ats_interview_event_id_key UNIQUE (organization_id, ats_interview_event_id);


--
-- Name: ats_interviews ats_interviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_interviews
    ADD CONSTRAINT ats_interviews_pkey PRIMARY KEY (id);


--
-- Name: ats_stage_round_map ats_stage_round_map_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_stage_round_map
    ADD CONSTRAINT ats_stage_round_map_pkey PRIMARY KEY (id);


--
-- Name: ats_stage_round_map ats_stage_round_map_requisition_id_ats_stage_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_stage_round_map
    ADD CONSTRAINT ats_stage_round_map_requisition_id_ats_stage_id_key UNIQUE (requisition_id, ats_stage_id);


--
-- Name: ats_webhook_events ats_webhook_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_webhook_events
    ADD CONSTRAINT ats_webhook_events_pkey PRIMARY KEY (event_id);


--
-- Name: blog_posts blog_posts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_posts
    ADD CONSTRAINT blog_posts_pkey PRIMARY KEY (id);


--
-- Name: blog_posts blog_posts_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_posts
    ADD CONSTRAINT blog_posts_slug_key UNIQUE (slug);


--
-- Name: calendar_event_detections calendar_event_detections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calendar_event_detections
    ADD CONSTRAINT calendar_event_detections_pkey PRIMARY KEY (id);


--
-- Name: calendar_event_detections calendar_event_detections_recall_event_id_profile_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calendar_event_detections
    ADD CONSTRAINT calendar_event_detections_recall_event_id_profile_id_key UNIQUE (recall_event_id, profile_id);


--
-- Name: calendar_intelligence_state calendar_intelligence_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calendar_intelligence_state
    ADD CONSTRAINT calendar_intelligence_state_pkey PRIMARY KEY (key);


--
-- Name: candidate_feedback candidate_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_feedback
    ADD CONSTRAINT candidate_feedback_pkey PRIMARY KEY (id);


--
-- Name: candidate_rounds candidate_rounds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_rounds
    ADD CONSTRAINT candidate_rounds_pkey PRIMARY KEY (id);


--
-- Name: candidates candidates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT candidates_pkey PRIMARY KEY (id);


--
-- Name: cortex_events cortex_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_events
    ADD CONSTRAINT cortex_events_pkey PRIMARY KEY (id);


--
-- Name: cortex_events cortex_events_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_events
    ADD CONSTRAINT cortex_events_unique UNIQUE (event_type, source_id);


--
-- Name: cortex_force_publish_jobs cortex_force_publish_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_force_publish_jobs
    ADD CONSTRAINT cortex_force_publish_jobs_pkey PRIMARY KEY (id);


--
-- Name: cortex_ingestion_record cortex_ingestion_record_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_ingestion_record
    ADD CONSTRAINT cortex_ingestion_record_pkey PRIMARY KEY (id);


--
-- Name: cortex_ingestion_record cortex_ingestion_record_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_ingestion_record
    ADD CONSTRAINT cortex_ingestion_record_unique UNIQUE (event_type, source_id);


--
-- Name: cortex_org_ingest_jobs cortex_org_ingest_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_org_ingest_jobs
    ADD CONSTRAINT cortex_org_ingest_jobs_pkey PRIMARY KEY (id);


--
-- Name: debrief_conversations debrief_conversations_packet_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_conversations
    ADD CONSTRAINT debrief_conversations_packet_id_key UNIQUE (packet_id);


--
-- Name: debrief_conversations debrief_conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_conversations
    ADD CONSTRAINT debrief_conversations_pkey PRIMARY KEY (id);


--
-- Name: debrief_insights debrief_insights_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_insights
    ADD CONSTRAINT debrief_insights_pkey PRIMARY KEY (id);


--
-- Name: debrief_packets debrief_packets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_packets
    ADD CONSTRAINT debrief_packets_pkey PRIMARY KEY (id);


--
-- Name: feedback_access_tokens feedback_access_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_access_tokens
    ADD CONSTRAINT feedback_access_tokens_pkey PRIMARY KEY (id);


--
-- Name: feedback_access_tokens feedback_access_tokens_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_access_tokens
    ADD CONSTRAINT feedback_access_tokens_token_key UNIQUE (token);


--
-- Name: feedback_questions feedback_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_questions
    ADD CONSTRAINT feedback_questions_pkey PRIMARY KEY (id);


--
-- Name: intake_sessions intake_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_sessions
    ADD CONSTRAINT intake_sessions_pkey PRIMARY KEY (id);


--
-- Name: mcp_audit_log mcp_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_audit_log
    ADD CONSTRAINT mcp_audit_log_pkey PRIMARY KEY (id);


--
-- Name: oauth_authorization_codes oauth_authorization_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_codes
    ADD CONSTRAINT oauth_authorization_codes_pkey PRIMARY KEY (code);


--
-- Name: oauth_clients oauth_clients_client_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_clients
    ADD CONSTRAINT oauth_clients_client_id_key UNIQUE (client_id);


--
-- Name: oauth_clients oauth_clients_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_clients
    ADD CONSTRAINT oauth_clients_pkey PRIMARY KEY (id);


--
-- Name: oauth_refresh_tokens oauth_refresh_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_refresh_tokens
    ADD CONSTRAINT oauth_refresh_tokens_pkey PRIMARY KEY (token_hash);


--
-- Name: org_generic_template_bindings org_generic_template_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_generic_template_bindings
    ADD CONSTRAINT org_generic_template_bindings_pkey PRIMARY KEY (id);


--
-- Name: organization_invites organization_invites_organization_id_email_status_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT organization_invites_organization_id_email_status_key UNIQUE (organization_id, email, status);


--
-- Name: organization_invites organization_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT organization_invites_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: personas personas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personas
    ADD CONSTRAINT personas_pkey PRIMARY KEY (id);


--
-- Name: plans plans_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plans
    ADD CONSTRAINT plans_name_key UNIQUE (name);


--
-- Name: plans plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plans
    ADD CONSTRAINT plans_pkey PRIMARY KEY (id);


--
-- Name: profiles profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);


--
-- Name: promotions promotions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_pkey PRIMARY KEY (id);


--
-- Name: recall_bots recall_bots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recall_bots
    ADD CONSTRAINT recall_bots_pkey PRIMARY KEY (id);


--
-- Name: recall_bots recall_bots_recall_bot_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recall_bots
    ADD CONSTRAINT recall_bots_recall_bot_id_key UNIQUE (recall_bot_id);


--
-- Name: requisitions requisitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT requisitions_pkey PRIMARY KEY (id);


--
-- Name: round_screening_configs round_screening_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_screening_configs
    ADD CONSTRAINT round_screening_configs_pkey PRIMARY KEY (id);


--
-- Name: round_screening_configs round_screening_configs_round_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_screening_configs
    ADD CONSTRAINT round_screening_configs_round_id_key UNIQUE (round_id);


--
-- Name: round_screening_questions round_screening_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_screening_questions
    ADD CONSTRAINT round_screening_questions_pkey PRIMARY KEY (id);


--
-- Name: rounds rounds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rounds
    ADD CONSTRAINT rounds_pkey PRIMARY KEY (id);


--
-- Name: screening_invites screening_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_invites
    ADD CONSTRAINT screening_invites_pkey PRIMARY KEY (id);


--
-- Name: screening_invites screening_invites_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_invites
    ADD CONSTRAINT screening_invites_token_key UNIQUE (token);


--
-- Name: slack_connections slack_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_connections
    ADD CONSTRAINT slack_connections_pkey PRIMARY KEY (id);


--
-- Name: slack_connections slack_connections_slack_user_id_slack_team_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_connections
    ADD CONSTRAINT slack_connections_slack_user_id_slack_team_id_key UNIQUE (slack_user_id, slack_team_id);


--
-- Name: slack_installations slack_installations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_installations
    ADD CONSTRAINT slack_installations_pkey PRIMARY KEY (id);


--
-- Name: slack_installations slack_installations_slack_team_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_installations
    ADD CONSTRAINT slack_installations_slack_team_id_key UNIQUE (slack_team_id);


--
-- Name: subscriptions subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_pkey PRIMARY KEY (id);


--
-- Name: topup_credits topup_credits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topup_credits
    ADD CONSTRAINT topup_credits_pkey PRIMARY KEY (id);


--
-- Name: topup_products topup_products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topup_products
    ADD CONSTRAINT topup_products_pkey PRIMARY KEY (id);


--
-- Name: transcripts transcripts_candidate_round_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transcripts
    ADD CONSTRAINT transcripts_candidate_round_id_key UNIQUE (candidate_round_id);


--
-- Name: transcripts transcripts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transcripts
    ADD CONSTRAINT transcripts_pkey PRIMARY KEY (id);


--
-- Name: untracked_interview_imports untracked_interview_imports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.untracked_interview_imports
    ADD CONSTRAINT untracked_interview_imports_pkey PRIMARY KEY (id);


--
-- Name: debrief_insights uq_debrief_insight_dedup; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_insights
    ADD CONSTRAINT uq_debrief_insight_dedup UNIQUE (packet_id, content_hash);


--
-- Name: untracked_interview_imports uq_import_source_target; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.untracked_interview_imports
    ADD CONSTRAINT uq_import_source_target UNIQUE (source_generic_candidate_round_id, target_requisition_id, target_round_id);


--
-- Name: org_generic_template_bindings uq_org_template_binding; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_generic_template_bindings
    ADD CONSTRAINT uq_org_template_binding UNIQUE (organization_id, template_key);


--
-- Name: usage_credits usage_credits_organization_id_credit_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_credits
    ADD CONSTRAINT usage_credits_organization_id_credit_type_key UNIQUE (organization_id, credit_type);


--
-- Name: usage_credits usage_credits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_credits
    ADD CONSTRAINT usage_credits_pkey PRIMARY KEY (id);


--
-- Name: user_connections user_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_connections
    ADD CONSTRAINT user_connections_pkey PRIMARY KEY (id);


--
-- Name: user_connections user_connections_profile_id_provider_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_connections
    ADD CONSTRAINT user_connections_profile_id_provider_key UNIQUE (profile_id, provider);


--
-- Name: cortex_force_publish_jobs_one_active_per_org; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX cortex_force_publish_jobs_one_active_per_org ON public.cortex_force_publish_jobs USING btree (org_id) WHERE (status = ANY (ARRAY['pending'::text, 'running'::text]));


--
-- Name: cortex_org_ingest_jobs_one_active_per_org; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX cortex_org_ingest_jobs_one_active_per_org ON public.cortex_org_ingest_jobs USING btree (org_id) WHERE (status = ANY (ARRAY['pending'::text, 'running'::text]));


--
-- Name: idx_agent_conversations_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_conversations_channel ON public.agent_conversations USING btree (slack_channel_id);


--
-- Name: idx_agent_conversations_slack_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_conversations_slack_user_id ON public.agent_conversations USING btree (slack_user_id);


--
-- Name: idx_agent_memories_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_memories_embedding ON public.agent_memories USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='100');


--
-- Name: idx_agent_memories_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_memories_user_id ON public.agent_memories USING btree (user_id);


--
-- Name: idx_agent_pending_tasks_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_pending_tasks_expires ON public.agent_pending_tasks USING btree (expires_at) WHERE (status = 'waiting'::text);


--
-- Name: idx_agent_pending_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_pending_tasks_status ON public.agent_pending_tasks USING btree (status);


--
-- Name: idx_agent_pending_tasks_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_pending_tasks_user ON public.agent_pending_tasks USING btree (user_id, channel_id);


--
-- Name: idx_agent_pending_tasks_watch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_pending_tasks_watch ON public.agent_pending_tasks USING btree (watch_table, watch_id, status);


--
-- Name: idx_assessment_evaluations_candidate_round; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessment_evaluations_candidate_round ON public.assessment_evaluations USING btree (candidate_round_id);


--
-- Name: idx_assessment_evaluations_instance; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessment_evaluations_instance ON public.assessment_evaluations USING btree (assessment_instance_id);


--
-- Name: idx_assessment_instances_access_code_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessment_instances_access_code_hash ON public.assessment_instances USING btree (access_code_hash);


--
-- Name: idx_assessment_instances_candidate_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessment_instances_candidate_id ON public.assessment_instances USING btree (candidate_id);


--
-- Name: idx_assessment_instances_evaluated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessment_instances_evaluated_at ON public.assessment_instances USING btree (evaluated_at) WHERE (evaluated_at IS NOT NULL);


--
-- Name: idx_assessment_instances_round_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessment_instances_round_id ON public.assessment_instances USING btree (round_id);


--
-- Name: idx_assessment_instances_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessment_instances_template_id ON public.assessment_instances USING btree (template_id);


--
-- Name: idx_assessment_templates_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessment_templates_status_created ON public.assessment_templates USING btree (status, created_at DESC);


--
-- Name: idx_ats_connections_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ats_connections_org ON public.ats_connections USING btree (organization_id);


--
-- Name: idx_ats_entity_links_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ats_entity_links_org ON public.ats_entity_links USING btree (organization_id);


--
-- Name: idx_ats_interviews_org_application; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ats_interviews_org_application ON public.ats_interviews USING btree (organization_id, ats_application_id);


--
-- Name: idx_ats_interviews_unpromoted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ats_interviews_unpromoted ON public.ats_interviews USING btree (organization_id) WHERE (candidate_round_id IS NULL);


--
-- Name: idx_ats_stage_round_map_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ats_stage_round_map_org ON public.ats_stage_round_map USING btree (organization_id);


--
-- Name: idx_ats_stage_round_map_req; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ats_stage_round_map_req ON public.ats_stage_round_map USING btree (requisition_id);


--
-- Name: idx_ats_webhook_events_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ats_webhook_events_pending ON public.ats_webhook_events USING btree (received_at) WHERE (processed_at IS NULL);


--
-- Name: idx_blog_posts_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_blog_posts_slug ON public.blog_posts USING btree (slug);


--
-- Name: idx_blog_posts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_blog_posts_status ON public.blog_posts USING btree (status);


--
-- Name: idx_blog_posts_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_blog_posts_status_created ON public.blog_posts USING btree (status, created_at DESC);


--
-- Name: idx_cal_detections_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cal_detections_event ON public.calendar_event_detections USING btree (recall_event_id);


--
-- Name: idx_cal_detections_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cal_detections_org ON public.calendar_event_detections USING btree (organization_id);


--
-- Name: idx_cal_detections_org_identity_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cal_detections_org_identity_key ON public.calendar_event_detections USING btree (organization_id, identity_key) WHERE (identity_key IS NOT NULL);


--
-- Name: idx_cal_detections_orphan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cal_detections_orphan ON public.calendar_event_detections USING btree (detection_status, reminder_count, event_start) WHERE (detection_status = ANY (ARRAY['notified'::text, 'awaiting_role'::text, 'awaiting_round'::text, 'awaiting_confirm'::text, 'orphan_no_response'::text, 'orphan_role'::text, 'orphan_round'::text, 'orphan_confirm'::text]));


--
-- Name: idx_cal_detections_profile_ical_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cal_detections_profile_ical_uid ON public.calendar_event_detections USING btree (profile_id, ical_uid) WHERE (ical_uid IS NOT NULL);


--
-- Name: idx_cal_detections_profile_identity_key_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_cal_detections_profile_identity_key_unique ON public.calendar_event_detections USING btree (profile_id, identity_key) WHERE (identity_key IS NOT NULL);


--
-- Name: idx_cal_detections_profile_platform_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cal_detections_profile_platform_id ON public.calendar_event_detections USING btree (profile_id, platform_id) WHERE (platform_id IS NOT NULL);


--
-- Name: idx_cal_detections_single_reminder_window; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cal_detections_single_reminder_window ON public.calendar_event_detections USING btree (detection_status, reminder_count, event_start) WHERE ((detection_status = ANY (ARRAY['notified'::text, 'orphan_no_response'::text, 'orphan_role'::text, 'orphan_round'::text, 'orphan_confirm'::text])) AND (reminder_count = 0));


--
-- Name: idx_cal_detections_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cal_detections_status ON public.calendar_event_detections USING btree (detection_status, profile_id);


--
-- Name: idx_candidate_feedback_question; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_feedback_question ON public.candidate_feedback USING btree (feedback_question_id);


--
-- Name: idx_candidate_feedback_round; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_feedback_round ON public.candidate_feedback USING btree (candidate_round_id);


--
-- Name: idx_candidate_rounds_candidate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_candidate ON public.candidate_rounds USING btree (candidate_id);


--
-- Name: idx_candidate_rounds_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_created_by_user_id ON public.candidate_rounds USING btree (created_by_user_id);


--
-- Name: idx_candidate_rounds_feedback_approved_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_feedback_approved_at ON public.candidate_rounds USING btree (feedback_approved_at) WHERE (feedback_approved_at IS NOT NULL);


--
-- Name: idx_candidate_rounds_feedback_voice_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_feedback_voice_token ON public.candidate_rounds USING btree (feedback_voice_session_token) WHERE (feedback_voice_session_token IS NOT NULL);


--
-- Name: idx_candidate_rounds_origin_detection; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_origin_detection ON public.candidate_rounds USING btree (origin_detection_id) WHERE (origin_detection_id IS NOT NULL);


--
-- Name: idx_candidate_rounds_origin_round; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_origin_round ON public.candidate_rounds USING btree (origin_candidate_round_id) WHERE (origin_candidate_round_id IS NOT NULL);


--
-- Name: idx_candidate_rounds_prep_reminder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_prep_reminder ON public.candidate_rounds USING btree (scheduled_at) WHERE ((prep_reminder_sent = false) AND ((status)::text = 'scheduled'::text));


--
-- Name: idx_candidate_rounds_round; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_round ON public.candidate_rounds USING btree (round_id);


--
-- Name: idx_candidate_rounds_screening_voice_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_screening_voice_token ON public.candidate_rounds USING btree (screening_voice_session_token) WHERE (screening_voice_session_token IS NOT NULL);


--
-- Name: idx_candidate_rounds_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_source_type ON public.candidate_rounds USING btree (source_type) WHERE (source_type <> 'standard'::text);


--
-- Name: idx_candidate_rounds_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidate_rounds_status ON public.candidate_rounds USING btree (status);


--
-- Name: idx_candidate_rounds_unique_non_generic; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_candidate_rounds_unique_non_generic ON public.candidate_rounds USING btree (candidate_id, round_id) WHERE (source_type <> 'untracked_generic'::text);


--
-- Name: idx_candidate_rounds_unique_untracked_detection; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_candidate_rounds_unique_untracked_detection ON public.candidate_rounds USING btree (origin_detection_id) WHERE ((source_type = 'untracked_generic'::text) AND (origin_detection_id IS NOT NULL));


--
-- Name: idx_candidates_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidates_email ON public.candidates USING btree (requisition_id, email) WHERE (deleted_at IS NULL);


--
-- Name: idx_candidates_enrichment_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidates_enrichment_pending ON public.candidates USING btree (created_at) WHERE ((enrichment_status = 'pending'::text) AND (deleted_at IS NULL));


--
-- Name: idx_candidates_requisition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidates_requisition ON public.candidates USING btree (requisition_id) WHERE (deleted_at IS NULL);


--
-- Name: idx_candidates_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidates_status ON public.candidates USING btree (status) WHERE (deleted_at IS NULL);


--
-- Name: idx_cortex_events_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_events_org ON public.cortex_events USING btree (org_id);


--
-- Name: idx_cortex_events_re_edit; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_events_re_edit ON public.cortex_events USING btree (last_touch_at, published_at) WHERE (published_at IS NOT NULL);


--
-- Name: idx_cortex_events_unpublished; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_events_unpublished ON public.cortex_events USING btree (last_touch_at) WHERE (published_at IS NULL);


--
-- Name: idx_cortex_force_publish_jobs_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_force_publish_jobs_org_status ON public.cortex_force_publish_jobs USING btree (org_id, status);


--
-- Name: idx_cortex_force_publish_jobs_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_force_publish_jobs_started ON public.cortex_force_publish_jobs USING btree (started_at DESC);


--
-- Name: idx_cortex_ingestion_record_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_ingestion_record_event_type ON public.cortex_ingestion_record USING btree (event_type);


--
-- Name: idx_cortex_ingestion_record_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_ingestion_record_org ON public.cortex_ingestion_record USING btree (org_id);


--
-- Name: idx_cortex_org_ingest_jobs_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_org_ingest_jobs_org_status ON public.cortex_org_ingest_jobs USING btree (org_id, status);


--
-- Name: idx_cortex_org_ingest_jobs_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cortex_org_ingest_jobs_started ON public.cortex_org_ingest_jobs USING btree (started_at DESC);


--
-- Name: idx_debrief_conversations_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_debrief_conversations_org ON public.debrief_conversations USING btree (organization_id);


--
-- Name: idx_debrief_insights_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_debrief_insights_org ON public.debrief_insights USING btree (organization_id);


--
-- Name: idx_debrief_insights_sync; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_debrief_insights_sync ON public.debrief_insights USING btree (sync_status);


--
-- Name: idx_debrief_packets_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_debrief_packets_created_at ON public.debrief_packets USING btree (created_at DESC);


--
-- Name: idx_debrief_packets_organization; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_debrief_packets_organization ON public.debrief_packets USING btree (organization_id);


--
-- Name: idx_debrief_packets_requisition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_debrief_packets_requisition ON public.debrief_packets USING btree (requisition_id);


--
-- Name: idx_debrief_packets_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_debrief_packets_status ON public.debrief_packets USING btree (status);


--
-- Name: idx_feedback_questions_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_questions_order ON public.feedback_questions USING btree (round_id, question_number) WHERE (deleted_at IS NULL);


--
-- Name: idx_feedback_questions_round; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_questions_round ON public.feedback_questions USING btree (round_id) WHERE (deleted_at IS NULL);


--
-- Name: idx_feedback_tokens_candidate_round; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_tokens_candidate_round ON public.feedback_access_tokens USING btree (candidate_round_id);


--
-- Name: idx_feedback_tokens_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_tokens_email ON public.feedback_access_tokens USING btree (interviewer_email);


--
-- Name: idx_imports_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_imports_org ON public.untracked_interview_imports USING btree (organization_id);


--
-- Name: idx_imports_source_cr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_imports_source_cr ON public.untracked_interview_imports USING btree (source_generic_candidate_round_id);


--
-- Name: idx_imports_target_req; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_imports_target_req ON public.untracked_interview_imports USING btree (target_requisition_id);


--
-- Name: idx_intake_sessions_heartbeat_modality; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intake_sessions_heartbeat_modality ON public.intake_sessions USING btree (last_heartbeat_at) WHERE (active_modality IS NOT NULL);


--
-- Name: idx_intake_sessions_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intake_sessions_org ON public.intake_sessions USING btree (organization_id, status);


--
-- Name: idx_intake_sessions_req; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intake_sessions_req ON public.intake_sessions USING btree (requisition_id);


--
-- Name: idx_intake_sessions_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_intake_sessions_user ON public.intake_sessions USING btree (user_id, created_at DESC);


--
-- Name: idx_mcp_audit_org_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mcp_audit_org_time ON public.mcp_audit_log USING btree (org_id, created_at DESC);


--
-- Name: idx_mcp_audit_status_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mcp_audit_status_time ON public.mcp_audit_log USING btree (status, created_at DESC);


--
-- Name: idx_mcp_audit_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mcp_audit_user_time ON public.mcp_audit_log USING btree (user_id, created_at DESC);


--
-- Name: idx_oauth_clients_client_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_clients_client_id ON public.oauth_clients USING btree (client_id);


--
-- Name: idx_oauth_codes_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_codes_expires_at ON public.oauth_authorization_codes USING btree (expires_at);


--
-- Name: idx_oauth_refresh_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_refresh_expires_at ON public.oauth_refresh_tokens USING btree (expires_at);


--
-- Name: idx_oauth_refresh_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_refresh_user ON public.oauth_refresh_tokens USING btree (user_id, client_id);


--
-- Name: idx_org_invites_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_invites_email ON public.organization_invites USING btree (email);


--
-- Name: idx_org_invites_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_invites_org_status ON public.organization_invites USING btree (organization_id, status);


--
-- Name: idx_org_template_bindings_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_template_bindings_org ON public.org_generic_template_bindings USING btree (organization_id);


--
-- Name: idx_organizations_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_active ON public.organizations USING btree (id) WHERE (deleted_at IS NULL);


--
-- Name: idx_organizations_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_domain ON public.organizations USING btree (domain);


--
-- Name: idx_organizations_org_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_org_type ON public.organizations USING btree (org_type);


--
-- Name: idx_personas_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_personas_org ON public.personas USING btree (organization_id);


--
-- Name: idx_personas_org_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_personas_org_template ON public.personas USING btree (organization_id) WHERE is_template;


--
-- Name: idx_personas_requisition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_personas_requisition ON public.personas USING btree (requisition_id);


--
-- Name: idx_profiles_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_active ON public.profiles USING btree (id) WHERE (deleted_at IS NULL);


--
-- Name: idx_profiles_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_email ON public.profiles USING btree (email);


--
-- Name: idx_profiles_invitation_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_invitation_status ON public.profiles USING btree (invitation_status) WHERE (deleted_at IS NULL);


--
-- Name: idx_profiles_organization; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_organization ON public.profiles USING btree (organization_id);


--
-- Name: idx_profiles_staff; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_staff ON public.profiles USING btree (is_staff) WHERE (is_staff = true);


--
-- Name: idx_recall_bots_candidate_round_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recall_bots_candidate_round_id ON public.recall_bots USING btree (candidate_round_id);


--
-- Name: idx_recall_bots_feedback_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recall_bots_feedback_started_at ON public.recall_bots USING btree (feedback_started_at) WHERE (feedback_started_at IS NOT NULL);


--
-- Name: idx_recall_bots_feedback_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recall_bots_feedback_status ON public.recall_bots USING btree (feedback_status) WHERE (feedback_status <> 'none'::text);


--
-- Name: idx_recall_bots_recall_bot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recall_bots_recall_bot_id ON public.recall_bots USING btree (recall_bot_id);


--
-- Name: idx_recall_bots_requisition_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recall_bots_requisition_id ON public.recall_bots USING btree (requisition_id) WHERE (requisition_id IS NOT NULL);


--
-- Name: idx_recall_bots_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recall_bots_status ON public.recall_bots USING btree (status);


--
-- Name: idx_requisitions_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_requisitions_created_at ON public.requisitions USING btree (created_at DESC) WHERE (deleted_at IS NULL);


--
-- Name: idx_requisitions_intake_voice_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_requisitions_intake_voice_token ON public.requisitions USING btree (intake_voice_session_token) WHERE (intake_voice_session_token IS NOT NULL);


--
-- Name: idx_requisitions_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_requisitions_org_status ON public.requisitions USING btree (organization_id, status) WHERE (deleted_at IS NULL);


--
-- Name: idx_requisitions_organization; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_requisitions_organization ON public.requisitions USING btree (organization_id) WHERE (deleted_at IS NULL);


--
-- Name: idx_requisitions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_requisitions_status ON public.requisitions USING btree (status) WHERE (deleted_at IS NULL);


--
-- Name: idx_requisitions_template_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_requisitions_template_key ON public.requisitions USING btree (organization_id, template_key) WHERE ((is_system_template = true) AND (deleted_at IS NULL));


--
-- Name: idx_rounds_custom_per_candidate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rounds_custom_per_candidate ON public.rounds USING btree (for_candidate_id, round_number) WHERE (for_candidate_id IS NOT NULL);


--
-- Name: idx_rounds_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rounds_order ON public.rounds USING btree (requisition_id, round_number) WHERE (deleted_at IS NULL);


--
-- Name: idx_rounds_requisition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rounds_requisition ON public.rounds USING btree (requisition_id) WHERE (deleted_at IS NULL);


--
-- Name: idx_rounds_unique_active_shared; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_rounds_unique_active_shared ON public.rounds USING btree (requisition_id, round_number) WHERE ((removed_from_plan_at IS NULL) AND (for_candidate_id IS NULL) AND (deleted_at IS NULL));


--
-- Name: idx_rsc_requisition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rsc_requisition ON public.round_screening_configs USING btree (requisition_id);


--
-- Name: idx_rsq_config; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rsq_config ON public.round_screening_questions USING btree (round_screening_config_id);


--
-- Name: idx_screening_invites_round; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screening_invites_round ON public.screening_invites USING btree (candidate_round_id);


--
-- Name: idx_slack_connections_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_slack_connections_lookup ON public.slack_connections USING btree (slack_user_id, slack_team_id);


--
-- Name: idx_slack_connections_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_slack_connections_org ON public.slack_connections USING btree (organization_id);


--
-- Name: idx_slack_installations_refresh_scan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_slack_installations_refresh_scan ON public.slack_installations USING btree (is_active, auth_state, token_expires_at);


--
-- Name: idx_slack_installations_team_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_slack_installations_team_active ON public.slack_installations USING btree (slack_team_id, is_active);


--
-- Name: idx_subscriptions_dodo_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subscriptions_dodo_id ON public.subscriptions USING btree (dodo_subscription_id);


--
-- Name: idx_subscriptions_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subscriptions_org ON public.subscriptions USING btree (organization_id);


--
-- Name: idx_subscriptions_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subscriptions_org_status ON public.subscriptions USING btree (organization_id, status);


--
-- Name: idx_subscriptions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subscriptions_status ON public.subscriptions USING btree (status);


--
-- Name: idx_templates_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_templates_status ON public.assessment_templates USING btree (status);


--
-- Name: idx_topup_credits_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_topup_credits_org ON public.topup_credits USING btree (organization_id);


--
-- Name: idx_topup_credits_remaining; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_topup_credits_remaining ON public.topup_credits USING btree (organization_id, credit_type) WHERE (remaining > 0);


--
-- Name: idx_transcripts_candidate_round_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transcripts_candidate_round_id ON public.transcripts USING btree (candidate_round_id);


--
-- Name: idx_unique_candidate_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_unique_candidate_email ON public.candidates USING btree (requisition_id, email) WHERE (deleted_at IS NULL);


--
-- Name: idx_unique_question_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_unique_question_number ON public.feedback_questions USING btree (round_id, question_number) WHERE (deleted_at IS NULL);


--
-- Name: idx_untracked_imports_active_attempt; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_untracked_imports_active_attempt ON public.untracked_interview_imports USING btree (source_generic_candidate_round_id) WHERE (superseded_at IS NULL);


--
-- Name: INDEX idx_untracked_imports_active_attempt; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON INDEX public.idx_untracked_imports_active_attempt IS 'UNTRACKED-MA: fast lookup of the active (superseded_at IS NULL) attempt per untracked interview. NON-unique by design — the services keep single-active.';


--
-- Name: idx_usage_credits_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_usage_credits_org ON public.usage_credits USING btree (organization_id);


--
-- Name: idx_user_connections_profile_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_connections_profile_provider ON public.user_connections USING btree (profile_id, provider) WHERE (is_active = true);


--
-- Name: uq_ats_connections_active_org; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_ats_connections_active_org ON public.ats_connections USING btree (organization_id) WHERE (status = 'active'::text);


--
-- Name: uq_screening_invite_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_screening_invite_active ON public.screening_invites USING btree (candidate_round_id) WHERE (session_token IS NULL);


--
-- Name: intake_sessions set_updated_at_intake_sessions; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER set_updated_at_intake_sessions BEFORE UPDATE ON public.intake_sessions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: candidate_feedback trg_cortex_candidate_feedback; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cortex_candidate_feedback AFTER INSERT OR DELETE OR UPDATE ON public.candidate_feedback FOR EACH ROW EXECUTE FUNCTION public.cortex_emit_candidate_feedback_event();


--
-- Name: candidate_rounds trg_cortex_candidate_rounds; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cortex_candidate_rounds AFTER INSERT OR UPDATE OF processing_status, status, summary, rating, scorecard_status, outcome, completed_at ON public.candidate_rounds FOR EACH ROW EXECUTE FUNCTION public.cortex_emit_candidate_round_event();


--
-- Name: candidates trg_cortex_candidates; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cortex_candidates AFTER INSERT OR UPDATE OF status, final_verdict ON public.candidates FOR EACH ROW EXECUTE FUNCTION public.cortex_emit_candidate_event();


--
-- Name: requisitions trg_cortex_requisitions; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cortex_requisitions AFTER INSERT OR UPDATE OF intake_processing_status, intake_summary, intake_transcript, status ON public.requisitions FOR EACH ROW EXECUTE FUNCTION public.cortex_emit_requisition_event();


--
-- Name: rounds trg_cortex_rounds; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cortex_rounds AFTER INSERT OR UPDATE OF name, category, skills, description, guidelines ON public.rounds FOR EACH ROW EXECUTE FUNCTION public.cortex_emit_round_event();


--
-- Name: transcripts trg_cortex_transcripts; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cortex_transcripts AFTER INSERT OR UPDATE OF segments, full_text, feedback_transcript ON public.transcripts FOR EACH ROW EXECUTE FUNCTION public.cortex_emit_transcript_event();


--
-- Name: assessment_evaluations update_assessment_evaluations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_assessment_evaluations_updated_at BEFORE UPDATE ON public.assessment_evaluations FOR EACH ROW EXECUTE FUNCTION public.update_assessment_evaluations_updated_at();


--
-- Name: assessment_instances update_assessment_instances_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_assessment_instances_updated_at BEFORE UPDATE ON public.assessment_instances FOR EACH ROW EXECUTE FUNCTION public.update_assessment_instances_updated_at();


--
-- Name: assessment_templates update_assessment_templates_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_assessment_templates_updated_at BEFORE UPDATE ON public.assessment_templates FOR EACH ROW EXECUTE FUNCTION public.update_assessment_templates_updated_at();


--
-- Name: candidate_feedback update_candidate_feedback_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_candidate_feedback_updated_at BEFORE UPDATE ON public.candidate_feedback FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: candidate_rounds update_candidate_rounds_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_candidate_rounds_updated_at BEFORE UPDATE ON public.candidate_rounds FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: candidates update_candidates_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_candidates_updated_at BEFORE UPDATE ON public.candidates FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: feedback_questions update_feedback_questions_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_feedback_questions_updated_at BEFORE UPDATE ON public.feedback_questions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: organizations update_organizations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON public.organizations FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: profiles update_profiles_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_profiles_updated_at BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: requisitions update_requisitions_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_requisitions_updated_at BEFORE UPDATE ON public.requisitions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: rounds update_rounds_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_rounds_updated_at BEFORE UPDATE ON public.rounds FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: agent_conversations agent_conversations_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_conversations
    ADD CONSTRAINT agent_conversations_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: agent_pending_tasks agent_pending_tasks_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_pending_tasks
    ADD CONSTRAINT agent_pending_tasks_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: assessment_evaluations assessment_evaluations_assessment_instance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_evaluations
    ADD CONSTRAINT assessment_evaluations_assessment_instance_id_fkey FOREIGN KEY (assessment_instance_id) REFERENCES public.assessment_instances(id) ON DELETE CASCADE;


--
-- Name: assessment_evaluations assessment_evaluations_candidate_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_evaluations
    ADD CONSTRAINT assessment_evaluations_candidate_round_id_fkey FOREIGN KEY (candidate_round_id) REFERENCES public.candidate_rounds(id) ON DELETE CASCADE;


--
-- Name: assessment_evaluations assessment_evaluations_evaluator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_evaluations
    ADD CONSTRAINT assessment_evaluations_evaluator_id_fkey FOREIGN KEY (evaluator_id) REFERENCES public.profiles(id);


--
-- Name: assessment_instances assessment_instances_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_instances
    ADD CONSTRAINT assessment_instances_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id);


--
-- Name: assessment_instances assessment_instances_evaluator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_instances
    ADD CONSTRAINT assessment_instances_evaluator_id_fkey FOREIGN KEY (evaluator_id) REFERENCES public.profiles(id);


--
-- Name: assessment_instances assessment_instances_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_instances
    ADD CONSTRAINT assessment_instances_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.rounds(id);


--
-- Name: assessment_instances assessment_instances_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_instances
    ADD CONSTRAINT assessment_instances_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.assessment_templates(id);


--
-- Name: assessment_templates assessment_templates_parent_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment_templates
    ADD CONSTRAINT assessment_templates_parent_template_id_fkey FOREIGN KEY (parent_template_id) REFERENCES public.assessment_templates(id) ON DELETE SET NULL;


--
-- Name: ats_connections ats_connections_connected_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_connections
    ADD CONSTRAINT ats_connections_connected_by_fkey FOREIGN KEY (connected_by) REFERENCES public.profiles(id) ON DELETE SET NULL;


--
-- Name: ats_connections ats_connections_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_connections
    ADD CONSTRAINT ats_connections_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: ats_entity_links ats_entity_links_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_entity_links
    ADD CONSTRAINT ats_entity_links_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.ats_connections(id) ON DELETE CASCADE;


--
-- Name: ats_entity_links ats_entity_links_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_entity_links
    ADD CONSTRAINT ats_entity_links_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: ats_interviews ats_interviews_candidate_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_interviews
    ADD CONSTRAINT ats_interviews_candidate_round_id_fkey FOREIGN KEY (candidate_round_id) REFERENCES public.candidate_rounds(id) ON DELETE SET NULL;


--
-- Name: ats_interviews ats_interviews_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_interviews
    ADD CONSTRAINT ats_interviews_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.ats_connections(id) ON DELETE CASCADE;


--
-- Name: ats_interviews ats_interviews_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_interviews
    ADD CONSTRAINT ats_interviews_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: ats_stage_round_map ats_stage_round_map_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_stage_round_map
    ADD CONSTRAINT ats_stage_round_map_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: ats_stage_round_map ats_stage_round_map_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_stage_round_map
    ADD CONSTRAINT ats_stage_round_map_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: ats_stage_round_map ats_stage_round_map_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ats_stage_round_map
    ADD CONSTRAINT ats_stage_round_map_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.rounds(id) ON DELETE CASCADE;


--
-- Name: blog_posts blog_posts_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_posts
    ADD CONSTRAINT blog_posts_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.profiles(id);


--
-- Name: calendar_event_detections calendar_event_detections_matched_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calendar_event_detections
    ADD CONSTRAINT calendar_event_detections_matched_candidate_id_fkey FOREIGN KEY (matched_candidate_id) REFERENCES public.candidates(id);


--
-- Name: calendar_event_detections calendar_event_detections_matched_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calendar_event_detections
    ADD CONSTRAINT calendar_event_detections_matched_requisition_id_fkey FOREIGN KEY (matched_requisition_id) REFERENCES public.requisitions(id);


--
-- Name: calendar_event_detections calendar_event_detections_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calendar_event_detections
    ADD CONSTRAINT calendar_event_detections_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: calendar_event_detections calendar_event_detections_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calendar_event_detections
    ADD CONSTRAINT calendar_event_detections_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id);


--
-- Name: candidate_feedback candidate_feedback_candidate_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_feedback
    ADD CONSTRAINT candidate_feedback_candidate_round_id_fkey FOREIGN KEY (candidate_round_id) REFERENCES public.candidate_rounds(id) ON DELETE CASCADE;


--
-- Name: candidate_feedback candidate_feedback_feedback_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_feedback
    ADD CONSTRAINT candidate_feedback_feedback_question_id_fkey FOREIGN KEY (feedback_question_id) REFERENCES public.feedback_questions(id) ON DELETE CASCADE;


--
-- Name: candidate_rounds candidate_rounds_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_rounds
    ADD CONSTRAINT candidate_rounds_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: candidate_rounds candidate_rounds_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_rounds
    ADD CONSTRAINT candidate_rounds_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.profiles(id) ON DELETE SET NULL;


--
-- Name: candidate_rounds candidate_rounds_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidate_rounds
    ADD CONSTRAINT candidate_rounds_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.rounds(id) ON DELETE CASCADE;


--
-- Name: candidates candidates_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT candidates_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: cortex_events cortex_events_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_events
    ADD CONSTRAINT cortex_events_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: cortex_force_publish_jobs cortex_force_publish_jobs_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_force_publish_jobs
    ADD CONSTRAINT cortex_force_publish_jobs_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: cortex_ingestion_record cortex_ingestion_record_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_ingestion_record
    ADD CONSTRAINT cortex_ingestion_record_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: cortex_org_ingest_jobs cortex_org_ingest_jobs_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cortex_org_ingest_jobs
    ADD CONSTRAINT cortex_org_ingest_jobs_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: debrief_conversations debrief_conversations_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_conversations
    ADD CONSTRAINT debrief_conversations_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: debrief_conversations debrief_conversations_packet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_conversations
    ADD CONSTRAINT debrief_conversations_packet_id_fkey FOREIGN KEY (packet_id) REFERENCES public.debrief_packets(id) ON DELETE CASCADE;


--
-- Name: debrief_insights debrief_insights_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_insights
    ADD CONSTRAINT debrief_insights_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.profiles(id) ON DELETE SET NULL;


--
-- Name: debrief_insights debrief_insights_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_insights
    ADD CONSTRAINT debrief_insights_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: debrief_insights debrief_insights_packet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_insights
    ADD CONSTRAINT debrief_insights_packet_id_fkey FOREIGN KEY (packet_id) REFERENCES public.debrief_packets(id) ON DELETE CASCADE;


--
-- Name: debrief_packets debrief_packets_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_packets
    ADD CONSTRAINT debrief_packets_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.profiles(id) ON DELETE SET NULL;


--
-- Name: debrief_packets debrief_packets_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_packets
    ADD CONSTRAINT debrief_packets_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: debrief_packets debrief_packets_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.debrief_packets
    ADD CONSTRAINT debrief_packets_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: feedback_access_tokens feedback_access_tokens_candidate_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_access_tokens
    ADD CONSTRAINT feedback_access_tokens_candidate_round_id_fkey FOREIGN KEY (candidate_round_id) REFERENCES public.candidate_rounds(id) ON DELETE CASCADE;


--
-- Name: feedback_questions feedback_questions_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_questions
    ADD CONSTRAINT feedback_questions_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.rounds(id) ON DELETE CASCADE;


--
-- Name: intake_sessions intake_sessions_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_sessions
    ADD CONSTRAINT intake_sessions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: intake_sessions intake_sessions_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_sessions
    ADD CONSTRAINT intake_sessions_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: intake_sessions intake_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_sessions
    ADD CONSTRAINT intake_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id);


--
-- Name: oauth_authorization_codes oauth_authorization_codes_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_codes
    ADD CONSTRAINT oauth_authorization_codes_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.oauth_clients(client_id) ON DELETE CASCADE;


--
-- Name: oauth_refresh_tokens oauth_refresh_tokens_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_refresh_tokens
    ADD CONSTRAINT oauth_refresh_tokens_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.oauth_clients(client_id) ON DELETE CASCADE;


--
-- Name: org_generic_template_bindings org_generic_template_bindings_materialized_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_generic_template_bindings
    ADD CONSTRAINT org_generic_template_bindings_materialized_requisition_id_fkey FOREIGN KEY (materialized_requisition_id) REFERENCES public.requisitions(id);


--
-- Name: org_generic_template_bindings org_generic_template_bindings_materialized_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_generic_template_bindings
    ADD CONSTRAINT org_generic_template_bindings_materialized_round_id_fkey FOREIGN KEY (materialized_round_id) REFERENCES public.rounds(id);


--
-- Name: org_generic_template_bindings org_generic_template_bindings_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_generic_template_bindings
    ADD CONSTRAINT org_generic_template_bindings_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: organization_invites organization_invites_invited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT organization_invites_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES public.profiles(id);


--
-- Name: organization_invites organization_invites_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT organization_invites_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: personas personas_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personas
    ADD CONSTRAINT personas_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: personas personas_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personas
    ADD CONSTRAINT personas_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: profiles profiles_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: profiles profiles_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE SET NULL;


--
-- Name: recall_bots recall_bots_candidate_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recall_bots
    ADD CONSTRAINT recall_bots_candidate_round_id_fkey FOREIGN KEY (candidate_round_id) REFERENCES public.candidate_rounds(id);


--
-- Name: recall_bots recall_bots_detection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recall_bots
    ADD CONSTRAINT recall_bots_detection_id_fkey FOREIGN KEY (detection_id) REFERENCES public.calendar_event_detections(id);


--
-- Name: recall_bots recall_bots_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recall_bots
    ADD CONSTRAINT recall_bots_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id);


--
-- Name: requisitions requisitions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT requisitions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.profiles(id) ON DELETE SET NULL;


--
-- Name: requisitions requisitions_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT requisitions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: round_screening_configs round_screening_configs_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_screening_configs
    ADD CONSTRAINT round_screening_configs_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: round_screening_configs round_screening_configs_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_screening_configs
    ADD CONSTRAINT round_screening_configs_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.rounds(id) ON DELETE CASCADE;


--
-- Name: round_screening_questions round_screening_questions_round_screening_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_screening_questions
    ADD CONSTRAINT round_screening_questions_round_screening_config_id_fkey FOREIGN KEY (round_screening_config_id) REFERENCES public.round_screening_configs(id) ON DELETE CASCADE;


--
-- Name: rounds rounds_assessment_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rounds
    ADD CONSTRAINT rounds_assessment_template_id_fkey FOREIGN KEY (assessment_template_id) REFERENCES public.assessment_templates(id) ON DELETE SET NULL;


--
-- Name: rounds rounds_for_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rounds
    ADD CONSTRAINT rounds_for_candidate_id_fkey FOREIGN KEY (for_candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: rounds rounds_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rounds
    ADD CONSTRAINT rounds_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: screening_invites screening_invites_candidate_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_invites
    ADD CONSTRAINT screening_invites_candidate_round_id_fkey FOREIGN KEY (candidate_round_id) REFERENCES public.candidate_rounds(id) ON DELETE CASCADE;


--
-- Name: slack_connections slack_connections_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_connections
    ADD CONSTRAINT slack_connections_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: slack_connections slack_connections_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_connections
    ADD CONSTRAINT slack_connections_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id);


--
-- Name: slack_connections slack_connections_slack_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_connections
    ADD CONSTRAINT slack_connections_slack_team_id_fkey FOREIGN KEY (slack_team_id) REFERENCES public.slack_installations(slack_team_id);


--
-- Name: slack_installations slack_installations_installed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_installations
    ADD CONSTRAINT slack_installations_installed_by_fkey FOREIGN KEY (installed_by) REFERENCES public.profiles(id);


--
-- Name: subscriptions subscriptions_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: subscriptions subscriptions_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.plans(id);


--
-- Name: topup_credits topup_credits_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topup_credits
    ADD CONSTRAINT topup_credits_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: transcripts transcripts_candidate_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transcripts
    ADD CONSTRAINT transcripts_candidate_round_id_fkey FOREIGN KEY (candidate_round_id) REFERENCES public.candidate_rounds(id);


--
-- Name: untracked_interview_imports untracked_interview_imports_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.untracked_interview_imports
    ADD CONSTRAINT untracked_interview_imports_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: untracked_interview_imports untracked_interview_imports_target_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.untracked_interview_imports
    ADD CONSTRAINT untracked_interview_imports_target_requisition_id_fkey FOREIGN KEY (target_requisition_id) REFERENCES public.requisitions(id);


--
-- Name: untracked_interview_imports untracked_interview_imports_target_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.untracked_interview_imports
    ADD CONSTRAINT untracked_interview_imports_target_round_id_fkey FOREIGN KEY (target_round_id) REFERENCES public.rounds(id);


--
-- Name: usage_credits usage_credits_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_credits
    ADD CONSTRAINT usage_credits_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: user_connections user_connections_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_connections
    ADD CONSTRAINT user_connections_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: user_connections user_connections_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_connections
    ADD CONSTRAINT user_connections_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id);


--
-- Name: organization_invites Admin full access to invites; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admin full access to invites" ON public.organization_invites USING (public.is_admin());


--
-- Name: plans Admin full access to plans; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admin full access to plans" ON public.plans USING (public.is_admin()) WITH CHECK (public.is_admin());


--
-- Name: promotions Admin full access to promotions; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admin full access to promotions" ON public.promotions USING (public.is_admin()) WITH CHECK (public.is_admin());


--
-- Name: subscriptions Admin full access to subscriptions; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admin full access to subscriptions" ON public.subscriptions USING (public.is_admin()) WITH CHECK (public.is_admin());


--
-- Name: topup_credits Admin full access to topup_credits; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admin full access to topup_credits" ON public.topup_credits USING (public.is_admin()) WITH CHECK (public.is_admin());


--
-- Name: topup_products Admin full access to topup_products; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admin full access to topup_products" ON public.topup_products USING (public.is_admin()) WITH CHECK (public.is_admin());


--
-- Name: usage_credits Admin full access to usage_credits; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admin full access to usage_credits" ON public.usage_credits USING (public.is_admin()) WITH CHECK (public.is_admin());


--
-- Name: plans Anyone can read active plans; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Anyone can read active plans" ON public.plans FOR SELECT USING ((is_active = true));


--
-- Name: topup_products Anyone can read active topup products; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Anyone can read active topup products" ON public.topup_products FOR SELECT USING ((is_active = true));


--
-- Name: assessment_templates Anyone can view published templates; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Anyone can view published templates" ON public.assessment_templates FOR SELECT USING ((status = 'published'::text));


--
-- Name: assessment_templates Service role can manage all templates; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role can manage all templates" ON public.assessment_templates USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: calendar_event_detections Service role full access on detections; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access on detections" ON public.calendar_event_detections USING ((auth.role() = 'service_role'::text));


--
-- Name: calendar_intelligence_state Service role only on state; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role only on state" ON public.calendar_intelligence_state USING ((auth.role() = 'service_role'::text));


--
-- Name: usage_credits Users can view own org credits; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view own org credits" ON public.usage_credits FOR SELECT USING ((organization_id = ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE (profiles.id = auth.uid()))));


--
-- Name: organization_invites Users can view own org invites; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view own org invites" ON public.organization_invites FOR SELECT USING ((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE (profiles.id = auth.uid()))));


--
-- Name: subscriptions Users can view own org subscription; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view own org subscription" ON public.subscriptions FOR SELECT USING ((organization_id = ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE (profiles.id = auth.uid()))));


--
-- Name: topup_credits Users can view own org topup credits; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view own org topup credits" ON public.topup_credits FOR SELECT USING ((organization_id = ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE (profiles.id = auth.uid()))));


--
-- Name: calendar_event_detections Users see own detections; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users see own detections" ON public.calendar_event_detections FOR SELECT USING ((profile_id = auth.uid()));


--
-- Name: agent_conversations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.agent_conversations ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_conversations agent_conversations_service_only; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY agent_conversations_service_only ON public.agent_conversations USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: agent_pending_tasks; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.agent_pending_tasks ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_pending_tasks agent_pending_tasks_service_only; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY agent_pending_tasks_service_only ON public.agent_pending_tasks USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: assessment_evaluations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.assessment_evaluations ENABLE ROW LEVEL SECURITY;

--
-- Name: assessment_evaluations assessment_evaluations_service_only; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY assessment_evaluations_service_only ON public.assessment_evaluations USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: assessment_instances; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.assessment_instances ENABLE ROW LEVEL SECURITY;

--
-- Name: assessment_instances assessment_instances_service_only; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY assessment_instances_service_only ON public.assessment_instances USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: assessment_templates; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.assessment_templates ENABLE ROW LEVEL SECURITY;

--
-- Name: ats_connections; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.ats_connections ENABLE ROW LEVEL SECURITY;

--
-- Name: ats_entity_links; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.ats_entity_links ENABLE ROW LEVEL SECURITY;

--
-- Name: ats_interviews; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.ats_interviews ENABLE ROW LEVEL SECURITY;

--
-- Name: ats_stage_round_map; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.ats_stage_round_map ENABLE ROW LEVEL SECURITY;

--
-- Name: ats_webhook_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.ats_webhook_events ENABLE ROW LEVEL SECURITY;

--
-- Name: blog_posts; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.blog_posts ENABLE ROW LEVEL SECURITY;

--
-- Name: blog_posts blog_posts_service_manage; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY blog_posts_service_manage ON public.blog_posts USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: blog_posts blog_posts_view_published; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY blog_posts_view_published ON public.blog_posts FOR SELECT USING (((status = 'published'::text) OR (auth.role() = 'service_role'::text)));


--
-- Name: calendar_event_detections; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.calendar_event_detections ENABLE ROW LEVEL SECURITY;

--
-- Name: calendar_intelligence_state; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.calendar_intelligence_state ENABLE ROW LEVEL SECURITY;

--
-- Name: candidate_feedback; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.candidate_feedback ENABLE ROW LEVEL SECURITY;

--
-- Name: candidate_feedback candidate_feedback_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidate_feedback_delete_policy ON public.candidate_feedback FOR DELETE TO authenticated USING (( SELECT public.is_admin() AS is_admin));


--
-- Name: candidate_feedback candidate_feedback_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidate_feedback_insert_policy ON public.candidate_feedback FOR INSERT TO authenticated WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: candidate_feedback candidate_feedback_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidate_feedback_select_policy ON public.candidate_feedback FOR SELECT TO authenticated USING (((candidate_round_id IN ( SELECT cr.id
   FROM (((public.candidate_rounds cr
     JOIN public.candidates c ON ((c.id = cr.candidate_id)))
     JOIN public.requisitions r ON ((r.id = c.requisition_id)))
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL) AND (c.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: candidate_feedback candidate_feedback_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidate_feedback_update_policy ON public.candidate_feedback FOR UPDATE TO authenticated USING (( SELECT public.is_admin() AS is_admin)) WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: candidate_rounds; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.candidate_rounds ENABLE ROW LEVEL SECURITY;

--
-- Name: candidate_rounds candidate_rounds_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidate_rounds_delete_policy ON public.candidate_rounds FOR DELETE TO authenticated USING (( SELECT public.is_admin() AS is_admin));


--
-- Name: candidate_rounds candidate_rounds_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidate_rounds_insert_policy ON public.candidate_rounds FOR INSERT TO authenticated WITH CHECK (((candidate_id IN ( SELECT c.id
   FROM ((public.candidates c
     JOIN public.requisitions r ON ((r.id = c.requisition_id)))
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL) AND (c.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: candidate_rounds candidate_rounds_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidate_rounds_select_policy ON public.candidate_rounds FOR SELECT TO authenticated USING (((candidate_id IN ( SELECT c.id
   FROM ((public.candidates c
     JOIN public.requisitions r ON ((r.id = c.requisition_id)))
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL) AND (c.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: candidate_rounds candidate_rounds_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidate_rounds_update_policy ON public.candidate_rounds FOR UPDATE TO authenticated USING (((candidate_id IN ( SELECT c.id
   FROM ((public.candidates c
     JOIN public.requisitions r ON ((r.id = c.requisition_id)))
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL) AND (c.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin))) WITH CHECK (((candidate_id IN ( SELECT c.id
   FROM ((public.candidates c
     JOIN public.requisitions r ON ((r.id = c.requisition_id)))
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL) AND (c.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: candidates; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.candidates ENABLE ROW LEVEL SECURITY;

--
-- Name: candidates candidates_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidates_delete_policy ON public.candidates FOR DELETE TO authenticated USING (( SELECT public.is_admin() AS is_admin));


--
-- Name: candidates candidates_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidates_insert_policy ON public.candidates FOR INSERT TO authenticated WITH CHECK (((requisition_id IN ( SELECT r.id
   FROM (public.requisitions r
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: candidates candidates_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidates_select_policy ON public.candidates FOR SELECT TO authenticated USING (((requisition_id IN ( SELECT r.id
   FROM (public.requisitions r
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: candidates candidates_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY candidates_update_policy ON public.candidates FOR UPDATE TO authenticated USING (((requisition_id IN ( SELECT r.id
   FROM (public.requisitions r
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin))) WITH CHECK (((requisition_id IN ( SELECT r.id
   FROM (public.requisitions r
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: cortex_force_publish_jobs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.cortex_force_publish_jobs ENABLE ROW LEVEL SECURITY;

--
-- Name: cortex_org_ingest_jobs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.cortex_org_ingest_jobs ENABLE ROW LEVEL SECURITY;

--
-- Name: debrief_conversations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.debrief_conversations ENABLE ROW LEVEL SECURITY;

--
-- Name: debrief_insights; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.debrief_insights ENABLE ROW LEVEL SECURITY;

--
-- Name: debrief_packets; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.debrief_packets ENABLE ROW LEVEL SECURITY;

--
-- Name: feedback_access_tokens; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.feedback_access_tokens ENABLE ROW LEVEL SECURITY;

--
-- Name: feedback_questions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.feedback_questions ENABLE ROW LEVEL SECURITY;

--
-- Name: feedback_questions feedback_questions_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY feedback_questions_delete_policy ON public.feedback_questions FOR DELETE TO authenticated USING (( SELECT public.is_admin() AS is_admin));


--
-- Name: feedback_questions feedback_questions_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY feedback_questions_insert_policy ON public.feedback_questions FOR INSERT TO authenticated WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: feedback_questions feedback_questions_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY feedback_questions_select_policy ON public.feedback_questions FOR SELECT TO authenticated USING (((round_id IN ( SELECT rd.id
   FROM ((public.rounds rd
     JOIN public.requisitions r ON ((r.id = rd.requisition_id)))
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL) AND (rd.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: feedback_questions feedback_questions_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY feedback_questions_update_policy ON public.feedback_questions FOR UPDATE TO authenticated USING (( SELECT public.is_admin() AS is_admin)) WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: feedback_access_tokens feedback_tokens_service_only; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY feedback_tokens_service_only ON public.feedback_access_tokens USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: intake_sessions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.intake_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: intake_sessions intake_sessions_user_or_org; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY intake_sessions_user_or_org ON public.intake_sessions FOR SELECT USING (((user_id = auth.uid()) OR (organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE (profiles.id = auth.uid())))));


--
-- Name: intake_sessions intake_sessions_user_owns_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY intake_sessions_user_owns_insert ON public.intake_sessions FOR INSERT WITH CHECK ((user_id = auth.uid()));


--
-- Name: intake_sessions intake_sessions_user_owns_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY intake_sessions_user_owns_update ON public.intake_sessions FOR UPDATE USING ((user_id = auth.uid())) WITH CHECK ((user_id = auth.uid()));


--
-- Name: mcp_audit_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.mcp_audit_log ENABLE ROW LEVEL SECURITY;

--
-- Name: mcp_audit_log mcp_audit_log_deny_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY mcp_audit_log_deny_all ON public.mcp_audit_log TO authenticated, anon USING (false) WITH CHECK (false);


--
-- Name: oauth_authorization_codes; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.oauth_authorization_codes ENABLE ROW LEVEL SECURITY;

--
-- Name: oauth_authorization_codes oauth_authorization_codes_deny_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY oauth_authorization_codes_deny_all ON public.oauth_authorization_codes TO authenticated, anon USING (false) WITH CHECK (false);


--
-- Name: oauth_clients; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.oauth_clients ENABLE ROW LEVEL SECURITY;

--
-- Name: oauth_clients oauth_clients_deny_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY oauth_clients_deny_all ON public.oauth_clients TO authenticated, anon USING (false) WITH CHECK (false);


--
-- Name: oauth_refresh_tokens; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.oauth_refresh_tokens ENABLE ROW LEVEL SECURITY;

--
-- Name: oauth_refresh_tokens oauth_refresh_tokens_deny_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY oauth_refresh_tokens_deny_all ON public.oauth_refresh_tokens TO authenticated, anon USING (false) WITH CHECK (false);


--
-- Name: org_generic_template_bindings; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.org_generic_template_bindings ENABLE ROW LEVEL SECURITY;

--
-- Name: org_generic_template_bindings org_generic_template_bindings_service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY org_generic_template_bindings_service_role_all ON public.org_generic_template_bindings USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: ats_connections org_users_select_ats_connections; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY org_users_select_ats_connections ON public.ats_connections FOR SELECT TO authenticated USING ((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = auth.uid()) AND (profiles.deleted_at IS NULL)))));


--
-- Name: ats_entity_links org_users_select_ats_entity_links; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY org_users_select_ats_entity_links ON public.ats_entity_links FOR SELECT TO authenticated USING ((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = auth.uid()) AND (profiles.deleted_at IS NULL)))));


--
-- Name: ats_interviews org_users_select_ats_interviews; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY org_users_select_ats_interviews ON public.ats_interviews FOR SELECT TO authenticated USING ((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = auth.uid()) AND (profiles.deleted_at IS NULL)))));


--
-- Name: ats_stage_round_map org_users_select_ats_stage_round_map; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY org_users_select_ats_stage_round_map ON public.ats_stage_round_map FOR SELECT TO authenticated USING ((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = auth.uid()) AND (profiles.deleted_at IS NULL)))));


--
-- Name: debrief_conversations org_users_select_debrief_conversations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY org_users_select_debrief_conversations ON public.debrief_conversations FOR SELECT TO authenticated USING ((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE (profiles.id = auth.uid()))));


--
-- Name: debrief_insights org_users_select_debrief_insights; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY org_users_select_debrief_insights ON public.debrief_insights FOR SELECT TO authenticated USING ((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE (profiles.id = auth.uid()))));


--
-- Name: debrief_packets org_users_select_debrief_packets; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY org_users_select_debrief_packets ON public.debrief_packets FOR SELECT TO authenticated USING ((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = auth.uid()) AND (profiles.deleted_at IS NULL)))));


--
-- Name: organization_invites; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.organization_invites ENABLE ROW LEVEL SECURITY;

--
-- Name: organizations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;

--
-- Name: organizations organizations_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY organizations_delete_policy ON public.organizations FOR DELETE TO authenticated USING (( SELECT public.is_admin() AS is_admin));


--
-- Name: organizations organizations_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY organizations_insert_policy ON public.organizations FOR INSERT TO authenticated WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: organizations organizations_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY organizations_select_policy ON public.organizations FOR SELECT TO authenticated USING (((id = ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE (profiles.id = ( SELECT auth.uid() AS uid)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: organizations organizations_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY organizations_update_policy ON public.organizations FOR UPDATE TO authenticated USING (( SELECT public.is_admin() AS is_admin)) WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: personas; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.personas ENABLE ROW LEVEL SECURITY;

--
-- Name: plans; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;

--
-- Name: profiles; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: profiles profiles_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY profiles_delete_policy ON public.profiles FOR DELETE TO authenticated USING (( SELECT public.is_admin() AS is_admin));


--
-- Name: profiles profiles_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY profiles_insert_policy ON public.profiles FOR INSERT TO authenticated WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: profiles profiles_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY profiles_select_policy ON public.profiles FOR SELECT TO authenticated USING (((id = ( SELECT auth.uid() AS uid)) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: profiles profiles_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY profiles_update_policy ON public.profiles FOR UPDATE TO authenticated USING (((id = ( SELECT auth.uid() AS uid)) OR ( SELECT public.is_admin() AS is_admin))) WITH CHECK (((id = ( SELECT auth.uid() AS uid)) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: promotions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.promotions ENABLE ROW LEVEL SECURITY;

--
-- Name: recall_bots; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.recall_bots ENABLE ROW LEVEL SECURITY;

--
-- Name: recall_bots recall_bots_delete_service; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY recall_bots_delete_service ON public.recall_bots FOR DELETE USING (((( SELECT auth.jwt() AS jwt) ->> 'role'::text) = 'service_role'::text));


--
-- Name: recall_bots recall_bots_insert_service; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY recall_bots_insert_service ON public.recall_bots FOR INSERT WITH CHECK (((( SELECT auth.jwt() AS jwt) ->> 'role'::text) = 'service_role'::text));


--
-- Name: recall_bots recall_bots_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY recall_bots_select_policy ON public.recall_bots FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM (((public.candidate_rounds cr
     JOIN public.candidates c ON ((cr.candidate_id = c.id)))
     JOIN public.requisitions r ON ((c.requisition_id = r.id)))
     JOIN public.profiles p ON ((r.organization_id = p.organization_id)))
  WHERE ((cr.id = recall_bots.candidate_round_id) AND (p.id = ( SELECT auth.uid() AS uid))))));


--
-- Name: recall_bots recall_bots_update_service; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY recall_bots_update_service ON public.recall_bots FOR UPDATE USING (((( SELECT auth.jwt() AS jwt) ->> 'role'::text) = 'service_role'::text)) WITH CHECK (((( SELECT auth.jwt() AS jwt) ->> 'role'::text) = 'service_role'::text));


--
-- Name: requisitions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.requisitions ENABLE ROW LEVEL SECURITY;

--
-- Name: requisitions requisitions_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY requisitions_delete_policy ON public.requisitions FOR DELETE TO authenticated USING (( SELECT public.is_admin() AS is_admin));


--
-- Name: requisitions requisitions_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY requisitions_insert_policy ON public.requisitions FOR INSERT TO authenticated WITH CHECK (((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = ( SELECT auth.uid() AS uid)) AND (profiles.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: requisitions requisitions_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY requisitions_select_policy ON public.requisitions FOR SELECT TO authenticated USING (((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = ( SELECT auth.uid() AS uid)) AND (profiles.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: requisitions requisitions_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY requisitions_update_policy ON public.requisitions FOR UPDATE TO authenticated USING (((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = ( SELECT auth.uid() AS uid)) AND (profiles.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin))) WITH CHECK (((organization_id IN ( SELECT profiles.organization_id
   FROM public.profiles
  WHERE ((profiles.id = ( SELECT auth.uid() AS uid)) AND (profiles.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: round_screening_configs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.round_screening_configs ENABLE ROW LEVEL SECURITY;

--
-- Name: round_screening_questions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.round_screening_questions ENABLE ROW LEVEL SECURITY;

--
-- Name: rounds; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.rounds ENABLE ROW LEVEL SECURITY;

--
-- Name: rounds rounds_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY rounds_delete_policy ON public.rounds FOR DELETE TO authenticated USING (( SELECT public.is_admin() AS is_admin));


--
-- Name: rounds rounds_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY rounds_insert_policy ON public.rounds FOR INSERT TO authenticated WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: rounds rounds_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY rounds_select_policy ON public.rounds FOR SELECT TO authenticated USING (((requisition_id IN ( SELECT r.id
   FROM (public.requisitions r
     JOIN public.profiles p ON ((p.organization_id = r.organization_id)))
  WHERE ((p.id = ( SELECT auth.uid() AS uid)) AND (p.deleted_at IS NULL) AND (r.deleted_at IS NULL)))) OR ( SELECT public.is_admin() AS is_admin)));


--
-- Name: rounds rounds_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY rounds_update_policy ON public.rounds FOR UPDATE TO authenticated USING (( SELECT public.is_admin() AS is_admin)) WITH CHECK (( SELECT public.is_admin() AS is_admin));


--
-- Name: screening_invites; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.screening_invites ENABLE ROW LEVEL SECURITY;

--
-- Name: slack_connections; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.slack_connections ENABLE ROW LEVEL SECURITY;

--
-- Name: slack_connections slack_connections_service_only; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY slack_connections_service_only ON public.slack_connections USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: slack_installations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.slack_installations ENABLE ROW LEVEL SECURITY;

--
-- Name: slack_installations slack_installations_service_only; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY slack_installations_service_only ON public.slack_installations USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: subscriptions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

--
-- Name: topup_credits; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.topup_credits ENABLE ROW LEVEL SECURITY;

--
-- Name: topup_products; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.topup_products ENABLE ROW LEVEL SECURITY;

--
-- Name: transcripts; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.transcripts ENABLE ROW LEVEL SECURITY;

--
-- Name: transcripts transcripts_delete_service; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY transcripts_delete_service ON public.transcripts FOR DELETE USING (((( SELECT auth.jwt() AS jwt) ->> 'role'::text) = 'service_role'::text));


--
-- Name: transcripts transcripts_insert_service; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY transcripts_insert_service ON public.transcripts FOR INSERT WITH CHECK (((( SELECT auth.jwt() AS jwt) ->> 'role'::text) = 'service_role'::text));


--
-- Name: transcripts transcripts_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY transcripts_select_policy ON public.transcripts FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM (((public.candidate_rounds cr
     JOIN public.candidates c ON ((cr.candidate_id = c.id)))
     JOIN public.requisitions r ON ((c.requisition_id = r.id)))
     JOIN public.profiles p ON ((r.organization_id = p.organization_id)))
  WHERE ((cr.id = transcripts.candidate_round_id) AND (p.id = ( SELECT auth.uid() AS uid))))));


--
-- Name: transcripts transcripts_update_service; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY transcripts_update_service ON public.transcripts FOR UPDATE USING (((( SELECT auth.jwt() AS jwt) ->> 'role'::text) = 'service_role'::text)) WITH CHECK (((( SELECT auth.jwt() AS jwt) ->> 'role'::text) = 'service_role'::text));


--
-- Name: untracked_interview_imports; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.untracked_interview_imports ENABLE ROW LEVEL SECURITY;

--
-- Name: untracked_interview_imports untracked_interview_imports_org_users_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY untracked_interview_imports_org_users_select ON public.untracked_interview_imports FOR SELECT TO authenticated USING ((organization_id IN ( SELECT p.organization_id
   FROM public.profiles p
  WHERE ((p.id = auth.uid()) AND (p.deleted_at IS NULL)))));


--
-- Name: untracked_interview_imports untracked_interview_imports_service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY untracked_interview_imports_service_role_all ON public.untracked_interview_imports USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: usage_credits; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.usage_credits ENABLE ROW LEVEL SECURITY;

--
-- Name: user_connections; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_connections ENABLE ROW LEVEL SECURITY;

--
-- Name: user_connections user_connections_delete_own; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_connections_delete_own ON public.user_connections FOR DELETE USING ((profile_id = ( SELECT auth.uid() AS uid)));


--
-- Name: user_connections user_connections_insert_own; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_connections_insert_own ON public.user_connections FOR INSERT WITH CHECK ((profile_id = ( SELECT auth.uid() AS uid)));


--
-- Name: user_connections user_connections_select_own; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_connections_select_own ON public.user_connections FOR SELECT USING ((profile_id = ( SELECT auth.uid() AS uid)));


--
-- Name: user_connections user_connections_service_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_connections_service_all ON public.user_connections USING ((auth.role() = 'service_role'::text)) WITH CHECK ((auth.role() = 'service_role'::text));


--
-- Name: user_connections user_connections_update_own; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_connections_update_own ON public.user_connections FOR UPDATE USING ((profile_id = ( SELECT auth.uid() AS uid))) WITH CHECK ((profile_id = ( SELECT auth.uid() AS uid)));


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO anon;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT ALL ON SCHEMA public TO service_role;


--
-- Name: FUNCTION add_candidate_with_backfill(p_req_id uuid, p_name text, p_email text, p_phone text, p_resume_url text, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.add_candidate_with_backfill(p_req_id uuid, p_name text, p_email text, p_phone text, p_resume_url text, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.add_candidate_with_backfill(p_req_id uuid, p_name text, p_email text, p_phone text, p_resume_url text, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.add_candidate_with_backfill(p_req_id uuid, p_name text, p_email text, p_phone text, p_resume_url text, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION add_custom_round(p_req_id uuid, p_candidate_id uuid, p_name text, p_category text, p_duration_minutes integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.add_custom_round(p_req_id uuid, p_candidate_id uuid, p_name text, p_category text, p_duration_minutes integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.add_custom_round(p_req_id uuid, p_candidate_id uuid, p_name text, p_category text, p_duration_minutes integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.add_custom_round(p_req_id uuid, p_candidate_id uuid, p_name text, p_category text, p_duration_minutes integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION add_shared_round(p_req_id uuid, p_name text, p_category text, p_duration_minutes integer, p_position integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.add_shared_round(p_req_id uuid, p_name text, p_category text, p_duration_minutes integer, p_position integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.add_shared_round(p_req_id uuid, p_name text, p_category text, p_duration_minutes integer, p_position integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.add_shared_round(p_req_id uuid, p_name text, p_category text, p_duration_minutes integer, p_position integer, p_description text, p_skills jsonb, p_guidelines jsonb, p_feedback_questions jsonb, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION admin_archive_organization(p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.admin_archive_organization(p_org_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.admin_archive_organization(p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.admin_archive_organization(p_org_id uuid) TO service_role;


--
-- Name: FUNCTION admin_restore_organization(p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.admin_restore_organization(p_org_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.admin_restore_organization(p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.admin_restore_organization(p_org_id uuid) TO service_role;


--
-- Name: FUNCTION admin_set_structured_feedback(p_cr_id uuid, p_summary text, p_rating text, p_source text, p_feedback jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.admin_set_structured_feedback(p_cr_id uuid, p_summary text, p_rating text, p_source text, p_feedback jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.admin_set_structured_feedback(p_cr_id uuid, p_summary text, p_rating text, p_source text, p_feedback jsonb) TO anon;
GRANT ALL ON FUNCTION public.admin_set_structured_feedback(p_cr_id uuid, p_summary text, p_rating text, p_source text, p_feedback jsonb) TO service_role;


--
-- Name: FUNCTION admin_submit_candidate_feedback(p_cr_id uuid, p_source text, p_feedback jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.admin_submit_candidate_feedback(p_cr_id uuid, p_source text, p_feedback jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.admin_submit_candidate_feedback(p_cr_id uuid, p_source text, p_feedback jsonb) TO anon;
GRANT ALL ON FUNCTION public.admin_submit_candidate_feedback(p_cr_id uuid, p_source text, p_feedback jsonb) TO service_role;


--
-- Name: FUNCTION ats_apply_dirty_update(p_org_id uuid, p_requisition_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_apply_dirty_update(p_org_id uuid, p_requisition_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_apply_dirty_update(p_org_id uuid, p_requisition_id uuid) TO anon;
GRANT ALL ON FUNCTION public.ats_apply_dirty_update(p_org_id uuid, p_requisition_id uuid) TO service_role;


--
-- Name: FUNCTION ats_connect(p_org_id uuid, p_provider text, p_integration_id text, p_user_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_connect(p_org_id uuid, p_provider text, p_integration_id text, p_user_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_connect(p_org_id uuid, p_provider text, p_integration_id text, p_user_id uuid) TO anon;
GRANT ALL ON FUNCTION public.ats_connect(p_org_id uuid, p_provider text, p_integration_id text, p_user_id uuid) TO service_role;


--
-- Name: FUNCTION ats_enrich_candidate(p_candidate_id uuid, p_org_id uuid, p_profile jsonb, p_resume_url text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_enrich_candidate(p_candidate_id uuid, p_org_id uuid, p_profile jsonb, p_resume_url text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_enrich_candidate(p_candidate_id uuid, p_org_id uuid, p_profile jsonb, p_resume_url text) TO anon;
GRANT ALL ON FUNCTION public.ats_enrich_candidate(p_candidate_id uuid, p_org_id uuid, p_profile jsonb, p_resume_url text) TO service_role;


--
-- Name: FUNCTION ats_import_job(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_job_id text, p_fields jsonb, p_ats_status text, p_user_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_import_job(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_job_id text, p_fields jsonb, p_ats_status text, p_user_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_import_job(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_job_id text, p_fields jsonb, p_ats_status text, p_user_id uuid) TO anon;
GRANT ALL ON FUNCTION public.ats_import_job(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_job_id text, p_fields jsonb, p_ats_status text, p_user_id uuid) TO service_role;


--
-- Name: FUNCTION ats_mark_deleted(p_org_id uuid, p_ats_type text, p_ats_id text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_mark_deleted(p_org_id uuid, p_ats_type text, p_ats_id text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_mark_deleted(p_org_id uuid, p_ats_type text, p_ats_id text) TO anon;
GRANT ALL ON FUNCTION public.ats_mark_deleted(p_org_id uuid, p_ats_type text, p_ats_id text) TO service_role;


--
-- Name: FUNCTION ats_promote_interviews(p_requisition_id uuid, p_org uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_promote_interviews(p_requisition_id uuid, p_org uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_promote_interviews(p_requisition_id uuid, p_org uuid) TO anon;
GRANT ALL ON FUNCTION public.ats_promote_interviews(p_requisition_id uuid, p_org uuid) TO service_role;


--
-- Name: FUNCTION ats_upsert_candidate(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_application_id text, p_ats_candidate_id text, p_fields jsonb, p_ats_status text, p_stage_id text, p_stage_name text, p_profile jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_upsert_candidate(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_application_id text, p_ats_candidate_id text, p_fields jsonb, p_ats_status text, p_stage_id text, p_stage_name text, p_profile jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_upsert_candidate(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_application_id text, p_ats_candidate_id text, p_fields jsonb, p_ats_status text, p_stage_id text, p_stage_name text, p_profile jsonb) TO anon;
GRANT ALL ON FUNCTION public.ats_upsert_candidate(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_application_id text, p_ats_candidate_id text, p_fields jsonb, p_ats_status text, p_stage_id text, p_stage_name text, p_profile jsonb) TO service_role;


--
-- Name: FUNCTION ats_upsert_interview(p_org uuid, p_connection uuid, p_fields jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_upsert_interview(p_org uuid, p_connection uuid, p_fields jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_upsert_interview(p_org uuid, p_connection uuid, p_fields jsonb) TO anon;
GRANT ALL ON FUNCTION public.ats_upsert_interview(p_org uuid, p_connection uuid, p_fields jsonb) TO service_role;


--
-- Name: FUNCTION ats_upsert_stage_round_map(p_org_id uuid, p_requisition_id uuid, p_round_id uuid, p_ats_stage_id text, p_ats_stage_name text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.ats_upsert_stage_round_map(p_org_id uuid, p_requisition_id uuid, p_round_id uuid, p_ats_stage_id text, p_ats_stage_name text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ats_upsert_stage_round_map(p_org_id uuid, p_requisition_id uuid, p_round_id uuid, p_ats_stage_id text, p_ats_stage_name text) TO anon;
GRANT ALL ON FUNCTION public.ats_upsert_stage_round_map(p_org_id uuid, p_requisition_id uuid, p_round_id uuid, p_ats_stage_id text, p_ats_stage_name text) TO service_role;


--
-- Name: FUNCTION cancel_candidate_round(p_cr_id uuid, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cancel_candidate_round(p_cr_id uuid, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.cancel_candidate_round(p_cr_id uuid, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.cancel_candidate_round(p_cr_id uuid, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION claim_feedback_processing(p_cr_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.claim_feedback_processing(p_cr_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.claim_feedback_processing(p_cr_id uuid) TO anon;
GRANT ALL ON FUNCTION public.claim_feedback_processing(p_cr_id uuid) TO service_role;


--
-- Name: FUNCTION claim_intake_processing(p_requisition_id uuid, p_stale_seconds integer); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.claim_intake_processing(p_requisition_id uuid, p_stale_seconds integer) TO anon;
GRANT ALL ON FUNCTION public.claim_intake_processing(p_requisition_id uuid, p_stale_seconds integer) TO authenticated;
GRANT ALL ON FUNCTION public.claim_intake_processing(p_requisition_id uuid, p_stale_seconds integer) TO service_role;


--
-- Name: FUNCTION cortex_backfill_org_event(event_type text, org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_backfill_org_event(event_type text, org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.cortex_backfill_org_event(event_type text, org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.cortex_backfill_org_event(event_type text, org_id uuid) TO service_role;


--
-- Name: FUNCTION cortex_emit_candidate_event(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_emit_candidate_event() TO anon;
GRANT ALL ON FUNCTION public.cortex_emit_candidate_event() TO authenticated;
GRANT ALL ON FUNCTION public.cortex_emit_candidate_event() TO service_role;


--
-- Name: FUNCTION cortex_emit_candidate_feedback_event(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_emit_candidate_feedback_event() TO anon;
GRANT ALL ON FUNCTION public.cortex_emit_candidate_feedback_event() TO authenticated;
GRANT ALL ON FUNCTION public.cortex_emit_candidate_feedback_event() TO service_role;


--
-- Name: FUNCTION cortex_emit_candidate_round_event(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_emit_candidate_round_event() TO anon;
GRANT ALL ON FUNCTION public.cortex_emit_candidate_round_event() TO authenticated;
GRANT ALL ON FUNCTION public.cortex_emit_candidate_round_event() TO service_role;


--
-- Name: FUNCTION cortex_emit_requisition_event(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_emit_requisition_event() TO anon;
GRANT ALL ON FUNCTION public.cortex_emit_requisition_event() TO authenticated;
GRANT ALL ON FUNCTION public.cortex_emit_requisition_event() TO service_role;


--
-- Name: FUNCTION cortex_emit_round_event(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_emit_round_event() TO anon;
GRANT ALL ON FUNCTION public.cortex_emit_round_event() TO authenticated;
GRANT ALL ON FUNCTION public.cortex_emit_round_event() TO service_role;


--
-- Name: FUNCTION cortex_emit_transcript_event(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_emit_transcript_event() TO anon;
GRANT ALL ON FUNCTION public.cortex_emit_transcript_event() TO authenticated;
GRANT ALL ON FUNCTION public.cortex_emit_transcript_event() TO service_role;


--
-- Name: FUNCTION cortex_events_for_org_unpublished(p_org_id uuid, p_limit integer); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_events_for_org_unpublished(p_org_id uuid, p_limit integer) TO anon;
GRANT ALL ON FUNCTION public.cortex_events_for_org_unpublished(p_org_id uuid, p_limit integer) TO authenticated;
GRANT ALL ON FUNCTION public.cortex_events_for_org_unpublished(p_org_id uuid, p_limit integer) TO service_role;


--
-- Name: FUNCTION cortex_events_settled(cutoff timestamp with time zone, "limit" integer); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.cortex_events_settled(cutoff timestamp with time zone, "limit" integer) TO anon;
GRANT ALL ON FUNCTION public.cortex_events_settled(cutoff timestamp with time zone, "limit" integer) TO authenticated;
GRANT ALL ON FUNCTION public.cortex_events_settled(cutoff timestamp with time zone, "limit" integer) TO service_role;


--
-- Name: FUNCTION debrief_commit_draft(p_packet_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.debrief_commit_draft(p_packet_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.debrief_commit_draft(p_packet_id uuid) TO service_role;


--
-- Name: FUNCTION debrief_conversation_append_turn(p_packet_id uuid, p_turn jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.debrief_conversation_append_turn(p_packet_id uuid, p_turn jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.debrief_conversation_append_turn(p_packet_id uuid, p_turn jsonb) TO service_role;


--
-- Name: FUNCTION debrief_supersede_and_insert(p jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.debrief_supersede_and_insert(p jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.debrief_supersede_and_insert(p jsonb) TO service_role;


--
-- Name: FUNCTION delete_candidate_round(p_req_id uuid, p_candidate_id uuid, p_cr_id uuid, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.delete_candidate_round(p_req_id uuid, p_candidate_id uuid, p_cr_id uuid, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.delete_candidate_round(p_req_id uuid, p_candidate_id uuid, p_cr_id uuid, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.delete_candidate_round(p_req_id uuid, p_candidate_id uuid, p_cr_id uuid, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION delete_shared_round(p_round_id uuid, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.delete_shared_round(p_round_id uuid, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.delete_shared_round(p_round_id uuid, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.delete_shared_round(p_round_id uuid, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION execute_readonly_query(query_text text); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.execute_readonly_query(query_text text) TO service_role;


--
-- Name: FUNCTION get_candidate_packet(p_candidate_id uuid, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.get_candidate_packet(p_candidate_id uuid, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.get_candidate_packet(p_candidate_id uuid, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.get_candidate_packet(p_candidate_id uuid, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION get_dashboard_summary(p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.get_dashboard_summary(p_org_id uuid) TO service_role;


--
-- Name: FUNCTION get_role_pipeline(p_req_id uuid, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.get_role_pipeline(p_req_id uuid, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.get_role_pipeline(p_req_id uuid, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.get_role_pipeline(p_req_id uuid, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION increment_blog_likes(post_slug text); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.increment_blog_likes(post_slug text) TO anon;
GRANT ALL ON FUNCTION public.increment_blog_likes(post_slug text) TO authenticated;
GRANT ALL ON FUNCTION public.increment_blog_likes(post_slug text) TO service_role;


--
-- Name: FUNCTION intake_session_heartbeat(p_session_id uuid, p_user_id uuid, p_paused boolean); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.intake_session_heartbeat(p_session_id uuid, p_user_id uuid, p_paused boolean) FROM PUBLIC;
GRANT ALL ON FUNCTION public.intake_session_heartbeat(p_session_id uuid, p_user_id uuid, p_paused boolean) TO anon;
GRANT ALL ON FUNCTION public.intake_session_heartbeat(p_session_id uuid, p_user_id uuid, p_paused boolean) TO authenticated;
GRANT ALL ON FUNCTION public.intake_session_heartbeat(p_session_id uuid, p_user_id uuid, p_paused boolean) TO service_role;


--
-- Name: FUNCTION intake_sessions_append_turn(p_session_id uuid, p_turn jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.intake_sessions_append_turn(p_session_id uuid, p_turn jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.intake_sessions_append_turn(p_session_id uuid, p_turn jsonb) TO anon;
GRANT ALL ON FUNCTION public.intake_sessions_append_turn(p_session_id uuid, p_turn jsonb) TO service_role;


--
-- Name: FUNCTION intake_sessions_merge_answers(p_session_id uuid, p_patch jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.intake_sessions_merge_answers(p_session_id uuid, p_patch jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.intake_sessions_merge_answers(p_session_id uuid, p_patch jsonb) TO anon;
GRANT ALL ON FUNCTION public.intake_sessions_merge_answers(p_session_id uuid, p_patch jsonb) TO service_role;


--
-- Name: FUNCTION intake_sessions_set_stage(p_session_id uuid, p_stage_name text, p_status text, p_output jsonb, p_error text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.intake_sessions_set_stage(p_session_id uuid, p_stage_name text, p_status text, p_output jsonb, p_error text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.intake_sessions_set_stage(p_session_id uuid, p_stage_name text, p_status text, p_output jsonb, p_error text) TO anon;
GRANT ALL ON FUNCTION public.intake_sessions_set_stage(p_session_id uuid, p_stage_name text, p_status text, p_output jsonb, p_error text) TO service_role;


--
-- Name: FUNCTION is_admin(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.is_admin() TO anon;
GRANT ALL ON FUNCTION public.is_admin() TO authenticated;
GRANT ALL ON FUNCTION public.is_admin() TO service_role;


--
-- Name: FUNCTION release_stale_intake_modality_locks(p_stale_minutes integer); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.release_stale_intake_modality_locks(p_stale_minutes integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.release_stale_intake_modality_locks(p_stale_minutes integer) TO anon;
GRANT ALL ON FUNCTION public.release_stale_intake_modality_locks(p_stale_minutes integer) TO authenticated;
GRANT ALL ON FUNCTION public.release_stale_intake_modality_locks(p_stale_minutes integer) TO service_role;


--
-- Name: FUNCTION reorder_requisition_rounds(p_requisition_id uuid, p_ordered_round_ids uuid[]); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.reorder_requisition_rounds(p_requisition_id uuid, p_ordered_round_ids uuid[]) FROM PUBLIC;
GRANT ALL ON FUNCTION public.reorder_requisition_rounds(p_requisition_id uuid, p_ordered_round_ids uuid[]) TO anon;
GRANT ALL ON FUNCTION public.reorder_requisition_rounds(p_requisition_id uuid, p_ordered_round_ids uuid[]) TO service_role;


--
-- Name: FUNCTION reorder_shared_rounds(p_req_id uuid, p_order jsonb, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.reorder_shared_rounds(p_req_id uuid, p_order jsonb, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.reorder_shared_rounds(p_req_id uuid, p_order jsonb, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.reorder_shared_rounds(p_req_id uuid, p_order jsonb, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION reschedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text, p_meeting_url text, p_clear_meeting_url boolean, p_org_id uuid, p_scheduling_timezone text); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.reschedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text, p_meeting_url text, p_clear_meeting_url boolean, p_org_id uuid, p_scheduling_timezone text) TO anon;
GRANT ALL ON FUNCTION public.reschedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text, p_meeting_url text, p_clear_meeting_url boolean, p_org_id uuid, p_scheduling_timezone text) TO authenticated;
GRANT ALL ON FUNCTION public.reschedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text, p_meeting_url text, p_clear_meeting_url boolean, p_org_id uuid, p_scheduling_timezone text) TO service_role;


--
-- Name: FUNCTION schedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text, p_meeting_url text, p_duration_minutes integer, p_assessment_instance jsonb, p_org_id uuid, p_scheduling_timezone text); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.schedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text, p_meeting_url text, p_duration_minutes integer, p_assessment_instance jsonb, p_org_id uuid, p_scheduling_timezone text) TO anon;
GRANT ALL ON FUNCTION public.schedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text, p_meeting_url text, p_duration_minutes integer, p_assessment_instance jsonb, p_org_id uuid, p_scheduling_timezone text) TO authenticated;
GRANT ALL ON FUNCTION public.schedule_candidate_round(p_cr_id uuid, p_scheduled_at timestamp with time zone, p_interviewer_email text, p_interviewer_name text, p_meeting_url text, p_duration_minutes integer, p_assessment_instance jsonb, p_org_id uuid, p_scheduling_timezone text) TO service_role;


--
-- Name: FUNCTION screening_create_invite(p jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.screening_create_invite(p jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.screening_create_invite(p jsonb) TO anon;
GRANT ALL ON FUNCTION public.screening_create_invite(p jsonb) TO service_role;


--
-- Name: FUNCTION screening_invite_existing(p jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.screening_invite_existing(p jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.screening_invite_existing(p jsonb) TO anon;
GRANT ALL ON FUNCTION public.screening_invite_existing(p jsonb) TO service_role;


--
-- Name: FUNCTION screening_save_config(p jsonb); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.screening_save_config(p jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.screening_save_config(p jsonb) TO anon;
GRANT ALL ON FUNCTION public.screening_save_config(p jsonb) TO service_role;


--
-- Name: FUNCTION set_active_modality(p_session_id uuid, p_modality text, p_user_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.set_active_modality(p_session_id uuid, p_modality text, p_user_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.set_active_modality(p_session_id uuid, p_modality text, p_user_id uuid) TO anon;
GRANT ALL ON FUNCTION public.set_active_modality(p_session_id uuid, p_modality text, p_user_id uuid) TO service_role;


--
-- Name: FUNCTION submit_human_feedback(p_cr_id uuid, p_entries jsonb, p_rating text, p_summary text, p_org_id uuid); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.submit_human_feedback(p_cr_id uuid, p_entries jsonb, p_rating text, p_summary text, p_org_id uuid) TO anon;
GRANT ALL ON FUNCTION public.submit_human_feedback(p_cr_id uuid, p_entries jsonb, p_rating text, p_summary text, p_org_id uuid) TO authenticated;
GRANT ALL ON FUNCTION public.submit_human_feedback(p_cr_id uuid, p_entries jsonb, p_rating text, p_summary text, p_org_id uuid) TO service_role;


--
-- Name: FUNCTION sync_profile_invitation_status(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.sync_profile_invitation_status() TO anon;
GRANT ALL ON FUNCTION public.sync_profile_invitation_status() TO authenticated;
GRANT ALL ON FUNCTION public.sync_profile_invitation_status() TO service_role;


--
-- Name: FUNCTION undo_untracked_link(p_org_id uuid, p_source_cr_id uuid); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.undo_untracked_link(p_org_id uuid, p_source_cr_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.undo_untracked_link(p_org_id uuid, p_source_cr_id uuid) TO anon;
GRANT ALL ON FUNCTION public.undo_untracked_link(p_org_id uuid, p_source_cr_id uuid) TO service_role;


--
-- Name: FUNCTION update_assessment_evaluations_updated_at(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.update_assessment_evaluations_updated_at() TO anon;
GRANT ALL ON FUNCTION public.update_assessment_evaluations_updated_at() TO authenticated;
GRANT ALL ON FUNCTION public.update_assessment_evaluations_updated_at() TO service_role;


--
-- Name: FUNCTION update_assessment_instances_updated_at(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.update_assessment_instances_updated_at() TO anon;
GRANT ALL ON FUNCTION public.update_assessment_instances_updated_at() TO authenticated;
GRANT ALL ON FUNCTION public.update_assessment_instances_updated_at() TO service_role;


--
-- Name: FUNCTION update_assessment_templates_updated_at(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.update_assessment_templates_updated_at() TO anon;
GRANT ALL ON FUNCTION public.update_assessment_templates_updated_at() TO authenticated;
GRANT ALL ON FUNCTION public.update_assessment_templates_updated_at() TO service_role;


--
-- Name: FUNCTION update_updated_at_column(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.update_updated_at_column() TO anon;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO authenticated;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO service_role;


--
-- Name: FUNCTION use_credit_atomic(p_org_id uuid, p_credit_type text); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.use_credit_atomic(p_org_id uuid, p_credit_type text) TO anon;
GRANT ALL ON FUNCTION public.use_credit_atomic(p_org_id uuid, p_credit_type text) TO authenticated;
GRANT ALL ON FUNCTION public.use_credit_atomic(p_org_id uuid, p_credit_type text) TO service_role;


--
-- Name: TABLE agent_conversations; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.agent_conversations TO anon;
GRANT ALL ON TABLE public.agent_conversations TO authenticated;
GRANT ALL ON TABLE public.agent_conversations TO service_role;


--
-- Name: TABLE agent_memories; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.agent_memories TO anon;
GRANT ALL ON TABLE public.agent_memories TO authenticated;
GRANT ALL ON TABLE public.agent_memories TO service_role;


--
-- Name: TABLE agent_pending_tasks; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.agent_pending_tasks TO anon;
GRANT ALL ON TABLE public.agent_pending_tasks TO authenticated;
GRANT ALL ON TABLE public.agent_pending_tasks TO service_role;


--
-- Name: TABLE assessment_evaluations; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.assessment_evaluations TO anon;
GRANT ALL ON TABLE public.assessment_evaluations TO authenticated;
GRANT ALL ON TABLE public.assessment_evaluations TO service_role;


--
-- Name: TABLE assessment_instances; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.assessment_instances TO anon;
GRANT ALL ON TABLE public.assessment_instances TO authenticated;
GRANT ALL ON TABLE public.assessment_instances TO service_role;


--
-- Name: TABLE assessment_templates; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.assessment_templates TO anon;
GRANT ALL ON TABLE public.assessment_templates TO authenticated;
GRANT ALL ON TABLE public.assessment_templates TO service_role;


--
-- Name: TABLE ats_connections; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.ats_connections TO anon;
GRANT ALL ON TABLE public.ats_connections TO authenticated;
GRANT ALL ON TABLE public.ats_connections TO service_role;


--
-- Name: TABLE ats_entity_links; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.ats_entity_links TO anon;
GRANT ALL ON TABLE public.ats_entity_links TO authenticated;
GRANT ALL ON TABLE public.ats_entity_links TO service_role;


--
-- Name: TABLE ats_interviews; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.ats_interviews TO anon;
GRANT ALL ON TABLE public.ats_interviews TO authenticated;
GRANT ALL ON TABLE public.ats_interviews TO service_role;


--
-- Name: TABLE ats_stage_round_map; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.ats_stage_round_map TO anon;
GRANT ALL ON TABLE public.ats_stage_round_map TO authenticated;
GRANT ALL ON TABLE public.ats_stage_round_map TO service_role;


--
-- Name: TABLE ats_webhook_events; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.ats_webhook_events TO anon;
GRANT ALL ON TABLE public.ats_webhook_events TO authenticated;
GRANT ALL ON TABLE public.ats_webhook_events TO service_role;


--
-- Name: TABLE blog_posts; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.blog_posts TO anon;
GRANT ALL ON TABLE public.blog_posts TO authenticated;
GRANT ALL ON TABLE public.blog_posts TO service_role;


--
-- Name: TABLE calendar_event_detections; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.calendar_event_detections TO anon;
GRANT ALL ON TABLE public.calendar_event_detections TO authenticated;
GRANT ALL ON TABLE public.calendar_event_detections TO service_role;


--
-- Name: TABLE calendar_intelligence_state; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.calendar_intelligence_state TO anon;
GRANT ALL ON TABLE public.calendar_intelligence_state TO authenticated;
GRANT ALL ON TABLE public.calendar_intelligence_state TO service_role;


--
-- Name: TABLE candidate_feedback; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.candidate_feedback TO anon;
GRANT ALL ON TABLE public.candidate_feedback TO authenticated;
GRANT ALL ON TABLE public.candidate_feedback TO service_role;


--
-- Name: TABLE candidate_rounds; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.candidate_rounds TO anon;
GRANT ALL ON TABLE public.candidate_rounds TO authenticated;
GRANT ALL ON TABLE public.candidate_rounds TO service_role;


--
-- Name: TABLE candidates; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.candidates TO anon;
GRANT ALL ON TABLE public.candidates TO authenticated;
GRANT ALL ON TABLE public.candidates TO service_role;


--
-- Name: TABLE cortex_events; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.cortex_events TO anon;
GRANT ALL ON TABLE public.cortex_events TO authenticated;
GRANT ALL ON TABLE public.cortex_events TO service_role;


--
-- Name: TABLE cortex_force_publish_jobs; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.cortex_force_publish_jobs TO anon;
GRANT ALL ON TABLE public.cortex_force_publish_jobs TO authenticated;
GRANT ALL ON TABLE public.cortex_force_publish_jobs TO service_role;


--
-- Name: TABLE cortex_ingestion_record; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.cortex_ingestion_record TO anon;
GRANT ALL ON TABLE public.cortex_ingestion_record TO authenticated;
GRANT ALL ON TABLE public.cortex_ingestion_record TO service_role;


--
-- Name: TABLE cortex_org_ingest_jobs; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.cortex_org_ingest_jobs TO anon;
GRANT ALL ON TABLE public.cortex_org_ingest_jobs TO authenticated;
GRANT ALL ON TABLE public.cortex_org_ingest_jobs TO service_role;


--
-- Name: TABLE debrief_conversations; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.debrief_conversations TO anon;
GRANT ALL ON TABLE public.debrief_conversations TO authenticated;
GRANT ALL ON TABLE public.debrief_conversations TO service_role;


--
-- Name: TABLE debrief_insights; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.debrief_insights TO anon;
GRANT ALL ON TABLE public.debrief_insights TO authenticated;
GRANT ALL ON TABLE public.debrief_insights TO service_role;


--
-- Name: TABLE debrief_packets; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.debrief_packets TO anon;
GRANT ALL ON TABLE public.debrief_packets TO authenticated;
GRANT ALL ON TABLE public.debrief_packets TO service_role;


--
-- Name: TABLE feedback_access_tokens; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.feedback_access_tokens TO anon;
GRANT ALL ON TABLE public.feedback_access_tokens TO authenticated;
GRANT ALL ON TABLE public.feedback_access_tokens TO service_role;


--
-- Name: TABLE feedback_questions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.feedback_questions TO anon;
GRANT ALL ON TABLE public.feedback_questions TO authenticated;
GRANT ALL ON TABLE public.feedback_questions TO service_role;


--
-- Name: TABLE intake_sessions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.intake_sessions TO anon;
GRANT ALL ON TABLE public.intake_sessions TO authenticated;
GRANT ALL ON TABLE public.intake_sessions TO service_role;


--
-- Name: TABLE mcp_audit_log; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.mcp_audit_log TO anon;
GRANT ALL ON TABLE public.mcp_audit_log TO authenticated;
GRANT ALL ON TABLE public.mcp_audit_log TO service_role;


--
-- Name: TABLE oauth_authorization_codes; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.oauth_authorization_codes TO service_role;


--
-- Name: TABLE oauth_clients; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.oauth_clients TO service_role;


--
-- Name: TABLE oauth_refresh_tokens; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.oauth_refresh_tokens TO service_role;


--
-- Name: TABLE org_generic_template_bindings; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.org_generic_template_bindings TO anon;
GRANT ALL ON TABLE public.org_generic_template_bindings TO authenticated;
GRANT ALL ON TABLE public.org_generic_template_bindings TO service_role;


--
-- Name: TABLE organization_invites; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.organization_invites TO anon;
GRANT ALL ON TABLE public.organization_invites TO authenticated;
GRANT ALL ON TABLE public.organization_invites TO service_role;


--
-- Name: TABLE organizations; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.organizations TO anon;
GRANT ALL ON TABLE public.organizations TO authenticated;
GRANT ALL ON TABLE public.organizations TO service_role;


--
-- Name: TABLE personas; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.personas TO anon;
GRANT ALL ON TABLE public.personas TO authenticated;
GRANT ALL ON TABLE public.personas TO service_role;


--
-- Name: TABLE plans; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.plans TO anon;
GRANT ALL ON TABLE public.plans TO authenticated;
GRANT ALL ON TABLE public.plans TO service_role;


--
-- Name: TABLE profiles; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.profiles TO anon;
GRANT ALL ON TABLE public.profiles TO authenticated;
GRANT ALL ON TABLE public.profiles TO service_role;


--
-- Name: TABLE promotions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.promotions TO anon;
GRANT ALL ON TABLE public.promotions TO authenticated;
GRANT ALL ON TABLE public.promotions TO service_role;


--
-- Name: TABLE recall_bots; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.recall_bots TO anon;
GRANT ALL ON TABLE public.recall_bots TO authenticated;
GRANT ALL ON TABLE public.recall_bots TO service_role;


--
-- Name: TABLE requisitions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.requisitions TO anon;
GRANT ALL ON TABLE public.requisitions TO authenticated;
GRANT ALL ON TABLE public.requisitions TO service_role;


--
-- Name: TABLE round_screening_configs; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.round_screening_configs TO anon;
GRANT ALL ON TABLE public.round_screening_configs TO authenticated;
GRANT ALL ON TABLE public.round_screening_configs TO service_role;


--
-- Name: TABLE round_screening_questions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.round_screening_questions TO anon;
GRANT ALL ON TABLE public.round_screening_questions TO authenticated;
GRANT ALL ON TABLE public.round_screening_questions TO service_role;


--
-- Name: TABLE rounds; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.rounds TO anon;
GRANT ALL ON TABLE public.rounds TO authenticated;
GRANT ALL ON TABLE public.rounds TO service_role;


--
-- Name: TABLE screening_invites; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.screening_invites TO anon;
GRANT ALL ON TABLE public.screening_invites TO authenticated;
GRANT ALL ON TABLE public.screening_invites TO service_role;


--
-- Name: TABLE slack_connections; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.slack_connections TO anon;
GRANT ALL ON TABLE public.slack_connections TO authenticated;
GRANT ALL ON TABLE public.slack_connections TO service_role;


--
-- Name: TABLE slack_installations; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.slack_installations TO anon;
GRANT ALL ON TABLE public.slack_installations TO authenticated;
GRANT ALL ON TABLE public.slack_installations TO service_role;


--
-- Name: TABLE subscriptions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.subscriptions TO anon;
GRANT ALL ON TABLE public.subscriptions TO authenticated;
GRANT ALL ON TABLE public.subscriptions TO service_role;


--
-- Name: TABLE topup_credits; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.topup_credits TO anon;
GRANT ALL ON TABLE public.topup_credits TO authenticated;
GRANT ALL ON TABLE public.topup_credits TO service_role;


--
-- Name: TABLE topup_products; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.topup_products TO anon;
GRANT ALL ON TABLE public.topup_products TO authenticated;
GRANT ALL ON TABLE public.topup_products TO service_role;


--
-- Name: TABLE transcripts; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.transcripts TO anon;
GRANT ALL ON TABLE public.transcripts TO authenticated;
GRANT ALL ON TABLE public.transcripts TO service_role;


--
-- Name: TABLE untracked_interview_imports; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.untracked_interview_imports TO anon;
GRANT ALL ON TABLE public.untracked_interview_imports TO authenticated;
GRANT ALL ON TABLE public.untracked_interview_imports TO service_role;


--
-- Name: TABLE usage_credits; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.usage_credits TO anon;
GRANT ALL ON TABLE public.usage_credits TO authenticated;
GRANT ALL ON TABLE public.usage_credits TO service_role;


--
-- Name: TABLE user_connections; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.user_connections TO anon;
GRANT ALL ON TABLE public.user_connections TO authenticated;
GRANT ALL ON TABLE public.user_connections TO service_role;


--
-- Name: TABLE user_conversation_history; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.user_conversation_history TO anon;
GRANT ALL ON TABLE public.user_conversation_history TO authenticated;
GRANT ALL ON TABLE public.user_conversation_history TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR FUNCTIONS; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO service_role;


--
-- PostgreSQL database dump complete
--



-- ============================================================================
-- SECURITY DEFINER lockdown
--
-- These functions run with the privileges of their OWNER and deliberately
-- bypass row-level security, which is the whole point of a definer function --
-- and exactly why the caller must be restricted. A stock Supabase project
-- grants EXECUTE on new functions in "public" to anon and authenticated, so
-- without these REVOKEs anyone holding the publishable key could call, for
-- example, admin_archive_organization() against any organization.
--
-- Every RPC in this codebase is invoked by the backend using the service_role
-- key; no browser code calls one directly. So service_role is the only grantee
-- required. If you add a definer function, add its guard here too.
-- ============================================================================
REVOKE ALL ON FUNCTION public.admin_archive_organization(p_org_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.admin_archive_organization(p_org_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.admin_restore_organization(p_org_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.admin_restore_organization(p_org_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.admin_set_structured_feedback(p_cr_id uuid, p_summary text, p_rating text, p_source text, p_feedback jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.admin_set_structured_feedback(p_cr_id uuid, p_summary text, p_rating text, p_source text, p_feedback jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.admin_submit_candidate_feedback(p_cr_id uuid, p_source text, p_feedback jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.admin_submit_candidate_feedback(p_cr_id uuid, p_source text, p_feedback jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.ats_apply_dirty_update(p_org_id uuid, p_requisition_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_apply_dirty_update(p_org_id uuid, p_requisition_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.ats_connect(p_org_id uuid, p_provider text, p_integration_id text, p_user_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_connect(p_org_id uuid, p_provider text, p_integration_id text, p_user_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.ats_enrich_candidate(p_candidate_id uuid, p_org_id uuid, p_profile jsonb, p_resume_url text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_enrich_candidate(p_candidate_id uuid, p_org_id uuid, p_profile jsonb, p_resume_url text) TO service_role;
REVOKE ALL ON FUNCTION public.ats_import_job(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_job_id text, p_fields jsonb, p_ats_status text, p_user_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_import_job(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_job_id text, p_fields jsonb, p_ats_status text, p_user_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.ats_mark_deleted(p_org_id uuid, p_ats_type text, p_ats_id text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_mark_deleted(p_org_id uuid, p_ats_type text, p_ats_id text) TO service_role;
REVOKE ALL ON FUNCTION public.ats_promote_interviews(p_requisition_id uuid, p_org uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_promote_interviews(p_requisition_id uuid, p_org uuid) TO service_role;
REVOKE ALL ON FUNCTION public.ats_upsert_candidate(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_application_id text, p_ats_candidate_id text, p_fields jsonb, p_ats_status text, p_stage_id text, p_stage_name text, p_profile jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_upsert_candidate(p_connection_id uuid, p_org_id uuid, p_provider text, p_ats_application_id text, p_ats_candidate_id text, p_fields jsonb, p_ats_status text, p_stage_id text, p_stage_name text, p_profile jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.ats_upsert_interview(p_org uuid, p_connection uuid, p_fields jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_upsert_interview(p_org uuid, p_connection uuid, p_fields jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.ats_upsert_stage_round_map(p_org_id uuid, p_requisition_id uuid, p_round_id uuid, p_ats_stage_id text, p_ats_stage_name text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ats_upsert_stage_round_map(p_org_id uuid, p_requisition_id uuid, p_round_id uuid, p_ats_stage_id text, p_ats_stage_name text) TO service_role;
REVOKE ALL ON FUNCTION public.claim_feedback_processing(p_cr_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_feedback_processing(p_cr_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.claim_intake_processing(p_requisition_id uuid, p_stale_seconds integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_intake_processing(p_requisition_id uuid, p_stale_seconds integer) TO service_role;
REVOKE ALL ON FUNCTION public.cortex_backfill_org_event(event_type text, org_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cortex_backfill_org_event(event_type text, org_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.cortex_emit_candidate_event() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cortex_emit_candidate_event() TO service_role;
REVOKE ALL ON FUNCTION public.cortex_emit_candidate_feedback_event() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cortex_emit_candidate_feedback_event() TO service_role;
REVOKE ALL ON FUNCTION public.cortex_emit_candidate_round_event() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cortex_emit_candidate_round_event() TO service_role;
REVOKE ALL ON FUNCTION public.cortex_emit_requisition_event() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cortex_emit_requisition_event() TO service_role;
REVOKE ALL ON FUNCTION public.cortex_emit_round_event() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cortex_emit_round_event() TO service_role;
REVOKE ALL ON FUNCTION public.cortex_emit_transcript_event() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cortex_emit_transcript_event() TO service_role;
REVOKE ALL ON FUNCTION public.debrief_commit_draft(p_packet_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.debrief_commit_draft(p_packet_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.debrief_conversation_append_turn(p_packet_id uuid, p_turn jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.debrief_conversation_append_turn(p_packet_id uuid, p_turn jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.debrief_supersede_and_insert(p jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.debrief_supersede_and_insert(p jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.execute_readonly_query(query_text text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.execute_readonly_query(query_text text) TO service_role;
REVOKE ALL ON FUNCTION public.get_dashboard_summary(p_org_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_dashboard_summary(p_org_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.increment_blog_likes(post_slug text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.increment_blog_likes(post_slug text) TO service_role;
REVOKE ALL ON FUNCTION public.intake_session_heartbeat(p_session_id uuid, p_user_id uuid, p_paused boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.intake_session_heartbeat(p_session_id uuid, p_user_id uuid, p_paused boolean) TO service_role;
REVOKE ALL ON FUNCTION public.intake_sessions_append_turn(p_session_id uuid, p_turn jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.intake_sessions_append_turn(p_session_id uuid, p_turn jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.intake_sessions_merge_answers(p_session_id uuid, p_patch jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.intake_sessions_merge_answers(p_session_id uuid, p_patch jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.intake_sessions_set_stage(p_session_id uuid, p_stage_name text, p_status text, p_output jsonb, p_error text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.intake_sessions_set_stage(p_session_id uuid, p_stage_name text, p_status text, p_output jsonb, p_error text) TO service_role;
REVOKE ALL ON FUNCTION public.is_admin() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.is_admin() TO service_role;
REVOKE ALL ON FUNCTION public.release_stale_intake_modality_locks(p_stale_minutes integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.release_stale_intake_modality_locks(p_stale_minutes integer) TO service_role;
REVOKE ALL ON FUNCTION public.reorder_requisition_rounds(p_requisition_id uuid, p_ordered_round_ids uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reorder_requisition_rounds(p_requisition_id uuid, p_ordered_round_ids uuid[]) TO service_role;
REVOKE ALL ON FUNCTION public.screening_create_invite(p jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.screening_create_invite(p jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.screening_invite_existing(p jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.screening_invite_existing(p jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.screening_save_config(p jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.screening_save_config(p jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.set_active_modality(p_session_id uuid, p_modality text, p_user_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_active_modality(p_session_id uuid, p_modality text, p_user_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.sync_profile_invitation_status() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.sync_profile_invitation_status() TO service_role;
REVOKE ALL ON FUNCTION public.undo_untracked_link(p_org_id uuid, p_source_cr_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.undo_untracked_link(p_org_id uuid, p_source_cr_id uuid) TO service_role;
REVOKE ALL ON FUNCTION public.update_assessment_evaluations_updated_at() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.update_assessment_evaluations_updated_at() TO service_role;
REVOKE ALL ON FUNCTION public.update_assessment_instances_updated_at() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.update_assessment_instances_updated_at() TO service_role;
REVOKE ALL ON FUNCTION public.update_assessment_templates_updated_at() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.update_assessment_templates_updated_at() TO service_role;
REVOKE ALL ON FUNCTION public.use_credit_atomic(p_org_id uuid, p_credit_type text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.use_credit_atomic(p_org_id uuid, p_credit_type text) TO service_role;

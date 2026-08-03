-- ============================================================================
-- OpenRecruiting — provision a staff user for the admin portal (`admin-app` :3001)
--
-- Run this in the Supabase SQL editor AFTER schema.sql. Edit the CONFIG block
-- below first — the script refuses to run while the password is still the
-- placeholder.
--
-- Safe to re-run: an existing account with the same email has its password
-- reset and its staff flag re-asserted rather than being duplicated.
--
-- WHAT "STAFF" MEANS
--   `profiles.is_staff = true` is the only thing gating the admin portal and
--   the 61 endpoints under /api/v2/admin/*. It is effectively superuser over
--   every organization in the instance — customers, subscriptions, promotions,
--   and manual credit grants. Do not set it on ordinary recruiter accounts.
--
-- WHY THIS WRITES TO auth.users DIRECTLY
--   `public.profiles.id` is a foreign key to `auth.users(id)`, and that table
--   belongs to Supabase Auth (GoTrue). The supported route is the dashboard
--   (Authentication → Users → Add user, with "Auto Confirm User" ticked) or the
--   admin API. This script exists so the whole thing is one repeatable step,
--   and it writes the same columns GoTrue writes: a bcrypt `encrypted_password`
--   via pgcrypto, a confirmed email, and the matching `auth.identities` row
--   that password sign-in requires. It is pinned to the current GoTrue schema —
--   if a future Supabase release changes those tables, prefer the dashboard.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- PART 1 — RLS prerequisite (retrofit; no-op on databases built from the
-- current schema.sql, which already contains this grant).
--
-- `public.is_admin()` is not an RPC: 39 RLS policies across 15 tables call it,
-- and a policy predicate executes with the CALLER's privileges. If EXECUTE is
-- revoked from `authenticated`, every authenticated read of those tables fails
-- with "permission denied for function is_admin" — the policy errors before it
-- can return a row, and the admin portal cannot even confirm you are staff.
--
-- Granting it is safe: it takes no arguments and reads only the caller's own
-- row (p.id = auth.uid()), so it discloses nothing a user cannot already infer
-- about themselves.
-- ---------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION public.is_admin() TO authenticated;


-- ---------------------------------------------------------------------------
-- PART 2 — the staff account
-- ---------------------------------------------------------------------------
DO $staff_user$
DECLARE
    -- ==================== CONFIG — EDIT THESE ====================
    v_email     text := 'staff@example.com';
    v_password  text := 'CHANGE-ME-BEFORE-RUNNING';
    v_full_name text := 'Staff User';
    -- =============================================================

    v_user_id uuid;
    v_org_id  uuid;
    v_existing boolean;
BEGIN
    IF v_password = 'CHANGE-ME-BEFORE-RUNNING' OR length(v_password) < 12 THEN
        RAISE EXCEPTION
            'Set v_password in the CONFIG block to a real password of at least 12 characters before running this script.';
    END IF;

    v_email := lower(trim(v_email));

    SELECT id INTO v_user_id FROM auth.users WHERE lower(email) = v_email;
    v_existing := v_user_id IS NOT NULL;

    IF v_existing THEN
        -- Reset the password and re-confirm the address; leave everything else.
        -- The COALESCEs also repair a row left by an older run of this script
        -- that omitted the token columns (see the note on the INSERT below).
        UPDATE auth.users
           SET encrypted_password       = extensions.crypt(v_password, extensions.gen_salt('bf')),
               email_confirmed_at       = COALESCE(email_confirmed_at, now()),
               confirmation_token       = COALESCE(confirmation_token, ''),
               recovery_token           = COALESCE(recovery_token, ''),
               email_change_token_new   = COALESCE(email_change_token_new, ''),
               email_change             = COALESCE(email_change, ''),
               updated_at               = now()
         WHERE id = v_user_id;
        RAISE NOTICE 'Existing auth user % — password reset.', v_email;
    ELSE
        v_user_id := extensions.uuid_generate_v4();

        -- `confirmed_at` is GENERATED ALWAYS from email/phone confirmation and
        -- must not be written here.
        --
        -- The four token columns must be '' and NOT NULL. They have no database
        -- default, but GoTrue scans them into non-nullable Go strings, so a NULL
        -- makes every sign-in fail with a 500 "Database error querying schema" —
        -- an error that points at the schema and not at the row that causes it.
        -- The remaining token columns (phone_change, phone_change_token,
        -- email_change_token_current, reauthentication_token) default to ''.
        INSERT INTO auth.users (
            instance_id, id, aud, role, email, encrypted_password,
            email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
            confirmation_token, recovery_token, email_change_token_new, email_change,
            created_at, updated_at
        ) VALUES (
            '00000000-0000-0000-0000-000000000000', v_user_id,
            'authenticated', 'authenticated', v_email,
            extensions.crypt(v_password, extensions.gen_salt('bf')),
            now(),
            '{"provider":"email","providers":["email"]}'::jsonb,
            jsonb_build_object('full_name', v_full_name, 'password_set', true),
            '', '', '', '',
            now(), now()
        );

        -- Password sign-in requires a matching identity row. `email` on this
        -- table is GENERATED ALWAYS from identity_data->>'email'.
        INSERT INTO auth.identities (
            provider_id, user_id, identity_data, provider,
            last_sign_in_at, created_at, updated_at
        ) VALUES (
            v_user_id::text, v_user_id,
            jsonb_build_object(
                'sub', v_user_id::text,
                'email', v_email,
                'email_verified', true,
                'phone_verified', false
            ),
            'email', now(), now(), now()
        );

        RAISE NOTICE 'Created auth user % (%).', v_email, v_user_id;
    END IF;

    -- Attach to an organization so the recruiter app has a tenant to scope to.
    -- Prefers the seed.sql demo org, then the oldest existing one. A staff user
    -- with no organization can still use the admin portal.
    SELECT id INTO v_org_id FROM public.organizations
     WHERE id = '00000000-0000-0000-0000-0000000000a1';
    IF v_org_id IS NULL THEN
        SELECT id INTO v_org_id FROM public.organizations
         ORDER BY created_at LIMIT 1;
    END IF;

    INSERT INTO public.profiles (
        id, email, full_name, is_staff, organization_id,
        invitation_status, onboarding_completed
    ) VALUES (
        v_user_id, v_email, v_full_name, true, v_org_id,
        'accepted', true
    )
    ON CONFLICT (id) DO UPDATE
        SET is_staff             = true,
            full_name            = EXCLUDED.full_name,
            organization_id      = COALESCE(public.profiles.organization_id, EXCLUDED.organization_id),
            invitation_status    = 'accepted',
            onboarding_completed = true,
            deleted_at           = NULL,
            updated_at           = now();

    IF v_org_id IS NULL THEN
        RAISE NOTICE 'No organization exists yet — profile created with organization_id NULL. The admin portal works; the recruiter app will show an empty tenant until you create one.';
    END IF;

    RAISE NOTICE 'Staff user ready: % — sign in at http://localhost:3001', v_email;
END
$staff_user$;


-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
SELECT p.email,
       p.is_staff,
       p.organization_id,
       u.email_confirmed_at IS NOT NULL AS email_confirmed,
       EXISTS (
           SELECT 1 FROM auth.identities i
            WHERE i.user_id = p.id AND i.provider = 'email'
       ) AS has_email_identity,
       -- All four must be true, or sign-in returns 500 "Database error
       -- querying schema" no matter how correct the password is.
       (u.confirmation_token     IS NOT NULL
        AND u.recovery_token         IS NOT NULL
        AND u.email_change_token_new IS NOT NULL
        AND u.email_change           IS NOT NULL) AS tokens_not_null,
       has_function_privilege('authenticated', 'public.is_admin()', 'EXECUTE') AS rls_grant_ok
  FROM public.profiles p
  JOIN auth.users u ON u.id = p.id
 WHERE p.is_staff
 ORDER BY p.created_at;

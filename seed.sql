-- ============================================================================
-- OpenRecruiting — optional demo seed
--
-- Run AFTER schema.sql. Safe to re-run (every statement is ON CONFLICT guarded).
--
-- Creates: one organization, one planned requisition with two interview rounds,
-- two candidates, three candidate-rounds (one completed with AI feedback, one
-- scheduled, one pending), and one interview transcript.
--
-- WHY THERE IS NO SEEDED RECRUITER ACCOUNT
--   public.profiles.id is a foreign key to auth.users(id), and auth.users is
--   owned by Supabase Auth. Fabricating a row there produces an account that
--   cannot actually sign in. So: sign up through the app first, then run the
--   ATTACH statement at the bottom of this file to put your account in the demo
--   organization. Until you do, row-level security will correctly hide all of
--   the data below from you.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Organization
-- ---------------------------------------------------------------------------
INSERT INTO public.organizations (id, name, domain, description, org_type)
VALUES ('00000000-0000-0000-0000-0000000000a1',
        'Acme Talent', 'example.com',
        'Demo organization created by seed.sql', 'team')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Requisition  (status must be one of: draft, intake_pending, planned, closed)
-- ---------------------------------------------------------------------------
INSERT INTO public.requisitions (
    id, organization_id, role_title, role_location,
    experience_min_years, experience_max_years, status, source,
    job_description, must_have_skills, good_to_have_skills, intake_summary)
VALUES ('00000000-0000-0000-0000-0000000000c1',
        '00000000-0000-0000-0000-0000000000a1',
        'Senior Backend Engineer', 'Remote (US)',
        5, 9, 'planned', 'native',
        'Design and operate the services behind our core product. You will own '
        'systems end to end, from schema to on-call.',
        ARRAY['Python', 'PostgreSQL', 'Distributed systems'],
        ARRAY['Kubernetes', 'Event-driven architecture'],
        'Hiring a senior backend engineer to own service architecture. Bar: '
        'strong systems depth, comfort with ambiguity, production ownership.')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Interview rounds  (duration_minutes must be 1..480)
-- ---------------------------------------------------------------------------
INSERT INTO public.rounds (
    id, requisition_id, round_number, name, category,
    duration_minutes, description, skills)
VALUES
 ('00000000-0000-0000-0000-0000000000d1',
  '00000000-0000-0000-0000-0000000000c1', 1, 'Technical Screen', 'technical',
  45, 'Systems fundamentals and a short coding exercise.',
  ARRAY['Python', 'Data modelling']),
 ('00000000-0000-0000-0000-0000000000d2',
  '00000000-0000-0000-0000-0000000000c1', 2, 'System Design', 'technical',
  60, 'Design a write-heavy service and defend the trade-offs.',
  ARRAY['Distributed systems', 'PostgreSQL'])
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Candidates  (status must be one of: active, hired, rejected, withdrawn)
-- ---------------------------------------------------------------------------
INSERT INTO public.candidates (
    id, requisition_id, name, email, phone, status, source)
VALUES
 ('00000000-0000-0000-0000-0000000000e1',
  '00000000-0000-0000-0000-0000000000c1',
  'Dana Okafor', 'dana.okafor@example.com', '+1-555-0142', 'active', 'native'),
 ('00000000-0000-0000-0000-0000000000e2',
  '00000000-0000-0000-0000-0000000000c1',
  'Marco Silva', 'marco.silva@example.com', '+1-555-0188', 'active', 'native')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Candidate rounds
--   status  : pending | scheduled | in_progress | completed | cancelled
--   rating  : strong_yes | yes | maybe | no | strong_no
--   outcome : advance | reject | hold
-- ---------------------------------------------------------------------------
INSERT INTO public.candidate_rounds (
    id, candidate_id, round_id, status, scheduled_at, started_at, completed_at,
    interviewer_email, interviewer_name, rating, outcome, summary,
    scorecard_status, processing_status, source_type)
VALUES
 -- Completed round, with the kind of AI-generated feedback the pipeline writes.
 ('00000000-0000-0000-0000-0000000000f1',
  '00000000-0000-0000-0000-0000000000e1',
  '00000000-0000-0000-0000-0000000000d1',
  'completed',
  now() - interval '3 days', now() - interval '3 days',
  now() - interval '3 days' + interval '47 minutes',
  'interviewer@example.com', 'Priya Raman',
  'yes', 'advance',
  'Strong practical grasp of relational modelling; walked through indexing '
  'trade-offs without prompting. Coding exercise completed with time to spare. '
  'Communication was clear and structured. Gap: limited exposure to running '
  'systems under real production load — worth probing in the design round.',
  'complete', 'completed', 'standard'),
 -- Scheduled round, nothing captured yet.
 ('00000000-0000-0000-0000-0000000000f2',
  '00000000-0000-0000-0000-0000000000e1',
  '00000000-0000-0000-0000-0000000000d2',
  'scheduled', now() + interval '2 days', NULL, NULL,
  'interviewer@example.com', 'Priya Raman',
  NULL, NULL, NULL, 'pending', 'none', 'standard'),
 -- Second candidate, not yet scheduled.
 ('00000000-0000-0000-0000-0000000000f3',
  '00000000-0000-0000-0000-0000000000e2',
  '00000000-0000-0000-0000-0000000000d1',
  'pending', NULL, NULL, NULL,
  NULL, NULL, NULL, NULL, NULL, 'pending', 'none', 'standard')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Transcript for the completed round
-- ---------------------------------------------------------------------------
INSERT INTO public.transcripts (
    id, candidate_round_id, provider, full_text, segments,
    word_count, duration_seconds, language, processed_at)
VALUES (
 '0000000a-0000-0000-0000-0000000000f1',
 '00000000-0000-0000-0000-0000000000f1',
 'seed',
 'Priya: Thanks for making the time. Want to start by walking me through a '
 'schema you have designed recently? '
 'Dana: Sure. Most recently a multi-tenant billing store. The interesting part '
 'was the tenant isolation — we went with row-level security rather than a '
 'schema per tenant, because the tenant count was going to grow faster than we '
 'wanted to run migrations. '
 'Priya: What did that cost you? '
 'Dana: Query planning, mostly. Every policy predicate lands in the plan, so we '
 'had to be deliberate about indexes that matched the policy shape.',
 '[{"speaker": "Priya Raman", "text": "Thanks for making the time. Want to start by walking me through a schema you have designed recently?"},
   {"speaker": "Dana Okafor", "text": "Sure. Most recently a multi-tenant billing store. The interesting part was the tenant isolation - we went with row-level security rather than a schema per tenant, because the tenant count was going to grow faster than we wanted to run migrations."},
   {"speaker": "Priya Raman", "text": "What did that cost you?"},
   {"speaker": "Dana Okafor", "text": "Query planning, mostly. Every policy predicate lands in the plan, so we had to be deliberate about indexes that matched the policy shape."}]'::jsonb,
 96, 2820, 'en', now() - interval '3 days')
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- ATTACH YOUR ACCOUNT  — required before you can see any of the above.
--
-- Sign up through the app first, then run ONE of these:
--
--   -- by email (preferred):
--   UPDATE public.profiles
--      SET organization_id = '00000000-0000-0000-0000-0000000000a1'
--    WHERE email = 'you@example.com';
--
--   -- or: adopt every account that does not belong to an organization yet
--   -- (fine on a fresh single-user instance, not on a shared one):
--   UPDATE public.profiles
--      SET organization_id = '00000000-0000-0000-0000-0000000000a1'
--    WHERE organization_id IS NULL;
-- ============================================================================

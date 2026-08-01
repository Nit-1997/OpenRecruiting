# One docker compose up: the whole stack

> Outline. The full post is a follow-on writing effort.

- Eleven containers, one .env, three cloud services you bring yourself.
- What `make verify` checks and why each line exists.
- Being honest about what was verified and what was not: a build environment with
  no cloud Supabase project cannot prove a sign-in works, so the checklist says
  UNVERIFIED instead of assuming.
- The .env.example was wrong four separate times, and every single error was found
  by booting the stack rather than reading the code.
- What would come next if this were maintained.

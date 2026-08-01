# Making a startup codebase safe to open-source

> Outline. The full post is a follow-on writing effort.

- The scariest thing in the repo was not a secret: 18 MB of production interview
  fixtures with real candidates' and interviewers' names, their transcripts, and
  the hiring verdicts -- encoded in the filenames. No secret scanner flags that.
- Deleting it from the working tree is not enough. It was in git history, and
  publishing the repo publishes every commit.
- Real people's testimonials cannot be republished under a different product
  name; that is misattribution, not just privacy.
- Every SECURITY DEFINER function was callable by `anon` and `authenticated`,
  because that is what a stock Supabase project grants. These functions bypass
  RLS by design, so that is a full privilege escalation.
- Auditing ACLs against a live database rather than grepping for REVOKE.
- A Cypher validator that blocked `apoc.cypher` but not `apoc.export` (dumps the
  whole multi-tenant graph) or `apoc.load` (SSRF from the DB server).
- Why an allow-list with reasons beats a permanently-red gate that everyone
  learns to ignore.

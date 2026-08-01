# Engineering notes

Nine posts, one per phase of the extraction. Outlines are here; the prose is a
follow-on effort. Each links to the commits that did the work, so the outline is
useful even before the post exists.

| # | Post | Phase |
|---|---|---|
| 0 | [Why and what we open-sourced](00-why-open-source.md) | Scaffold |
| 1 | [Squashing 133 migrations into one schema](01-squashing-migrations.md) | Schema |
| 2 | [Turning AWS Lambdas into local containers](02-lambdas-to-containers.md) | Backend + workers |
| 3 | [Packaging two Next.js apps and a shared cookie](03-two-next-apps.md) | Frontends + auth |
| 4 | [A recruiting knowledge graph](04-knowledge-graph.md) | Cortex + Neo4j |
| 5 | [A WebRTC voice intake agent](05-voice-agent.md) | Voice + Scout |
| 6 | [Real meeting capture with Recall.ai](06-meeting-capture.md) | Recall |
| 7 | [Making a startup codebase safe to open-source](07-safe-to-publish.md) | Security + gates |
| 8 | [One `docker compose up`: the whole stack](08-one-compose-up.md) | E2E + release |

## The thread running through them

Most of the interesting material is not "we moved files". It is the places where
a mechanical rename would have produced working-looking code that was subtly
wrong, and the only way to find out was to run it:

- A search-and-replace renamed a column onto the name of a local variable, and
  the resulting ambiguity only raises at **runtime** — silently breaking every
  admin permission check (post 1).
- Two host-detection heuristics matched a vendor domain. Substituting the domain
  turned one into dead code and the other into a disabled security guard
  (posts 2 and 3).
- BSD `sed` has no `\b`. Half the "word boundary" replacements silently did
  nothing, which is invisible unless you diff the result (posts 2 and 4).
- The de-brand grep never looks at **filenames** (post 3).
- The single most dangerous thing in the repo was not a secret and no scanner
  flagged it: 18 MB of real interview transcripts, with real candidates' names
  and the hiring verdicts reached about them (post 7).

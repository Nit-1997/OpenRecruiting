# A recruiting knowledge graph

> Outline. The full post is a follow-on writing effort.

- What the graph is for: candidates, requisitions, rounds, skills, and the
  relationships that make "who else interviewed well on pricing?" answerable.
- Ontology renames are not string replacements. The prefix, the namespace URI and
  every term reference move together, or you get a file that declares one prefix
  and uses another.
- Picking an ontology namespace for an OSS project: `.example` is reserved by
  RFC 2606 and can never collide with a real domain.
- The crash-loop: the service required an embedding key at startup and died
  without one, so anyone who hadn't set OPENAI_API_KEY got a restart loop instead
  of a running stack. Gating a feature vs. failing to boot.

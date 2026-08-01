# types/

Shared TypeScript types for domain models and event contracts.

**What lives here:** Plan, Round, Question (domain), AgentEvent, UserEvent,
ChatMessage, ActionCard, Chip, InlineAsk (contract).

**Design rule:** types are exported from `index.ts` in this folder for a
single import site: `import type { Plan, AgentEvent } from '@/types'`.
Types live alongside their implementations only when scoped to one file.

**Spec:** § 6.1, § 7.

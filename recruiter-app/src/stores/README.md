# stores/

Zustand stores — client-only shell state.

**What lives here:** chatStore (threads), workspaceStore (tabs, active tab),
artifactStore (artifact data by id), undoStore (patch history), voiceStore
(call state, captions).

**Design rule:** stores handle state shape and reducers; hooks (`../hooks/`)
handle derived state, selectors, subscriptions. Server state (TanStack
Query) lives separately — stores are for ephemeral UI state only.

# KNOWNEST 前端重建设计与接口审计

## Scope

This document records the implementation boundary used by the KNOWNEST frontend rebuild. The attached concept images are visual references only; they are not treated as API contracts.

## Product Rules

- The brand shown in the top-left is `KNOWNEST`.
- `普通 RAG` retrieves indexed knowledge-base chunks and streams citations.
- `智能回答` uses the bounded Agent flow and may use explicitly enabled MCP tools.
- MCP is managed from the settings drawer; ordinary RAG never executes MCP tools, while intelligent answering may use explicitly enabled tools.
- Drawers are right-anchored overlays. Opening a drawer must not reflow the underlying workspace.
- A document is not shown as `已索引` until the backend reports an indexed state.
- Real API failures must remain visible. They must not silently fall back to fake successful data.
- Destructive deletion must state that the document, chunks, vectors, and source file are permanently removed.

## Confirmed Backend Contracts

Implemented routes include workspace and knowledge-base CRUD, folder CRUD, document upload/list/detail/preview/delete/reindex/chunks, citation lookup, RAG and Agent sessions/messages, Agent cancellation, memory CRUD and lifecycle actions, model listing/creation/testing, MCP server CRUD/connect/discovery, and MCP tool enable/disable.

## Frontend Gaps Closed By This Rebuild

- Real document detail, preview, reindex, and delete entry points.
- Delete confirmation drawer with refresh after successful deletion.
- MCP server list, add, connect, discover, tool list, tool enable/disable, and delete entry points.
- Evidence, citation, memory, MCP, document detail, and delete drawers with one visual system.
- Session list and session restoration entry points.
- Real upload status handling using the backend job state rather than optimistic `已索引`.
- Upload polling is bounded to 30 checks and refreshes the document list at terminal job states.
- RAG/Agent mode changes clear the active session and evidence trace so a session is never reused across modes.
- Citation lookup failures are shown as an explicit backend error; quoted fallback text is labeled by the error state and is not presented as a successful source fetch.
- The conversation surface follows a fixed workbench layout: mode selection above, one scrollable answer area in the middle, and one compact composer at the bottom. Drawers remain fixed overlays and do not reflow this layout.
- Explicit demo-state labeling when no authentication token exists.
- KNOWNEST branding in the browser title and top-left application header.

## Deliberately Not Invented

The backend does not provide page count, uploader, generated summary, document tags, structured MCP risk levels, MCP health timestamps, soft-delete/recycle-bin semantics, or paginated document filters. The rebuilt UI does not present these as backend facts. Where a document detail view needs a derived value, it uses only fields returned by the detail endpoint.

## Known Risks

1. Permanent document deletion invalidates future citation lookups for deleted chunks. The UI warns about this; a future product decision is still needed on citation snapshots versus soft deletion.
2. Agent cancellation is a backend request. Closing the browser stream alone is not treated as cancellation.
3. MCP transports can execute external requests or local commands. The backend deployment must enforce network and process restrictions.
4. The frontend now has a login/setup route and guards `/runtime/*` when no token is present. The explicitly labeled demo state remains useful for local visual review, but it must not be treated as an authenticated production session.

## Verification Gate

- `npm.cmd run build`
- backend tests
- Impeccable detector over changed frontend files
- manual checks for desktop/mobile drawer overflow, keyboard close, focus return, upload states, delete refresh, and MCP tool toggles

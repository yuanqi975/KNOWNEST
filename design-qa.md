# Design QA

## Redesign pass

- Design system: native CSS, editorial workbench aesthetic, existing Knownest teal and dark-forest palette retained.
- Design dials: `DESIGN_VARIANCE 7 / MOTION_INTENSITY 4 / VISUAL_DENSITY 5`.
- Audit changes: replaced the oversized question card treatment, introduced a compact thread summary strip, strengthened user/assistant message hierarchy, tightened composer height, and restyled evidence as a source stack.

- Source visual truth: `C:/Users/ASUS/AppData/Local/Temp/codex-clipboard-dee66ad5-d265-42b6-849f-caf33b723312.png` (1250 × 889 px)
- Implementation: `frontend/src/views/python/RuntimeApp.vue` served at `http://localhost:4173/runtime/rag`
- Intended viewport: 1250 × 889 CSS px, desktop, populated thread state
- Implementation screenshot: unavailable
- State: desktop populated Knownest thread; narrow-screen evidence drawer and request error states are implemented but not captured

## Findings

- [P1] Browser-rendered comparison is blocked. The Codex in-app browser rejected the local preview request during automatic review (403), so the source and implementation could not be opened together or compared at the target viewport.

## Required fidelity surfaces

- Fonts and typography: reviewed in source code; final rendered comparison not verified.
- Spacing and layout rhythm: implementation defines the desktop three-column grid and mobile breakpoints; final rendered comparison not verified.
- Colors and visual tokens: implementation uses a restrained teal/cream palette derived from the reference; final rendered comparison not verified.
- Image quality and asset fidelity: reference contains no required raster assets beyond the supplied screenshot; the wordmark is rendered as text and a simple mark.
- Copy and app-specific text: Chinese copy is restored from the reference and interaction requirements.

## Primary interactions implemented

- RAG / 智能回答 tabs preserve `mode` on each message.
- Enter sends, Shift+Enter inserts a newline, Escape closes drawers.
- Composer has bounded vertical resize and internal scrolling.
- Streaming answers expose cancel, timeout, partial-result, error and retry states.
- Failed requests restore the original question.
- Evidence remains available through a drawer on narrow screens.
- Upload flow handles duplicate, indexing, indexed, unsupported and failed states.
- MCP drawer displays permission scope and risk language.

## Final result

blocked

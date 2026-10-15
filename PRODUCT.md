# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Enterprise knowledge workers who need to find, understand, and use information held across their organization's documents.

## Product Purpose

WeKnora Runtime is a web knowledge application for asking questions of a selected knowledge base. It supports direct retrieval-assisted answers and an agentic research mode, with source citations and evidence traces available for review.

## Positioning

The product combines document-grounded RAG and bounded agent research in one workspace, exposing the evidence behind answers instead of treating the response as an opaque chat result.

## Operating Context

Users work within a workspace and selected knowledge base. They upload and index documents, ask questions, inspect citations and source passages, and may use agent tool traces for more involved research.

## Capabilities and Constraints

- Separate RAG and Agent routes are implemented in the Vue frontend.
- The Agent has bounded reasoning and tool-call limits; its hidden chain of thought is not shown in the browser.
- Answers can include stored citations that open the originating source chunk.
- Workspaces support knowledge bases, documents, conversations, memories, model configuration, and MCP server configuration.
- The current frontend is a Vue 3 application; the backend uses FastAPI and compatible model providers.

## Evidence on Hand

- Product overview: `README.md`.
- API contract and evidence behavior: `backend/API.md`.
- Current runtime screen: `frontend/src/views/python/RuntimeApp.vue`.
- Existing illustrative assets: `design-concepts/`.

## Product Principles

- Ground answers in inspectable source material.
- Make research progress and system activity legible without exposing hidden reasoning.
- Keep high-frequency knowledge work focused and efficient.
- Preserve a clear boundary between simple retrieval and tool-enabled research.


# Luna Agent Delivery Plan

The principal architect owns architecture, acceptance criteria, and review.
Luna agents own implementation, tests, debugging, and scoped file creation.
Each phase starts only after the previous phase passes review.

## Phase sequence

| Phase | Luna role | Deliverable | Review gate |
|---|---|---|---|
| 1 | Foundation Agent | Backend/frontend skeleton, config, DB/migrations, launch scripts, CI-quality local checks | Both apps start; migrations and baseline tests pass |
| 2 | Data Agent | Allow-listed crawler, parser, Markdown/JSON normalization, metadata, quality report | Representative fixtures are complete, deterministic, deduplicated, and traceable |
| 3 | RAG Agent | bge-m3 adapter, Qdrant store, chunking, retrieval, cited answering, evaluation set | Retrieval/citation thresholds pass and unsupported answers abstain |
| 4 | Database Agent | Campaign repositories/services and complete state APIs | Constraints, migrations, concurrency, audit, and CRUD integration tests pass |
| 5 | AI Agent | Typed tools, two-model orchestration, change proposal workflow, DM hints | No unconfirmed writes; prompt-injection and hallucination tests pass |
| 6 | Frontend Agent | Dark DM dashboard and full API integration | Critical Playwright journeys pass; layout and error states are usable |
| 7 | Hardening Agent | Packaging, backups, diagnostics, performance and security review | Fresh-machine setup and end-to-end acceptance suite pass |

## Review protocol

For every phase, the principal architect checks:

1. Architecture boundaries and scope.
2. Maintainability, typing, documentation, and test quality.
3. Schema evolution and data integrity.
4. Grounding, tool safety, and hallucination controls.
5. Apple Silicon resource use and local latency.
6. Localhost exposure, input validation, crawler safety, and secret handling.

Failed gates produce a focused Luna repair brief rather than being silently
accepted into the next phase.

## Phase 1 Luna Task Brief

# Luna Task Brief

Task:

Initialize the Local AI D&D Dungeon Master Assistant repository.

目标:

Create a clean, locally runnable foundation for the FastAPI backend, React
frontend, SQLite database, configuration system, tests, and launch commands.

背景:

The approved Phase 0 architecture is in `docs/architecture.md`. Version 1 is a
text-only, local DM copilot. Phase 1 must create boundaries and infrastructure
only; crawler, RAG, campaign business features, and agent reasoning belong to
later phases.

需要修改文件:

- Repository root configuration and documentation
- `backend/` application package, migrations, and tests
- `frontend/` React/TypeScript/Tailwind application and tests
- `scripts/` local launch/check helpers
- `.env.example`, ignore files, and dependency lock files
- Do not replace or weaken `docs/architecture.md`

技术要求:

- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite
- React, TypeScript, Vite, Tailwind CSS, TanStack Query
- uv and pnpm
- Configuration-driven paths/model names; bind backend to `127.0.0.1`
- Backend layer boundaries: API, application, domain, infrastructure,
  integrations
- A minimal schema/migration sufficient to prove Alembic and SQLite work
- Health endpoint, stable error envelope, CORS restricted to configured origin
- pytest and frontend unit tests; strict TypeScript and lint/type-check commands
- Apple Silicon compatible dependencies

实现方式:

1. Inspect the architecture document before editing.
2. Scaffold the smallest functional modular monolith.
3. Add typed settings and dependency injection seams for DB, Ollama, embedding,
   and vector store without implementing later-phase behavior.
4. Add an initial Alembic migration and database smoke test.
5. Create a restrained dark dashboard shell matching the four-panel layout.
6. Provide one-command development startup plus separate backend/frontend
   commands.
7. Run all feasible checks and report exact results.

禁止事项:

- Do not implement the crawler, RAG, agent tools, or campaign CRUD.
- Do not download Ollama models or add cloud dependencies.
- Do not hard-code absolute paths, model names, secrets, or D&D rules.
- Do not use chat history as campaign memory.
- Do not expose the server on `0.0.0.0` by default.
- Do not commit generated databases, vector data, node modules, or secrets.
- Do not rewrite the approved architecture to fit implementation shortcuts.

验收标准:

- Fresh documented setup produces a backend and frontend that start locally.
- `GET /api/v1/health` returns a typed success response.
- Alembic can upgrade a new SQLite database to head.
- Backend tests pass.
- Frontend lint/type-check/tests/build pass.
- Dashboard shell renders header, event log, assistant, and state panel.
- `.env.example` documents all current settings.
- README explains prerequisites, commands, architecture boundaries, and Phase 1
  scope.

测试方法:

- Run backend unit/integration tests.
- Run Alembic upgrade against a temporary SQLite file.
- Run frontend lint, TypeScript check, unit tests, and production build.
- Start both applications and smoke-test health and dashboard loading.
- Include command output summaries and any unresolved issue in the handoff.

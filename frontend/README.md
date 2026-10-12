# Frontend

The web UI for the agent: an inbox with live triage, human review (approve, edit the
draft, leave actions out, reject), dead-letter retries, stats, and the demo's
test-email form. The design spec is in [`../design`](../design/README.md).

Vite, React 19, TypeScript, Tailwind CSS v4, shadcn/ui on Radix primitives,
TanStack Query and TanStack Router.

## Run it

```sh
# terminal 1, repo root: the API with the synthetic inbox (no keys needed)
uv run gmail-agent demo

# terminal 2
cd frontend
npm install
npm run dev        # http://localhost:5173, /api is proxied to :8000
```

In production FastAPI serves `frontend/dist` itself: `npm run build`, then
`gmail-agent demo` or `gmail-agent serve` and open http://127.0.0.1:8000.

## How data flows

- **Types** come from the API's OpenAPI schema, never written by hand:
  `uv run python -m gmail_operations_agent.api.openapi` writes `openapi.json`,
  `npm run gen:api` turns it into `src/api/schema.gen.ts`. A backend test fails
  when `openapi.json` is stale.
- **Reads** go through TanStack Query (`src/api/queries.ts`). The URL holds the
  open email, the tab and the search, so every view can be linked.
- **Live updates** arrive over server-sent events (`src/api/live.ts`). Each event
  carries the message summary, which is patched into the cached lists at once
  (`src/api/cache.ts`); a debounced refetch then confirms counts and order.
- **The demo session** is a cookie. The app makes one request before rendering,
  so parallel first requests do not each create a sandbox.

## Checks

```sh
npm run typecheck
npm run lint       # oxlint
npm test           # Vitest: cache updates, view logic, the API client
npm run e2e        # builds, starts the real demo backend, runs Playwright
```

The end-to-end tests drive the built UI against `gmail-agent demo`, which replays
recorded model runs, so they need `uv` but no API keys or network.

`package.json` overrides `openapi-typescript`'s TypeScript peer range: it asks for
TypeScript 5 and works with 6.

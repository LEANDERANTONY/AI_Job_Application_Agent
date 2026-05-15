# Frontend

The `frontend/` app is the live Next.js workspace for the AI Job Application Agent, deployed on Vercel and calling the FastAPI backend through a same-origin rewrite.

The workspace includes:

- account-aware Google sign-in and session restore
- resume upload + parsing, or building one conversationally with the assistant
- job search plus direct job-URL import
- manual JD upload and editing
- deterministic preview and the supervised agentic analysis (Tailoring → Review → ResumeGen → CoverLetter)
- shortlist persistence and latest saved-workspace reload
- grounded assistant chat scoped to the active workspace
- voice input on the JD / resume-builder / assistant fields, and thumbs-up/down feedback on every artifact
- artifact preview plus **DOCX and PDF export in two themes** (`classic_ats`, `professional_neutral`)
- a custom EU cookie consent banner gating PostHog + Sentry Session Replay behind explicit opt-in

## Local development

1. Start the backend from the repo root:

```powershell
uv run uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

2. In this `frontend/` directory:

```powershell
npm install
npm run dev
```

3. Open [http://localhost:3000](http://localhost:3000)

## Environment

Copy `frontend/.env.example` into a local `.env.local` and set:

- `NEXT_PUBLIC_API_BASE_URL=/api`
- `API_REWRITE_TARGET=http://127.0.0.1:8000` for local backend development
- `NEXT_PUBLIC_SITE_URL=http://localhost:3000`

For Vercel production:

- keep `NEXT_PUBLIC_API_BASE_URL=/api`
- point `API_REWRITE_TARGET` at the VPS FastAPI origin (e.g. `https://api.example.com`) so the frontend stays same-origin on Vercel and the backend host stays hidden behind the rewrite
- set `NEXT_PUBLIC_SITE_URL` to the Vercel workspace URL

Observability env vars (`NEXT_PUBLIC_SENTRY_*`, `NEXT_PUBLIC_POSTHOG_*`, `SENTRY_AUTH_TOKEN`) are documented inline in `frontend/.env.example`. All SDK init paths are no-ops on empty values, so local dev runs without analytics by default.

## Deployment notes

- Add the Vercel workspace URL to Supabase allowed redirect URLs because Google sign-in returns to `/workspace`.
- Keep the backend CORS list aligned with the Vercel domain and any custom domain placed in front of it.
- On the VPS, set `AI_JOB_APPLICATION_API_DOMAIN` in `backend/vps/.env` so Caddy serves the FastAPI container on the final API subdomain.
- The VPS runs a single shared ingress proxy on `80/443` routing multiple domains/subdomains to separate app containers — do not stand up a second public Caddy stack competing for those ports. See `docs/operations.md` for the Caddy-state-must-be-in-git gotcha.
- The frontend is build-verified with `npm run build`; source maps upload to Sentry on every Vercel deploy via `withSentryConfig`.

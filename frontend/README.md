# Frontend

This `frontend/` app is now the live `Next.js` workspace for the Streamlit-to-Vercel migration.

The current workspace includes:

- account-aware Google sign-in and session restore
- resume upload and parsing
- job search plus direct job URL import
- manual JD upload and editing
- deterministic preview and agentic analysis
- shortlist persistence and latest saved-workspace reload
- grounded assistant chat scoped to the active workspace
- artifact preview plus Markdown, PDF, and ZIP package exports

## Local Development

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
- `API_REWRITE_TARGET=http://127.0.0.1:8000/api` for local backend development
- `NEXT_PUBLIC_SITE_URL=http://localhost:3000`

For Vercel production:

- keep `NEXT_PUBLIC_API_BASE_URL=/api`
- point `API_REWRITE_TARGET` at the VPS FastAPI origin, for example `https://api.example.com/api`
- set `NEXT_PUBLIC_SITE_URL` to the Vercel workspace URL
- this mirrors the HelpMate setup, where the frontend stays same-origin on Vercel and the actual backend host is hidden behind the rewrite target

## Deployment Notes

- Add the Vercel workspace URL to Supabase allowed redirect URLs because Google sign-in returns to `/workspace`.
- Keep the backend CORS list aligned with the Vercel domain and any custom domain you place in front of it.
- On the VPS, set `AI_JOB_APPLICATION_API_DOMAIN` in `deploy/vps/.env` so Caddy serves the FastAPI container on the final API subdomain.
- Because this app shares the same VPS as HelpMate, do not run two separate public Caddy stacks on `80/443`. The safer production shape is one shared ingress proxy routing multiple domains or subdomains to separate app containers.
- The frontend is build-verified with `npm run build`; the remaining work after code merge is hosted QA across real env vars and auth callbacks.

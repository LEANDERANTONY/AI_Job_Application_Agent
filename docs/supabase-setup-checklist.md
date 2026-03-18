# Supabase Setup Checklist

Use this when turning on saved-workspace reloads, persisted usage, and account-level quotas.

The current product does not expose a separate saved-workspace page. The saved snapshot is restored through the sidebar `Reload Workspace` action directly into `Manual JD Input`.

## 1. Create the Supabase project

- Create a new Supabase project for this app.
- Wait for the database and Auth services to finish provisioning.
- In Project Settings, copy the project URL.
- In Project Settings, copy the anon public key.

These map to:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`

## 2. Apply the database schema

Use the Supabase SQL Editor and run [docs/supabase-bootstrap.sql](docs/supabase-bootstrap.sql).

That bootstrap script creates:

- `app_users`
- `usage_events`
- `saved_workspaces`

It also creates the required indexes, Row Level Security policies, and the scheduled cleanup job for expired saved workspaces.

## 3. Configure the auth provider

The current app is wired for Google sign-in through Supabase Auth.

- In Supabase, open Authentication -> Providers.
- Enable the Google provider.
- Add the Google client ID and client secret.
- Set the allowed redirect URL to your app URL.

For local Streamlit development, the default redirect is usually:

- `http://localhost:8501`

That value should also be used for:

- `SUPABASE_AUTH_REDIRECT_URL`

If you later deploy to Streamlit Community Cloud, update the provider redirect list and the app config to the hosted URL.

The app now preserves Supabase PKCE verifier state across the Streamlit redirect cycle. If a callback arrives without the expected verifier state, the user sees a clean retry message instead of an incomplete signed-in state.

## 4. Configure local app environment

Create a private `.env` file in the repo root and copy the needed keys from [/.env.example](../.env.example):

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_AUTH_REDIRECT_URL`
- `SUPABASE_APP_USERS_TABLE=app_users`
- `SUPABASE_USAGE_EVENTS_TABLE=usage_events`
- `SUPABASE_SAVED_WORKSPACES_TABLE=saved_workspaces`
- `SAVED_WORKSPACE_TTL_HOURS=24`

Recommended auth behavior once Supabase is live:

- `AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW=true`

The repo-root `.env` file is ignored by git and is now loaded automatically for local runs. When you later deploy to Streamlit Community Cloud, put the same values into the Streamlit Secrets manager instead.

## 5. Run the app and test auth

Start Streamlit and verify the login flow works.

Minimum smoke test:

1. Sign in from the sidebar.
2. Confirm the app shows the authenticated account panel.
3. Upload a resume and move into `Manual JD Input` without a `current_menu` session-state error.
4. Run the assisted workflow once and confirm the execution mode is `OpenAI`, not deterministic fallback.
5. Click `Reload Workspace` from the signed-in sidebar account panel and confirm the latest saved workspace restores into `Manual JD Input`.
6. Confirm the restored JD page still shows the saved resume-backed state and keeps the restored workflow outputs available.
7. Generate PDF exports and confirm the current in-session exports still work.

## 6. Verify database writes in Supabase

Check the Table Editor or run SQL queries to confirm:

- `app_users` has one row for your signed-in account.
- `usage_events` records assisted requests.
- `saved_workspaces` keeps only the latest reloadable workspace per user and overwrites it on each successful workflow run.

The current saved-workspace behavior is intentionally ephemeral:

- one reloadable saved workspace row per authenticated user
- overwritten by the latest successful workflow run
- expires exactly when `expires_at` is reached because Supabase RLS stops serving the row after that timestamp
- is physically deleted by a Supabase scheduled cleanup job that runs every 5 minutes
- is also purged opportunistically by the app on save/load as a backup cleanup path

If `usage_events` stays empty, the assisted request likely fell back before a successful OpenAI response completed. In the current app, successful assisted requests should persist usage rows after the model response is accepted.

## 7. Verify Row Level Security

Confirm the following behavior:

- a signed-in user can read only their own `app_users` row
- a signed-in user can read only their own `usage_events`
- a signed-in user can read only their own `saved_workspaces` row
- expired `saved_workspaces` rows are no longer readable after `expires_at`

The bootstrap SQL already creates these policies, so this step is a validation step, not a separate schema design task.

## 8. Verify the scheduled cleanup job

Run these checks in the Supabase SQL Editor:

```sql
select jobid, jobname, schedule, command
from cron.job
where jobname = 'cleanup-expired-saved-workspaces';
```

```sql
select public.cleanup_expired_saved_workspaces();
```

Expected behavior:

- the cron job exists and runs every 5 minutes
- expired rows disappear even if the user never comes back to the app
- the app still treats expired rows as unavailable immediately because the read policy blocks them at `expires_at`

## 9. After local validation

When you deploy:

- move the same values into the host secret manager
- update `SUPABASE_AUTH_REDIRECT_URL` to the hosted app URL
- update the Google provider redirect settings in Supabase to match

## Related Files

- [README.md](../README.md)
- [deployment-plan.md](../deployment-plan.md)
- [docs/supabase-bootstrap.sql](supabase-bootstrap.sql)

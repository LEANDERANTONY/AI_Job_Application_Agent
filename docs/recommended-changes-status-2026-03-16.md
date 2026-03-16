# Recommended Changes Status — March 16, 2026

This document summarizes the 21 recommended changes tracked at the top of `improvements.md`, along with what was changed for each one and the current status.

It also includes the smaller follow-up cleanup items from the later re-assessment section where those were completed after the initial 21-item pass.

Status labels used here:

- `Completed in stepwise pass`: implemented during the March 15-16 step-by-step improvement run
- `Already implemented earlier`: present in the current codebase before this summary document was created
- `Mostly implemented earlier`: core capability already exists, but some surrounding work was completed during the recent stepwise pass

## 1. Assistant Product-Help Latency

Status: `Completed in stepwise pass`

Changes made:

- switched product-help requests to a leaner request shape that does not send `temperature` to models that reject it
- reduced product-help reasoning effort to `low`
- disabled higher output-budget retries for product-help so short help questions fail fast to deterministic fallback instead of paying extra round trips

Checkpoint:

- `c064307` — `Step 7: Reduce product-help assistant latency`

## 2. Assistant Limit Awareness Is Inaccurate

Status: `Completed in stepwise pass`

Changes made:

- expanded product-help prompt guidance for limit, quota, warning, and fallback questions
- added runtime session-budget and daily-quota context to product-help requests
- improved deterministic fallback answers so they explain browser-session budget versus account-level daily quota directly

Checkpoint:

- `5c2bca1` — `Step 5: Ground assistant limit-awareness in runtime quotas`

## 3. Main AI Workflow Can Quietly Drop To Deterministic Fallback Mid-Run

Status: `Completed in stepwise pass`

Changes made:

- preserved whether assisted mode was attempted before fallback
- surfaced fallback reason and details on the workflow result
- added explicit UI warning when a supervised run downgrades from AI-assisted mode to deterministic fallback

Checkpoint:

- `88c2953` — `Step 2: Show supervised workflow fallback reasons`

## 4. Truncated Partial JSON Responses Need Dedicated Recovery Logic

Status: `Completed in stepwise pass`

Changes made:

- added retry handling for incomplete `max_output_tokens` responses that contain partial malformed JSON
- added retry handling for incomplete responses with partial JSON that is missing required fields
- added focused tests covering both retry paths

Checkpoint:

- `f19aa77` — `Step 1: Recover truncated partial JSON responses`

## 5. Internal Account Should Support Unlimited Assisted Access During Product Testing

Status: `Completed in stepwise pass`

Changes made:

- added `AUTH_INTERNAL_USER_EMAILS` configuration
- mapped allowlisted emails to `plan_tier=internal` during authenticated user sync
- documented the configuration in `.env.example` and `README.md`

Checkpoint:

- `eafe132` — `Step 3: Add internal account quota override`

## 6. Add A Separate Quota-Test User For Daily-Limit Validation

Status: `Completed in stepwise pass`

Changes made:

- documented the intended split between unrestricted internal accounts and normal quota-test accounts
- clarified that only unrestricted internal emails belong in `AUTH_INTERNAL_USER_EMAILS`
- documented that any second non-allowlisted Google account remains on the normal free-tier quota path

Checkpoint:

- `fa4408a` — `Step 14: Document quota test account split`

## 7. Input Prompt Budgeting Needs First-Class Visibility And Guardrails

Status: `Completed in stepwise pass`

Changes made:

- added prompt-compaction rules for the largest supervised-agent prompts
- attached prompt-budget metadata such as estimated input size and compacted sections to assisted requests
- surfaced latest prompt-budget details in the UI usage panel

Checkpoint:

- `6fd8d53` — `Step 8: Add prompt budgeting guardrails`

## 8. Resume Template Selection Does Not Apply Cleanly

Status: `Completed in stepwise pass`

Changes made:

- made the selected resume template authoritative when building the artifact
- stopped `resume_generation.template_hint` from overriding a valid user-selected theme
- aligned artifact summary and displayed metadata with the active selected theme

Checkpoint:

- `d4489c8` — `Step 10: Make selected resume template authoritative`

## 9. Modern Professional Template Causes Unstable Reruns

Status: `Completed in stepwise pass`

Changes made:

- removed the explicit extra rerun in the resume-template selector path
- added theme-state normalization so invalid widget state is reset to a valid theme
- kept template changes converging on one session-state value

Checkpoint:

- `267db39` — `Step 11: Stabilize resume template reruns`

## 10. Markdown Downloads Break After Modern Professional Selection

Status: `Completed in stepwise pass`

Changes made:

- made artifact download widget keys content-aware so theme changes generate fresh download controls
- kept download controls aligned with the current tailored-resume artifact after theme switches
- removed stale UI-state behavior that could leave download controls pointing at old content

Checkpoint:

- `1057ef7` — `Step 12: Refresh download controls after theme changes`

## 11. Export Preparation UX Is Indirect And Confusing

Status: `Completed in stepwise pass`

Changes made:

- replaced explicit `Prepare ...` labels with consistent `Download ...` actions for PDF and ZIP bundle exports
- generated exports behind the first click with spinner feedback, then refreshed into the browser download control
- documented the Streamlit constraint that file bytes must exist before browser handoff

Checkpoint:

- `bf8b6d7` — `Step 13: Simplify export download actions`

## 12. Assistant Input Should Submit On Enter

Status: `Completed in stepwise pass`

Changes made:

- moved assistant entry to a form-based submission flow
- made pressing Enter submit the assistant question directly
- kept the explicit `Ask Assistant` button path inside the same form

Checkpoint:

- `51c430f` — `Step 4: Submit assistant input on Enter and clear after send`

## 13. Assistant Input Field Should Clear After Send

Status: `Completed in stepwise pass`

Changes made:

- enabled `clear_on_submit` on the assistant form
- left the input ready for the next question after a successful send

Checkpoint:

- `51c430f` — `Step 4: Submit assistant input on Enter and clear after send`

## 14. Application Q&A Is Too Narrow For General Resume Coaching

Status: `Completed in stepwise pass`

Changes made:

- broadened Application Q&A prompt guidance so it can give general coaching while staying grounded in the current package
- enriched Application Q&A context with review signals, highlighted skills, and fit gaps
- added deterministic fallback handling for broader coaching questions such as transferable collaboration framing

Checkpoint:

- `88f778e` — `Step 9: Broaden application Q&A coaching`

## 15. Saved Workspace Page Purpose And UX Are Unclear

Status: `Completed in stepwise pass`

Changes made:

- clarified that the page is for inspection and download regeneration of the latest saved snapshot
- added a direct in-page reload action
- updated page copy so the difference between inspect/download and restore/reload is explicit

Checkpoint:

- `a53abdd` — `Step 6: Clarify Saved Workspace page purpose`

## 16. Saved Workspace Reload Must Restore Resume-Backed Workflow State

Status: `Completed in stepwise pass`

Changes made:

- preserved resume document, candidate profile, JD, fit outputs, and tailored draft during reload
- restored the matching workflow signature before reapplying the saved supervised workflow result
- prevented the next Manual JD render from dropping restored workflow state as stale

Checkpoint:

- `0cb88c5` — `Step 15: Preserve saved workspace workflow state`

## 17. Explore Retrieval-Augmented Product Context For The Assistant

Status: `Completed in stepwise pass`

Changes made:

- added `src/product_knowledge.py` with curated product knowledge documents
- retrieved relevant knowledge hits per question and combined them with live runtime/session context
- allowed deterministic product-help fallback to use retrieved knowledge when a question falls outside the hardcoded fallback branches

Checkpoint:

- `9b34c99` — `Step 16: Add retrieval-backed product help context`

## 18. Revision Loop

Status: `Superseded by later workflow simplification`

Earlier state:

- `ApplicationOrchestrator` previously reran tailoring, strategy, and review in a bounded revision loop
- review feedback was injected back into `TailoringAgent.run(...)` as `revision_requests`
- revision pass history was preserved on `review_history`
- the loop was capped by `max_revision_passes`

Current state:

- the bounded rerun loop was removed in favor of one single-pass workflow
- Review now applies direct corrections to tailoring and strategy outputs instead of sending the whole flow through another pass
- `review_history` remains only as a compatibility field, not as an active revision-loop record for the current live flow

Current evidence:

- `src/agents/orchestrator.py`
- `src/agents/review_agent.py`
- `docs/adr/ADR-010-single-pass-review-corrections-and-task-tuned-model-budgets.md`

## 19. Application Strategy Agent

Status: `Already implemented earlier`

Changes present in the current codebase:

- `StrategyAgent` exists as a first-class agent under `src/agents/strategy_agent.py`
- the orchestrator runs it once in the active single-pass workflow
- its output is included in workflow payloads, UI rendering, report generation, and resume generation context

Current evidence:

- `src/agents/strategy_agent.py`
- `src/agents/orchestrator.py`

## 20. Logging and Observability

Status: `Already implemented earlier`

Changes present in the current codebase:

- structured JSON logging exists in `src/logging_utils.py`
- workflow, agent, OpenAI, export, and usage-persistence paths emit structured events with metadata
- OpenAI request lifecycle logging is already present in `src/openai_service.py`
- orchestration lifecycle logging is already present in `src/agents/orchestrator.py`

Current evidence:

- `src/logging_utils.py`
- `src/openai_service.py`
- `src/agents/orchestrator.py`
- `src/exporters.py`

## 21. Authentication and Multi-Tenancy

Status: `Mostly implemented earlier`

Changes present in the current codebase:

- Google sign-in via Supabase is already integrated
- authenticated users sync into `app_users`
- persisted usage events back daily quota enforcement
- saved workspaces are stored per authenticated user
- internal account override and quota-test account split were completed in the recent stepwise pass

What was added during the recent stepwise pass for this area:

- internal-account allowlist override for unrestricted testing
- explicit documentation for keeping a separate non-allowlisted quota-test user

Current evidence:

- `src/ui/auth.py`
- `src/user_store.py`
- `src/usage_store.py`
- `src/saved_workspace_store.py`
- `README.md`
- `.env.example`

## Additional Follow-Up Improvements From The Re-Assessment

These items come from the later code-quality and testing follow-up section of `improvements.md`, not the original top 21 user-facing recommendations.

### A. Extract duplicated builder utility wrappers

Status: `Completed in current follow-up pass`

Changes made:

- removed the local `_slugify`, `_safe_join`, `_render_markdown_list`, and markdown wrapper indirection from `src/resume_builder.py`
- removed the parallel duplicated wrapper layer from `src/report_builder.py`
- used the shared helpers in `src/utils.py` directly so the builder modules no longer re-expose the same logic under local names

Current evidence:

- `src/resume_builder.py`
- `src/report_builder.py`
- `src/utils.py`

### B. Consolidate near-duplicate string-list helpers

Status: `Completed in current follow-up pass`

Changes made:

- kept the public `coerce_string_list(...)` and `unique_strings(...)` API surface stable in `src/agents/common.py`
- removed the duplicated internal deduplication path so both now flow through one shared normalization helper

Current evidence:

- `src/agents/common.py`
- `tests/test_agents_common.py`

### C. Add boundary tests for fit-service scoring

Status: `Completed in current follow-up pass`

Changes made:

- added a boundary test proving same-year start/end dates still earn the intended 0.5-year minimum experience credit
- added explicit type-validation tests for invalid `candidate_profile` and `job_description` inputs

Current evidence:

- `tests/test_fit_service.py`

### D. Add tests for thin helper modules

Status: `Completed in current follow-up pass`

Changes made:

- added direct helper coverage for `src/agents/common.py`
- added direct caching/factory-injection coverage for `src/ui/auth.py`
- added a workflow-level regression test showing an injected auth service can be reused without resolving a fresh one inside the UI workflow path

Current evidence:

- `tests/test_agents_common.py`
- `tests/test_ui_auth.py`
- `tests/test_ui_workflow.py`

### E. Make auth-service reuse more explicit in workflow persistence/quota paths

Status: `Completed in current follow-up pass`

Changes made:

- added optional `auth_service` injection to `refresh_daily_quota_status(...)`, `build_ai_session_view_model(...)`, `load_saved_workspace_summary(...)`, and `restore_latest_saved_workspace(...)`
- kept the cached `get_auth_service()` fallback behavior intact for normal app execution while making those workflow paths easier to test and reuse with one shared service instance
- added optional factory injection to `get_auth_service(...)` in `src/ui/auth.py`

Current evidence:

- `src/ui/workflow.py`
- `src/ui/auth.py`
- `tests/test_ui_workflow.py`
- `tests/test_ui_auth.py`

### F. Reclassified as already satisfied or stale after audit

Status: `Reclassified during follow-up audit`

Findings:

- the `datetime.utcnow()` note for `src/services/fit_service.py` was stale because the file already uses `datetime.now(timezone.utc)`
- the OpenAI retry logic note was stale because retry and incomplete-response recovery are already present in `src/openai_service.py`
- the md5 compatibility comment note was stale because the exporter already documents the `pdfdoc.md5 = md5_compat` compatibility path

Current evidence:

- `src/services/fit_service.py`
- `src/openai_service.py`
- `src/exporters.py`

### G. UI page split was already partially completed earlier

Status: `Mostly implemented earlier`

Findings:

- `src/ui/pages.py` is no longer the earlier ~1,240-line monolith referenced in the re-assessment; it is now 408 lines
- page-specific responsibilities were already split into `src/ui/page_artifacts.py`, `src/ui/page_assistant.py`, and `src/ui/page_history.py`
- the remaining `src/ui/pages.py` file is still a central composition layer, but the bulk split work had already happened before this follow-up pass

Current evidence:

- `src/ui/pages.py`
- `src/ui/page_artifacts.py`
- `src/ui/page_assistant.py`
- `src/ui/page_history.py`

### H. UI workflow split was already partially completed earlier

Status: `Mostly implemented earlier`

Findings:

- `src/ui/workflow.py` is no longer the earlier ~640-line file referenced in the re-assessment; it is now 417 lines
- workflow concerns were already split across `src/ui/workflow_intake.py`, `src/ui/workflow_history.py`, `src/ui/workflow_exports.py`, `src/ui/workflow_payloads.py`, and `src/ui/workflow_signatures.py`
- this follow-up pass only tightened the auth-service reuse seam; the larger structural split work had already been done earlier

Current evidence:

- `src/ui/workflow.py`
- `src/ui/workflow_intake.py`
- `src/ui/workflow_history.py`
- `src/ui/workflow_exports.py`
- `src/ui/workflow_payloads.py`
- `src/ui/workflow_signatures.py`

### I. Move daily usage aggregation to a server-side aggregate/RPC path

Status: `Completed in current follow-up pass`

Changes made:

- added `public.get_daily_usage_totals(...)` to the Supabase bootstrap SQL so the database can aggregate usage totals for the authenticated user directly
- updated `src/usage_store.py` to prefer the RPC path and return one aggregated totals payload instead of always fetching and summing every matching row in Python
- kept a compatibility fallback to the prior row-query path so the app still works until the updated SQL bootstrap is applied in Supabase
- added focused tests covering both RPC success and fallback behavior

Current evidence:

- `docs/supabase-bootstrap.sql`
- `src/usage_store.py`
- `tests/test_usage_store.py`

### J. Remaining larger follow-on work after this pass

Status: `No clear unresolved re-assessment blocker confirmed`

Current state:

- the late re-assessment items that were still under question have now been reconciled against the codebase
- the UI page split, UI workflow split, builder-helper cleanup, thin-module tests, fit-service boundary tests, and server-side usage aggregation are all now accounted for
- any further work from here would be new follow-on refinement rather than an unclosed item from the audited `improvements.md` list

## Tomorrow Follow-Up

These are the next practical checks to run in the app after the Supabase bootstrap update.

0. Review the generated PDF outputs themselves and improve the visual/layout quality, because the current exported documents still look off even when the workflow data and runtime are behaving correctly.
1. Sign in with a normal non-internal account and confirm the daily quota panel renders without warnings or silent fallback.
2. Verify the saved workspace flow still works normally after the updated bootstrap SQL, including reload and download regeneration.
3. Do one final spot-check with a normal non-internal account so the persisted quota panel, assisted run, and post-run quota refresh all behave correctly end to end.
4. Do one final cleanup pass over `improvements.md` and explicitly separate any remaining notes into:
	- obsolete / already handled
	- future nice-to-haves / optional refinements
5. If anything in the runtime quota path looks off, inspect `src/usage_store.py`, `src/quota_service.py`, and the `public.get_daily_usage_totals(...)` function together before changing unrelated UI code.

Completed on March 16, 2026 after this note was first written:
- removed the repeated local Playwright penalty on unsupported Windows runtimes by skipping that backend when the selector event-loop policy makes subprocess startup unsupported
- if Playwright still raises `NotImplementedError`, the exporter now disables that backend for the rest of the process and routes future PDF exports directly to ReportLab
- completed the cleanup pass over `improvements.md` so stale already-handled items are explicitly marked instead of lingering as false pending work
- forced an immediate persisted daily-quota refresh after authenticated supervised runs so the quota panel reflects newly recorded usage on the next render instead of waiting for cache expiry

## Commit Index

- `f19aa77` — Step 1: Recover truncated partial JSON responses
- `88c2953` — Step 2: Show supervised workflow fallback reasons
- `eafe132` — Step 3: Add internal account quota override
- `51c430f` — Step 4: Submit assistant input on Enter and clear after send
- `5c2bca1` — Step 5: Ground assistant limit-awareness in runtime quotas
- `a53abdd` — Step 6: Clarify Saved Workspace page purpose
- `c064307` — Step 7: Reduce product-help assistant latency
- `6fd8d53` — Step 8: Add prompt budgeting guardrails
- `88f778e` — Step 9: Broaden application Q&A coaching
- `d4489c8` — Step 10: Make selected resume template authoritative
- `267db39` — Step 11: Stabilize resume template reruns
- `1057ef7` — Step 12: Refresh download controls after theme changes
- `bf8b6d7` — Step 13: Simplify export download actions
- `fa4408a` — Step 14: Document quota test account split
- `0cb88c5` — Step 15: Preserve saved workspace workflow state
- `9b34c99` — Step 16: Add retrieval-backed product help context
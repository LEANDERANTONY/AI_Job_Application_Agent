# ADR-019: Independent Step Navigation in the Workspace

- Status: Accepted
- Date: 2026-05-08

## Context

The workspace's step rail enforced the following gates on which steps were navigable:

```
resume   → always available
jobs     → available once a candidate profile exists
jd       → available once a candidate profile exists OR a job is selected
analysis → available once both resume + JD are parsed
```

The rail surfaced "Upload a resume to unlock" tooltips on Job Search and Job Detail when their gates failed, and the corresponding rail buttons were `disabled`.

In practice the gates on Job Search and Job Detail caused friction:

- Users frequently arrive with a job they've already heard about — a recruiter reach-out, a friend's referral, a posting URL they want to evaluate. They want to paste the JD and look at the parsed requirements before deciding whether to upload a resume at all.
- Users sometimes want to browse the live listings cache as a discovery surface — "what ML engineering roles are open right now at Stripe / Pinterest / Anthropic?" — without committing to a resume upload first.
- The "Upload a resume to unlock" tooltip read as a hostile gate, not as guidance. The rail is for navigation; navigation gating belongs to the destination page if at all.

The Analysis step's gate is different: it can't actually run without both inputs (the supervised pipeline reads from both the parsed resume and the parsed JD). Gating it on the rail is honest.

## Decision

Drop the rail gates on Job Search and Job Detail. Keep the Analysis gate.

The new gating model:

```
resume   → always available
jobs     → always available
jd       → always available
analysis → available once both resume + JD are parsed
```

Specifically:

- `stepReady.jobs` and `stepReady.jd` in `WorkspaceShell.tsx` are now literal `true`. The corresponding entries in the `lockReason` tooltip map are empty strings.
- The "Upload a resume first" fallback `sub` text on the `nav-jobs` and `nav-jd` command-palette entries was removed — it was dead code now that those steps are never gated.
- The `AnalysisRunner.tsx` page-level "Upload a resume to proceed" affordance stays as the honest enforcement point for the only step that genuinely requires both inputs. The rail-level lock on Analysis is now a hint, not a hard wall (the page itself surfaces what's missing).

The actual workflow behavior is unchanged — Job Search has always called the cached-jobs RPC without needing a candidate profile, JD parsing has always worked on the JD text alone, and Analysis still won't run without both inputs. This ADR is purely about removing UI gates that pushed users away from useful pages.

## Alternatives Considered

### 1. Keep the gates but soften the tooltip copy
Rejected. The gate itself was the problem, not the tooltip phrasing. A "softer" tooltip on a button you can't click is worse, not better.

### 2. Allow navigation but show a "Step requires a resume" warning at the top of Job Search / Job Detail
Rejected. The pages don't actually require a resume to function — Job Search lists open roles regardless, and Job Detail parses a JD on its own. A warning would be lying about what the user can do.

### 3. Remove all gates including Analysis
Rejected. Analysis can't run without both inputs; allowing the user to navigate there only to see "Upload a resume to proceed" with no other affordances is worse than the rail-level visual hint that the step is gated. The current AnalysisRunner page tells the user exactly what's missing — that's the right experience.

## Consequences

### Positive

- Users with a JD they want to evaluate can paste it without any friction. The parsed-JD hero gives them an immediate read on whether the role is worth tailoring for.
- Users who want to browse open ML / data / engineering roles without uploading a resume can do so directly. The cached-jobs cache (Greenhouse / Lever / Ashby / Workday, ~12k roles) is a legitimate discovery surface in its own right.
- The rail reads as navigation, not enforcement — matches user expectation.
- One fewer "locked" affordance on the workspace, which reduces overall UI friction and makes the rail feel like a sequence of options rather than a gauntlet.

### Negative

- Users may use Job Search or Job Detail without ever uploading a resume, then be confused that Analysis still doesn't run. The Analysis page itself surfaces what's missing, but a user who doesn't reach Analysis won't see that. Acceptable trade — they can still get value from the parsed JD on its own, and the topbar's persistent stat pills ("Resume · not uploaded") signal what's missing.
- The supervised analysis pipeline still has its own gates (the Analysis page's "Upload a resume" affordance) — those weren't changed. So a user who tries to run analysis without a resume gets a clear "missing input" surface.

## Follow-Up

- Consider adding a "you've parsed a JD without a resume" callout on the Analysis page that nudges to Step 01.
- Watch the saved-jobs / Job Search analytics for users who browse extensively without uploading. If conversion lift on resume upload is meaningful, no further action; if it tanks, revisit whether a softer prompt on those pages is warranted.

## Related

- [ADR-017](ADR-017-workspace-assistant-state-aware-context.md): the workspace assistant now gets `current_step` and the `has_resume` / `has_jd` flags via its state-context payload, so it can give honest answers when a user asks "what should I do next?" while standing on Job Search with no resume.

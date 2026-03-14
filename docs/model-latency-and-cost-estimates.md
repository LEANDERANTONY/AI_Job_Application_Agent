# Model Routing, Latency, and Cost Estimates

## Decision Summary

This project should use two OpenAI model tiers by default:

- `gpt-5-mini-2025-08-07` for bounded structured synthesis tasks.
- `gpt-5.4` for the highest-trust, user-facing, hallucination-sensitive tasks.

`gpt-5.4-pro` is not recommended for the default product path because its price jump is too large for the current workload.

## Agent-to-Model Matrix

| Role | Recommended model | Why |
| --- | --- | --- |
| Profile Agent | `gpt-5-mini-2025-08-07` | Structured summary over normalized profile data. |
| Job Agent | `gpt-5-mini-2025-08-07` | JD summarization is bounded and low risk. |
| Fit Agent | `gpt-5-mini-2025-08-07` | Works from deterministic fit analysis and should stay cheap. |
| Tailoring Agent | `gpt-5-mini-2025-08-07` | Rewrites are constrained by upstream grounded context. |
| Strategy Agent | `gpt-5-mini-2025-08-07` | Useful but not the highest-risk surface. |
| Review Agent | `gpt-5.4` | Main hallucination brake and final quality gate. |
| Resume Generation Agent | `gpt-5.4` | Produces the direct user-facing artifact. |
| Product Help chat | `gpt-5-mini-2025-08-07` | Navigation and feature explanation should be low cost. |
| Application Q&A chat | `gpt-5.4` | Grounded explanation over the current package needs higher trust. |

## Pricing Reference Used

Published OpenAI pricing reviewed on March 14, 2026:

| Model | Input / 1M tokens | Output / 1M tokens |
| --- | ---: | ---: |
| `gpt-5.4` | `$2.50` | `$15.00` |
| `gpt-5-mini-2025-08-07` | `$0.25` | `$2.00` |
| `gpt-5.4-pro` | `$30.00` | `$180.00` |

## Measurement Basis

These estimates are not generic guesses. Prompt sizes were measured against the current prompt builders in this repository using:

- the real sample JD file at [static/demo_job_description/Sample_Job_Description_DataScientist.txt](static/demo_job_description/Sample_Job_Description_DataScientist.txt)
- a realistic synthetic resume profile created from the existing test pattern because [static/demo_resume](static/demo_resume) is currently empty except for `.gitkeep`
- the current prompt builders in [src/prompts.py](src/prompts.py)

Token counts are estimated from the built prompt text using local tokenization where available, with normal approximation fallback if a matching tokenizer is unavailable.

## Measured Prompt Sizes

| Role | Estimated prompt tokens | Estimated output tokens |
| --- | ---: | ---: |
| Profile Agent | `436` | `101` |
| Job Agent | `520` | `162` |
| Fit Agent | `1430` | `192` |
| Tailoring Agent | `1742` | `180` |
| Strategy Agent | `1719` | `339` |
| Review Agent | `1921` | `144` |
| Resume Generation Agent | `2162` | `156` |
| Product Help chat turn | `209` | `82` |
| Application Q&A chat turn | `1565` | `98` |

## Estimated Cost Per Call

| Role | Model | Estimated cost per call |
| --- | --- | ---: |
| Profile Agent | `gpt-5-mini-2025-08-07` | `$0.00031` |
| Job Agent | `gpt-5-mini-2025-08-07` | `$0.00045` |
| Fit Agent | `gpt-5-mini-2025-08-07` | `$0.00074` |
| Tailoring Agent | `gpt-5-mini-2025-08-07` | `$0.00080` |
| Strategy Agent | `gpt-5-mini-2025-08-07` | `$0.00111` |
| Review Agent | `gpt-5.4` | `$0.00696` |
| Resume Generation Agent | `gpt-5.4` | `$0.00775` |
| Product Help chat turn | `gpt-5-mini-2025-08-07` | `$0.00022` |
| Application Q&A chat turn | `gpt-5.4` | `$0.00538` |

## Estimated Cost Per User Session

### Single-pass supervised workflow

One clean supervised workflow run with no revision pass:

- Profile
- Job
- Fit
- Tailoring
- Strategy
- Review
- Resume Generation

Estimated total: `~$0.0181` per run.

Practical planning number: `~$0.02 to $0.03` after normal variance and hidden reasoning overhead.

### Workflow with one revision pass

One extra review loop adds:

- Tailoring
- Strategy
- Review

Additional estimated cost: `~$0.0089`

Total estimated workflow cost with one revision: `~$0.0270`

Practical planning number: `~$0.03 to $0.04`

### Typical active user session

Representative session:

- one supervised workflow run with one revision pass
- two Product Help turns
- two Application Q&A turns

Estimated total:

- workflow with one revision: `~$0.0270`
- two Product Help turns: `~$0.0004`
- two Application Q&A turns: `~$0.0108`

Combined estimate: `~$0.0382`

Practical planning number: `~$0.04 to $0.06` per serious session.

### Heavy user session

If a user repeatedly reruns the workflow, triggers multiple revisions, and asks several Application Q&A questions, a heavy session can move into the `~$0.08 to $0.15` range.

## Expected Latency Bands

These are product-level wall-clock estimates, not provider SLAs.

| Role class | Expected latency |
| --- | --- |
| Product Help on `gpt-5-mini-2025-08-07` | `~0.5s to 1.5s` |
| Profile / Job on `gpt-5-mini-2025-08-07` | `~1s to 2s` |
| Fit / Tailoring / Strategy on `gpt-5-mini-2025-08-07` | `~1.5s to 3.5s` |
| Review / Resume Generation on `gpt-5.4` | `~2s to 6s` |
| Application Q&A on `gpt-5.4` | `~2s to 5s` |

Sequential workflow estimate:

- single-pass workflow: `~10s to 22s`
- workflow with one revision: `~14s to 30s`

## Main Cost Drivers

The biggest cost multipliers in this app are:

- repeated inclusion of full normalized resume and JD context across multiple agents
- extra review loops
- Application Q&A turns that include the full workflow context again
- any future move to `gpt-5.4-pro`

## Recommended Guardrails

- Keep Product Help on the cheaper model.
- Keep the high-trust model only on Review, Resume Generation, and Application Q&A.
- Do not add more agents until the current agent set is clearly insufficient.
- If cost pressure rises, merge Strategy into Tailoring before weakening Review.
- Pin model snapshots in production where available.

## Implementation Notes

The code should route models per task instead of using a single global model. It should also use the Responses API instead of Chat Completions so the integration stays aligned with current OpenAI guidance and future model behavior.
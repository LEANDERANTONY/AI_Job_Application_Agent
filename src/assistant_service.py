from dataclasses import asdict, is_dataclass
import logging

from src.errors import AgentExecutionError
from src.logging_utils import get_logger, log_event
from src.product_knowledge import retrieve_product_knowledge
from src.prompts import (
    build_assistant_prompt,
    build_application_qa_assistant_prompt,
    build_product_help_assistant_prompt,
)
from src.config import get_openai_max_completion_tokens_for_task
from src.schemas import AssistantResponse


LOGGER = get_logger(__name__)


class AssistantService:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def answer(
        self,
        question,
        *,
        current_page,
        workflow_view_model=None,
        report=None,
        artifact=None,
        history=None,
        app_context=None,
        assistant_scope="assistant",
    ):
        product_context = {
            **(app_context or {}),
            "knowledge_hits": (app_context or {}).get(
                "knowledge_hits",
                retrieve_product_knowledge(question, current_page=current_page),
            ),
        }
        workflow_context = self._build_workflow_context(
            workflow_view_model,
            report=report,
            artifact=artifact,
        )
        assistant_context = {
            "assistant_scope": assistant_scope,
            "current_page": current_page,
            "product_context": product_context,
            "workflow_context": workflow_context,
        }
        if self._openai_service and self._openai_service.is_available():
            try:
                prompt = build_assistant_prompt(
                    assistant_context,
                    question,
                    history=history,
                )
                payload = self._openai_service.run_json_prompt(
                    prompt["system"],
                    prompt["user"],
                    expected_keys=prompt["expected_keys"],
                    temperature=None,
                    max_completion_tokens=get_openai_max_completion_tokens_for_task(
                        "assistant"
                    ),
                    task_name="assistant",
                    allow_output_budget_retry=False,
                )
                return self._build_response(payload, max_sources=4)
            except AgentExecutionError as exc:
                self._log_assistant_fallback("assistant", exc)
        return self._fallback_unified(
            question,
            current_page=current_page,
            workflow_view_model=workflow_view_model,
            artifact=artifact,
            report=report,
            app_context=product_context,
        )

    def answer_product_help(self, question, current_page, history=None, app_context=None):
        return self.answer(
            question,
            current_page=current_page,
            history=history,
            app_context=app_context,
            assistant_scope="product_help",
        )

    def answer_application_qa(self, question, workflow_view_model, report=None, artifact=None, history=None):
        return self.answer(
            question,
            current_page="Manual JD Input",
            workflow_view_model=workflow_view_model,
            report=report,
            artifact=artifact,
            history=history,
            assistant_scope="application_qa",
        )

    @staticmethod
    def _build_workflow_context(workflow_view_model, report=None, artifact=None):
        fit_analysis = getattr(workflow_view_model, "fit_analysis", None) if workflow_view_model else None
        agent_result = getattr(workflow_view_model, "agent_result", None) if workflow_view_model else None
        review = getattr(agent_result, "review", None) if agent_result else None
        cover_letter = getattr(agent_result, "cover_letter", None) if agent_result else None
        return {
            "job_description": AssistantService._to_context_payload(getattr(workflow_view_model, "job_description", None) if workflow_view_model else None),
            "candidate_profile": AssistantService._to_context_payload(getattr(workflow_view_model, "candidate_profile", None) if workflow_view_model else None),
            "fit_analysis": AssistantService._to_context_payload(fit_analysis),
            "tailored_draft": AssistantService._to_context_payload(getattr(workflow_view_model, "tailored_draft", None) if workflow_view_model else None),
            "agent_result": AssistantService._to_context_payload(agent_result),
            "report_summary": getattr(report, "summary", None),
            "tailored_resume_summary": getattr(artifact, "summary", None),
            "tailored_resume_validation_notes": getattr(artifact, "validation_notes", []),
            "cover_letter_summary": AssistantService._build_cover_letter_summary(cover_letter),
            "has_cover_letter": cover_letter is not None,
            "current_highlighted_skills": list(getattr(artifact, "highlighted_skills", []) or getattr(fit_analysis, "matched_hard_skills", [])[:6]),
            "fit_gaps": list(getattr(fit_analysis, "missing_hard_skills", []) or getattr(fit_analysis, "gaps", [])[:6]) if fit_analysis else [],
            "review_approved": bool(getattr(review, "approved", False)) if review else False,
            "review_revision_requests": list(getattr(review, "revision_requests", []) or []),
            "review_grounding_issues": list(getattr(review, "grounding_issues", []) or []),
        }

    @staticmethod
    def _build_application_qa_context(workflow_view_model, report=None, artifact=None):
        return AssistantService._build_workflow_context(
            workflow_view_model,
            report=report,
            artifact=artifact,
        )

    @staticmethod
    def _build_cover_letter_summary(cover_letter):
        if cover_letter is None:
            return None
        paragraphs = [
            str(getattr(cover_letter, "opening_paragraph", "")).strip(),
            *[str(item).strip() for item in getattr(cover_letter, "body_paragraphs", []) if str(item).strip()],
            str(getattr(cover_letter, "closing_paragraph", "")).strip(),
        ]
        paragraphs = [item for item in paragraphs if item]
        if not paragraphs:
            return None
        return " ".join(paragraphs[:2])

    @staticmethod
    def _to_context_payload(value):
        if value is None:
            return None
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "__dict__"):
            return dict(vars(value))
        return value

    @staticmethod
    def _build_response(payload, max_sources):
        answer = str(payload.get("answer", "")).strip()
        if not answer:
            raise AgentExecutionError(
                "The assistant returned an empty answer.",
                details=str(payload),
            )
        return AssistantResponse(
            answer=answer,
            sources=[str(item).strip() for item in payload.get("sources", []) if str(item).strip()][:max_sources],
            suggested_follow_ups=[str(item).strip() for item in payload.get("suggested_follow_ups", []) if str(item).strip()][:3],
        )

    @staticmethod
    def _log_assistant_fallback(task_name, exc):
        log_event(
            LOGGER,
            logging.WARNING,
            "assistant_fallback_used",
            "Assistant request fell back to deterministic response.",
            task_name=task_name,
            error_message=exc.user_message,
            details=exc.details,
        )

    @staticmethod
    def _fallback_unified(
        question,
        *,
        current_page,
        workflow_view_model=None,
        artifact=None,
        report=None,
        app_context=None,
    ):
        normalized = str(question or "").lower()
        app_context = app_context or {}
        knowledge_hits = list(app_context.get("knowledge_hits", []) or [])
        if "your name" in normalized or "who are you" in normalized:
            return AssistantResponse(
                answer="I am the in-app assistant for Application Copilot. I can explain how the product works and answer grounded questions about your current fit analysis, tailored resume, cover letter, and application package.",
                sources=[current_page, "Upload Resume", "Manual JD Input"],
                suggested_follow_ups=["How does the navigation work?", "What does Reload Workspace do?"],
            )
        if "navigation" in normalized or "nav" in normalized or "tab" in normalized or "sidebar" in normalized:
            return AssistantResponse(
                answer="The sidebar navigation is the main way to move through the product. Upload Resume is where you parse your resume, Job Search is the placeholder search entry, and Manual JD Input is where you load and analyze the target role. If you are signed in, the account panel also exposes Reload Workspace to restore your latest saved account snapshot directly into the JD flow.",
                sources=["Upload Resume", "Job Search", "Manual JD Input"],
                suggested_follow_ups=["What does Reload Workspace do?", "What happens after I reload a saved workspace?"],
            )
        if "resume" in normalized and ("upload" in normalized or "where" in normalized):
            resume_requires_login = bool(app_context.get("resume_upload_requires_login", False))
            is_signed_in = bool(app_context.get("is_authenticated", False))
            if resume_requires_login and not is_signed_in:
                return AssistantResponse(
                    answer="Start by signing in with Google from the sidebar. Resume upload is now login-first, so once you are signed in you can return to Upload Resume and upload your PDF, DOCX, or TXT resume.",
                    sources=["Upload Resume", "Account Panel"],
                    suggested_follow_ups=["Where do I sign in?", "What can I do after I log in?"],
                )
            return AssistantResponse(
                answer="Start on Upload Resume. Once you are signed in, upload your PDF, DOCX, or TXT resume, then move to Manual JD Input after the resume is parsed.",
                sources=["Upload Resume", "Manual JD Input"],
                suggested_follow_ups=["What happens after I upload my resume?", "How do I add a job description?"],
            )
        if "job description" in normalized or "jd" in normalized:
            return AssistantResponse(
                answer="Use Manual JD Input to upload a JD file or paste JD text directly. Once the JD is loaded, the app builds the fit snapshot, supervised workflow outputs, tailored resume, cover letter, and application package from that structured role data.",
                sources=["Manual JD Input", "Readiness Snapshot"],
                suggested_follow_ups=["What is the supervised workflow?", "What do I get at the end?"],
            )
        if "cover letter" in normalized or ("letter" in normalized and "cover" in normalized):
            return AssistantResponse(
                answer="The cover letter is a first-class artifact in the JD flow. After review-approved workflow outputs exist, it appears between Resume Preview and Application Package and can be downloaded as Markdown or PDF.",
                sources=["Cover Letter", "Resume Preview", "Application Package"],
                suggested_follow_ups=["Is the cover letter saved with the workspace?", "What inputs shape the cover letter?"],
            )
        if "report" in normalized or "application package" in normalized:
            return AssistantResponse(
                answer="Use the application package report to review the fit summary, strategy guidance, review notes, and rationale behind the tailored resume and cover letter wording. It is the explanation layer, while the tailored resume and cover letter are the direct-use artifacts.",
                sources=["Application Package", "Readiness Snapshot", "Tailored Resume Draft", "Cover Letter"],
                suggested_follow_ups=["What is the difference between the report and the resume?", "Can I download the report as PDF?"],
            )
        if "difference" in normalized or ("report" in normalized and "resume" in normalized):
            return AssistantResponse(
                answer="The tailored resume and cover letter are the direct-use artifacts, while the report explains the fit, strategy, review notes, and why those outputs were shaped that way. You can preview all of them in the page before downloading.",
                sources=["Tailored Resume Draft", "Cover Letter", "Application Package"],
                suggested_follow_ups=["Which one should I submit?", "Can I download the report as PDF?"],
            )
        if "template" in normalized or "theme" in normalized:
            return AssistantResponse(
                answer="The resume template changes the deterministic layout style of the tailored resume. Classic ATS is the safer parsing-first option, while Modern Professional adds a cleaner visual hierarchy.",
                sources=["Tailored Resume Draft"],
                suggested_follow_ups=["Which template is safer for ATS?", "Can I preview before downloading?"],
            )
        if (
            "budget" in normalized
            or "quota" in normalized
            or "token" in normalized
            or "limit" in normalized
            or ("ai" in normalized and "warning" in normalized)
        ):
            return AssistantResponse(
                answer="AI-assisted features are tied to your signed-in account and are governed by the daily quota for your plan. When that daily quota is exhausted, assisted features stay unavailable until the next UTC reset or until the plan tier changes.",
                sources=["Daily Workflow Runs Left", "Daily Capacity Left", "Quota State"],
                suggested_follow_ups=["What happens when the daily quota is exhausted?", "Which features require login?"],
            )
        if "job search" in normalized:
            return AssistantResponse(
                answer="Job Search is still a placeholder entry point. The active production path today is: sign in, upload a resume, load a job description, run the AI-assisted analysis, and then review the tailored outputs.",
                sources=["Job Search", "Upload Resume", "Manual JD Input"],
                suggested_follow_ups=["What is the current happy path?", "How do I generate both outputs?"],
            )
        if "saved workspace" in normalized or "reload workspace" in normalized or "restore" in normalized:
            return AssistantResponse(
                answer="Signed-in users keep one saved workspace snapshot for 24 hours. Reload Workspace restores the saved resume-backed candidate state, fit outputs, and any saved report, tailored resume, and cover letter artifacts back into the JD flow.",
                sources=["Reload Workspace", "Manual JD Input"],
                suggested_follow_ups=["How long does the saved workspace last?", "What gets restored into the JD page?"],
            )
        contextual_response = AssistantService._fallback_output_qa(
            normalized,
            workflow_view_model,
            artifact,
            report=report,
        )
        if contextual_response is not None:
            return contextual_response
        if knowledge_hits:
            primary_hit = knowledge_hits[0]
            return AssistantResponse(
                answer=primary_hit.get("content", "") or "The product context is available in the current page and saved knowledge documents.",
                sources=[str(item.get("source", "")).strip() for item in knowledge_hits if str(item.get("source", "")).strip()][:3],
                suggested_follow_ups=["Can you explain that step-by-step?", "What page should I use for that?"],
            )
        return AssistantResponse(
            answer="The current flow is: sign in, upload a resume, load a job description, review the fit snapshot, optionally run the AI-assisted analysis, inspect the tailored resume, cover letter, and application package, then download only the artifacts you want to keep.",
            sources=[current_page, "Readiness Snapshot", "Tailored Resume Draft", "Cover Letter", "Application Package"],
            suggested_follow_ups=["How do I use the AI-assisted analysis?", "What is the difference between the two outputs?"],
        )

    @staticmethod
    def _fallback_product_help(question, current_page, app_context=None):
        return AssistantService._fallback_unified(
            question,
            current_page=current_page,
            app_context=app_context,
        )

    @staticmethod
    def _fallback_output_qa(normalized, workflow_view_model, artifact, report=None):
        if not workflow_view_model or not workflow_view_model.candidate_profile or not workflow_view_model.job_description:
            if any(keyword in normalized for keyword in ("resume", "report", "cover letter", "fit", "submit", "gap", "bullet", "rewrite")):
                return AssistantResponse(
                    answer="The assistant needs both a resume and a job description loaded first. Once those are available, I can answer grounded questions about the fit snapshot, tailored resume, cover letter, and application package.",
                    sources=["Upload Resume", "Manual JD Input"],
                    suggested_follow_ups=["How do I load the job description?", "What happens after I upload a resume?"],
                )
            return None

        fit_analysis = workflow_view_model.fit_analysis
        agent_result = workflow_view_model.agent_result
        highlighted_skills = list(
            (getattr(artifact, "highlighted_skills", None) or fit_analysis.matched_hard_skills)[:4]
        )
        fit_gaps = list((fit_analysis.missing_hard_skills or fit_analysis.gaps)[:4])

        if (
            "cross-functional" in normalized
            or "collaboration" in normalized
            or "without experience" in normalized
            or "without formal" in normalized
            or "transferable" in normalized
            or "frame" in normalized
            or "position" in normalized
        ):
            return AssistantResponse(
                answer=(
                    "General advice: describe collaboration through outcomes, stakeholders, and handoffs rather than through job-title labels alone. "
                    "Use bullets that show who you worked with, what decision or deliverable moved forward, and how your contribution improved the result. "
                    "Context-specific recommendation: in your current package, anchor that story to {skills} and keep any weaker areas like {gaps} framed as adjacent or transferable evidence rather than direct claims you cannot support."
                ).format(
                    skills=", ".join(highlighted_skills) or "your strongest matched skills",
                    gaps=", ".join(fit_gaps) or "remaining JD gaps",
                ),
                sources=["Candidate Profile", "Readiness Snapshot", "Tailored Resume Draft"],
                suggested_follow_ups=[
                    "Can you help me rewrite one bullet with that framing?",
                    "Which collaboration examples in my package look strongest?",
                ],
            )

        if "missing" in normalized or "gap" in normalized or "weak" in normalized:
            return AssistantResponse(
                answer=(
                    "The main gaps right now are: {gaps}. These come from the fit analysis against the JD, so they are the highest-friction areas to strengthen with real evidence."
                ).format(gaps=", ".join(fit_gaps) or "no major gaps surfaced"),
                sources=["Deterministic Fit Analysis", "Readiness Snapshot"],
                suggested_follow_ups=["How should I address these gaps honestly?", "Which of these gaps matter most?"],
            )
        if "why" in normalized or "change" in normalized or "rewrite" in normalized or "bullet" in normalized:
            return AssistantResponse(
                answer=(
                    "The tailored resume was shaped to emphasize verified alignment with the JD, especially around {skills}. The change summary and comparison view show what moved, and the report explains the reasoning behind those adjustments."
                ).format(skills=", ".join(highlighted_skills) or "the strongest matched skills"),
                sources=["Tailored Resume Draft", "Change Summary", "Application Package"],
                suggested_follow_ups=["Is this claim grounded in my resume?", "What should I verify before submitting?"],
            )
        if "safe" in normalized or "grounded" in normalized or "submit" in normalized:
            approval_text = "approved by the review stage" if agent_result and agent_result.review.approved else "not fully approved by the review stage yet"
            return AssistantResponse(
                answer=(
                    "The current tailored resume is {approval}, and you should still review the validation notes before submitting. The safest path is to check any highlighted wording against your original resume evidence and keep unsupported claims out."
                ).format(approval=approval_text),
                sources=["Review Notes", "Validation Notes", "Compare Original vs Tailored Resume"],
                suggested_follow_ups=["What should I verify manually?", "Which lines look least supported?"],
            )
        if "which" in normalized and ("output" in normalized or "download" in normalized):
            return AssistantResponse(
                answer="Use the tailored resume if you want a ready-to-use JD-aligned resume, use the cover letter if you also want role-specific outreach text, use the report if you want the reasoning and improvement guidance, or use the combined export if you want everything together.",
                sources=["Tailored Resume Draft", "Cover Letter", "Application Package", "Combined Export"],
                suggested_follow_ups=["Can I preview both before downloading?", "Which one is better for manual editing?"],
            )
        return AssistantResponse(
            answer=(
                "Right now your package centers on a fit score of {score}/100 with readiness marked as {label}. The tailored resume emphasizes {skills}, the cover letter follows the approved workflow outputs when available, and the report captures the broader strategy and review context."
            ).format(
                score=fit_analysis.overall_score,
                label=fit_analysis.readiness_label,
                skills=", ".join(highlighted_skills) or "the strongest matched skills",
            ),
            sources=["Readiness Snapshot", "Tailored Resume Draft", "Cover Letter", "Application Package"],
            suggested_follow_ups=["What are my biggest remaining gaps?", "Why were these skills emphasized?"],
        )

    @staticmethod
    def _fallback_application_qa(question, workflow_view_model, artifact):
        return AssistantService._fallback_output_qa(
            str(question or "").lower(),
            workflow_view_model,
            artifact,
        ) or AssistantService._fallback_unified(
            question,
            current_page="Manual JD Input",
            workflow_view_model=workflow_view_model,
            artifact=artifact,
        )

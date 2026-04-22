from dataclasses import asdict, is_dataclass
import hashlib
import json
import logging

from src.errors import AgentExecutionError
from src.logging_utils import get_logger, log_event
from src.product_knowledge import retrieve_product_knowledge
from src.prompts import (
    build_assistant_prompt,
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
        workflow_context = self._build_application_qa_context(
            workflow_view_model,
            report=report,
            artifact=artifact,
        )
        assistant_context = {
            "assistant_scope": "assistant",
            "current_page": current_page,
            "product_context": product_context,
            "workflow_context": workflow_context,
        }
        if self._openai_service and self._openai_service.is_available():
            try:
                task_name = "assistant"
                prompt = build_assistant_prompt(
                    assistant_context,
                    question,
                    history=self._compact_history(history),
                )
                payload = self._openai_service.run_json_prompt(
                    prompt["system"],
                    prompt["user"],
                    expected_keys=prompt["expected_keys"],
                    temperature=None,
                    max_completion_tokens=get_openai_max_completion_tokens_for_task(
                        task_name
                    ),
                    task_name=task_name,
                    allow_output_budget_retry=False,
                )
                return self._build_response(payload, max_sources=4)
            except AgentExecutionError as exc:
                self._log_assistant_fallback(task_name, exc)
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

    def prepare_session(
        self,
        *,
        current_page,
        workflow_view_model=None,
        report=None,
        artifact=None,
        app_context=None,
    ):
        if not self._openai_service or not self._openai_service.is_available():
            return None

        assistant_context = self.build_session_context(
            current_page=current_page,
            workflow_view_model=workflow_view_model,
            report=report,
            artifact=artifact,
            app_context=app_context,
        )
        prompt = build_assistant_prompt(
            assistant_context,
            "Prepare for upcoming user questions in this session. Confirm briefly that the current app context is loaded.",
            history=None,
        )
        self._openai_service.run_json_prompt(
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
        snapshot = self._openai_service.get_usage_snapshot()
        return snapshot.get("last_response_metadata", {}).get("response_id")

    @classmethod
    def build_session_context(
        cls,
        *,
        current_page,
        workflow_view_model=None,
        report=None,
        artifact=None,
        app_context=None,
    ):
        product_context = dict(app_context or {})
        product_context.pop("knowledge_hits", None)
        workflow_context = None
        if workflow_view_model and getattr(workflow_view_model, "job_description", None):
            workflow_context = cls._build_application_qa_context(
                workflow_view_model,
                report=report,
                artifact=artifact,
            )
        return {
            "assistant_scope": "assistant",
            "current_page": current_page,
            "product_context": product_context,
            "workflow_context": workflow_context,
        }

    @staticmethod
    def build_session_signature(session_context):
        normalized = json.dumps(session_context or {}, sort_keys=True, default=str)
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

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
        fit_analysis = getattr(workflow_view_model, "fit_analysis", None) if workflow_view_model else None
        agent_result = getattr(workflow_view_model, "agent_result", None) if workflow_view_model else None
        review = getattr(agent_result, "review", None) if agent_result else None
        cover_letter = getattr(agent_result, "cover_letter", None) if agent_result else None
        job_description = getattr(workflow_view_model, "job_description", None) if workflow_view_model else None
        candidate_profile = getattr(workflow_view_model, "candidate_profile", None) if workflow_view_model else None
        tailored_draft = getattr(workflow_view_model, "tailored_draft", None) if workflow_view_model else None
        return {
            "job": {
                "title": getattr(job_description, "title", ""),
                "location": getattr(job_description, "location", ""),
                "hard_skills": list(getattr(getattr(job_description, "requirements", None), "hard_skills", [])[:8]),
                "soft_skills": list(getattr(getattr(job_description, "requirements", None), "soft_skills", [])[:6]),
                "experience_requirement": getattr(
                    getattr(job_description, "requirements", None),
                    "experience_requirement",
                    None,
                ),
            },
            "candidate": {
                "name": getattr(candidate_profile, "full_name", ""),
                "location": getattr(candidate_profile, "location", ""),
                "skills": list(getattr(candidate_profile, "skills", [])[:10]),
                "current_role": AssistantService._build_current_role_summary(candidate_profile),
            },
            "fit": {
                "overall_score": getattr(fit_analysis, "overall_score", None),
                "readiness_label": getattr(fit_analysis, "readiness_label", ""),
                "matched_hard_skills": list(getattr(fit_analysis, "matched_hard_skills", [])[:6]) if fit_analysis else [],
                "missing_hard_skills": list(getattr(fit_analysis, "missing_hard_skills", [])[:6]) if fit_analysis else [],
                "strengths": list(getattr(fit_analysis, "strengths", [])[:4]) if fit_analysis else [],
                "gaps": list(getattr(fit_analysis, "gaps", [])[:4]) if fit_analysis else [],
            },
            "tailored_resume": {
                "summary": getattr(artifact, "summary", None),
                "highlighted_skills": list(
                    getattr(artifact, "highlighted_skills", [])[:6]
                ) if artifact else list(getattr(tailored_draft, "highlighted_skills", [])[:6]) if tailored_draft else [],
                "validation_notes": list(getattr(artifact, "validation_notes", [])[:4]) if artifact else [],
            },
            "report_summary": getattr(report, "summary", None),
            "cover_letter_summary": AssistantService._build_cover_letter_summary(cover_letter),
            "review": {
                "approved": bool(getattr(review, "approved", False)) if review else False,
                "revision_requests": list(getattr(review, "revision_requests", [])[:4]) if review else [],
                "grounding_issues": list(getattr(review, "grounding_issues", [])[:4]) if review else [],
            },
        }

    @staticmethod
    def _build_current_role_summary(candidate_profile):
        experience = list(getattr(candidate_profile, "experience", []) or [])
        if not experience:
            return ""
        latest = experience[0]
        title = str(getattr(latest, "title", "") or "").strip()
        organization = str(getattr(latest, "organization", "") or "").strip()
        if title and organization:
            return f"{title} at {organization}"
        return title or organization

    @staticmethod
    def _compact_history(history):
        compacted = []
        for turn in list(history or [])[-3:]:
            question = str(getattr(turn, "question", "") or "").strip()
            answer = str(getattr(getattr(turn, "response", None), "answer", "") or "").strip()
            if not question and not answer:
                continue
            compacted.append(
                {
                    "question": question[:240],
                    "answer": answer[:320],
                }
            )
        return compacted

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
        if (
            "how does the app work" in normalized
            or "how the app works" in normalized
            or "full flow" in normalized
            or "overall flow" in normalized
            or "whole flow" in normalized
        ):
            return AssistantResponse(
                answer=(
                    "The main flow is: sign in, upload your resume on Upload Resume, then either search/import a role from Job Search or paste/upload a JD in Manual JD Input. "
                    "Once the job description is loaded, the app builds a fit snapshot, tailored resume draft, cover letter, and application package report. "
                    "You review those outputs in the same JD flow, download the artifacts you want, and if you are signed in the latest workspace can be reloaded for 24 hours. "
                    "Job Search is just one entry path into that larger workflow."
                ),
                sources=["Upload Resume", "Job Search", "Manual JD Input", "Readiness Snapshot", "Application Package"],
                suggested_follow_ups=["What exactly happens after I upload my resume?", "What is the difference between Job Search and Manual JD Input?"],
            )
        if "navigation" in normalized or "nav" in normalized or "tab" in normalized or "sidebar" in normalized:
            return AssistantResponse(
                answer="The sidebar navigation is the main way to move through the product. Upload Resume is where you parse your resume, Job Search is where you search or import supported roles, and Manual JD Input is where you load and analyze the target role. If you are signed in, the account panel also exposes Reload Workspace to restore your latest saved account snapshot directly into the JD flow.",
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
                answer="Use Job Search to search configured technical-role sources, paste a supported job URL, or shortlist interesting roles for later. Once you choose a role, load it into the JD flow and continue through the same analysis, resume, cover letter, and application-strategy path.",
                sources=["Job Search", "Upload Resume", "Manual JD Input"],
                suggested_follow_ups=["Can I save jobs for later?", "What happens after I load a role into the JD flow?"],
            )
        if "saved workspace" in normalized or "reload workspace" in normalized or "restore" in normalized:
            return AssistantResponse(
                answer="Signed-in users keep one saved workspace snapshot for 24 hours. Reload Workspace restores the saved resume-backed candidate state, fit outputs, imported job context when applicable, and any saved report, tailored resume, and cover letter artifacts back into the JD flow.",
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
        fit_summary_text = fit_analysis if isinstance(fit_analysis, str) else ""
        fit_skills = getattr(fit_analysis, "matched_hard_skills", None)
        fit_missing_skills = getattr(fit_analysis, "missing_hard_skills", None)
        fit_gap_labels = getattr(fit_analysis, "gaps", None)
        fit_score = getattr(fit_analysis, "overall_score", None)
        readiness_label = getattr(fit_analysis, "readiness_label", None)

        highlighted_skills = list(
            (getattr(artifact, "highlighted_skills", None) or fit_skills or [])[:4]
        )
        fit_gaps = list((fit_missing_skills or fit_gap_labels or [])[:4])
        fit_score_text = str(fit_score) if fit_score is not None else "an unavailable"
        readiness_label_text = readiness_label or "not yet classified"

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
                ).format(
                    gaps=", ".join(fit_gaps)
                    or fit_summary_text
                    or "no major gaps surfaced"
                ),
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
                score=fit_score_text,
                label=readiness_label_text,
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

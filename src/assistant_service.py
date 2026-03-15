from dataclasses import asdict
import logging

from src.errors import AgentExecutionError
from src.logging_utils import get_logger, log_event
from src.prompts import (
    build_application_qa_assistant_prompt,
    build_product_help_assistant_prompt,
)
from src.config import get_openai_max_completion_tokens_for_task
from src.schemas import AssistantResponse


LOGGER = get_logger(__name__)


class AssistantService:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def answer_product_help(self, question, current_page, history=None, app_context=None):
        app_context = app_context or {}
        if self._openai_service and self._openai_service.is_available():
            try:
                prompt = build_product_help_assistant_prompt(
                    {
                        "current_page": current_page,
                        **app_context,
                    },
                    question,
                    history=history,
                )
                payload = self._openai_service.run_json_prompt(
                    prompt["system"],
                    prompt["user"],
                    expected_keys=prompt["expected_keys"],
                    temperature=None,
                    max_completion_tokens=get_openai_max_completion_tokens_for_task(
                        "assistant_product_help"
                    ),
                    task_name="assistant_product_help",
                    allow_output_budget_retry=False,
                )
                return self._build_response(payload, max_sources=3)
            except AgentExecutionError as exc:
                self._log_assistant_fallback("assistant_product_help", exc)
        return self._fallback_product_help(question, current_page)

    def answer_application_qa(self, question, workflow_view_model, report=None, artifact=None, history=None):
        if self._openai_service and self._openai_service.is_available():
            try:
                prompt = build_application_qa_assistant_prompt(
                    {
                        "job_description": asdict(workflow_view_model.job_description) if workflow_view_model and workflow_view_model.job_description else None,
                        "candidate_profile": asdict(workflow_view_model.candidate_profile) if workflow_view_model and workflow_view_model.candidate_profile else None,
                        "fit_analysis": asdict(workflow_view_model.fit_analysis) if workflow_view_model and workflow_view_model.fit_analysis else None,
                        "tailored_draft": asdict(workflow_view_model.tailored_draft) if workflow_view_model and workflow_view_model.tailored_draft else None,
                        "agent_result": asdict(workflow_view_model.agent_result) if workflow_view_model and workflow_view_model.agent_result else None,
                        "report_summary": getattr(report, "summary", None),
                        "tailored_resume_summary": getattr(artifact, "summary", None),
                        "tailored_resume_validation_notes": getattr(artifact, "validation_notes", []),
                    },
                    question,
                    history=history,
                )
                payload = self._openai_service.run_json_prompt(
                    prompt["system"],
                    prompt["user"],
                    expected_keys=prompt["expected_keys"],
                    temperature=0.2,
                    max_completion_tokens=get_openai_max_completion_tokens_for_task(
                        "assistant_application_qa"
                    ),
                    task_name="assistant_application_qa",
                )
                return self._build_response(payload, max_sources=4)
            except AgentExecutionError as exc:
                self._log_assistant_fallback("assistant_application_qa", exc)
        return self._fallback_application_qa(question, workflow_view_model, artifact)

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
    def _fallback_product_help(question, current_page):
        normalized = str(question or "").lower()
        if "your name" in normalized or "who are you" in normalized:
            return AssistantResponse(
                answer="I am the in-app Product Help Assistant for the AI Job Application Agent. I can explain the current workflow, navigation, saved workspace behavior, and the difference between the generated outputs.",
                sources=[current_page, "Upload Resume", "Manual JD Input"],
                suggested_follow_ups=["How does the navigation work?", "What does Reload Saved Workspace do?"],
            )
        if "navigation" in normalized or "nav" in normalized or "tab" in normalized or "sidebar" in normalized:
            return AssistantResponse(
                answer="The sidebar navigation is the main way to move through the product. Upload Resume is where you parse your resume, Job Search is the placeholder search entry, Manual JD Input is where you load and analyze the target role, and Saved Workspace lets you inspect the latest saved account snapshot. If you are signed in, the account panel can also expose Reload Saved Workspace to restore that saved state back into Manual JD Input.",
                sources=["Upload Resume", "Job Search", "Manual JD Input"],
                suggested_follow_ups=["What does Saved Workspace do?", "What does Reload Saved Workspace do?"],
            )
        if "resume" in normalized and ("upload" in normalized or "where" in normalized):
            return AssistantResponse(
                answer="Start on Upload Resume. You can choose a sample file or upload your own PDF, DOCX, or TXT resume, then move to Manual JD Input once the resume is parsed.",
                sources=["Upload Resume", "Manual JD Input"],
                suggested_follow_ups=["What happens after I upload my resume?", "How do I add a job description?"],
            )
        if "job description" in normalized or "jd" in normalized:
            return AssistantResponse(
                answer="Use Manual JD Input to upload a JD file, select a sample JD, or paste JD text directly. Once the JD is loaded, the app builds the fit snapshot and tailored outputs from that structured role data.",
                sources=["Manual JD Input", "Readiness Snapshot"],
                suggested_follow_ups=["What is the supervised workflow?", "What do I get at the end?"],
            )
        if "difference" in normalized or ("report" in normalized and "resume" in normalized):
            return AssistantResponse(
                answer="The tailored resume is the direct-use artifact, while the report explains the fit, strategy, review notes, and why the resume was shaped that way. You can preview both in the page before downloading either one.",
                sources=["Tailored Resume Draft", "Application Package", "Combined Export"],
                suggested_follow_ups=["Which one should I submit?", "Can I download both together?"],
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
                answer="The app has two separate assisted limits. First, there is a browser-session budget that tracks model calls and tokens for the current session. Second, signed-in users can also have an account-level daily quota. If either limit is reached, the app can downgrade assisted features to deterministic fallback mode until the session resets, the next UTC quota window starts, or the plan tier is changed.",
                sources=["Browser Session Runs Left", "Daily Workflow Runs Left", "Quota State"],
                suggested_follow_ups=["What runs without AI?", "What happens when the daily quota is exhausted?"],
            )
        if "job search" in normalized:
            return AssistantResponse(
                answer="Job Search is still a placeholder entry point. The active production path today is resume upload, JD input, fit analysis, supervised workflow, and export.",
                sources=["Job Search", "Upload Resume", "Manual JD Input"],
                suggested_follow_ups=["What is the current happy path?", "How do I generate both outputs?"],
            )
        return AssistantResponse(
            answer="The current flow is: upload a resume, load a job description, review the fit snapshot, optionally run the supervised workflow, inspect the tailored resume and report, then download only if you want to keep them.",
            sources=[current_page, "Readiness Snapshot", "Tailored Resume Draft", "Application Package"],
            suggested_follow_ups=["How do I use the supervised workflow?", "What is the difference between the two outputs?"],
        )

    @staticmethod
    def _fallback_application_qa(question, workflow_view_model, artifact):
        normalized = str(question or "").lower()
        if not workflow_view_model or not workflow_view_model.candidate_profile or not workflow_view_model.job_description:
            return AssistantResponse(
                answer="Application Q&A needs both a resume and a job description loaded first. Once those are available, I can answer questions about the fit snapshot, tailored resume, and report.",
                sources=["Upload Resume", "Manual JD Input"],
                suggested_follow_ups=["How do I load the job description?", "What happens after I upload a resume?"],
            )

        fit_analysis = workflow_view_model.fit_analysis
        agent_result = workflow_view_model.agent_result

        if "missing" in normalized or "gap" in normalized or "weak" in normalized:
            return AssistantResponse(
                answer=(
                    "The main gaps right now are: {gaps}. These come from the fit analysis against the JD, so they are the highest-friction areas to strengthen with real evidence."
                ).format(gaps=", ".join((fit_analysis.missing_hard_skills or fit_analysis.gaps)[:4]) or "no major gaps surfaced"),
                sources=["Deterministic Fit Analysis", "Readiness Snapshot"],
                suggested_follow_ups=["How should I address these gaps honestly?", "Which of these gaps matter most?"],
            )
        if "why" in normalized or "change" in normalized or "rewrite" in normalized or "bullet" in normalized:
            return AssistantResponse(
                answer=(
                    "The tailored resume was shaped to emphasize verified alignment with the JD, especially around {skills}. The change summary and comparison view show what moved, and the report explains the reasoning behind those adjustments."
                ).format(skills=", ".join((artifact.highlighted_skills if artifact else [])[:4]) or "the strongest matched skills"),
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
                answer="Use the tailored resume if you want a ready-to-use JD-aligned resume, use the report if you want the reasoning and improvement guidance, or use the combined export if you want both together.",
                sources=["Tailored Resume Draft", "Application Package", "Combined Export"],
                suggested_follow_ups=["Can I preview both before downloading?", "Which one is better for manual editing?"],
            )
        return AssistantResponse(
            answer=(
                "Right now your package centers on a fit score of {score}/100 with readiness marked as {label}. The tailored resume emphasizes {skills}, and the report captures the broader strategy and review context."
            ).format(
                score=fit_analysis.overall_score,
                label=fit_analysis.readiness_label,
                skills=", ".join((artifact.highlighted_skills if artifact else fit_analysis.matched_hard_skills)[:4]) or "the strongest matched skills",
            ),
            sources=["Readiness Snapshot", "Tailored Resume Draft", "Application Package"],
            suggested_follow_ups=["What are my biggest remaining gaps?", "Why were these skills emphasized?"],
        )
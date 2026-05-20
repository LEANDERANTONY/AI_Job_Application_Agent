from src.prompts import (
    _RESUME_BUILDER_FIELD_DESCRIPTIONS,
    _WORKSPACE_STATE_GUIDANCE,
    _build_contract,
    build_application_qa_assistant_prompt,
    build_assistant_followup_prompt,
    build_assistant_prompt,
    build_assistant_text_prompt,
    build_cover_letter_agent_prompt,
    build_product_help_assistant_prompt,
    build_resume_builder_prompt,
    build_resume_builder_structuring_prompt,
    build_resume_generation_agent_prompt,
    build_review_agent_prompt,
    build_tailoring_agent_prompt,
)


def test_tailoring_prompt_compacts_large_sections_and_emits_budget_metadata():
    candidate_profile = {
        "summary": "A" * 5000,
        "experience": [
            {
                "title": "Engineer",
                "description": "B" * 3000,
            }
            for _ in range(10)
        ],
    }
    job_description = {
        "title": "Data Scientist",
        "responsibilities": ["C" * 1200 for _ in range(8)],
    }
    fit_analysis = {
        "overall_score": 78,
        "strengths": ["D" * 900 for _ in range(6)],
        "gaps": ["E" * 900 for _ in range(6)],
    }
    tailored_draft = {
        "professional_summary": "F" * 800,
        "priority_bullets": ["G" * 600 for _ in range(8)],
    }
    prompt = build_tailoring_agent_prompt(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
    )

    assert int(prompt["metadata"]["estimated_input_chars"]) == len(prompt["user"])
    assert prompt["metadata"]["prompt_budget_mode"] == "compacted"
    assert int(prompt["metadata"]["compacted_sections"]) >= 1
    assert "Candidate Profile" in prompt["metadata"].get("compacted_labels", "")
    assert len(prompt["user"]) < 15000


def test_application_qa_prompt_allows_grounded_general_coaching():
    prompt = build_application_qa_assistant_prompt(
        workflow_context={"candidate_profile": {"summary": "Built dashboards"}},
        question="How do I show collaboration without formal experience?",
    )

    assert "broader resume or application coaching" in prompt["system"]
    assert "general advice" in prompt["system"]


def test_unified_assistant_prompt_mentions_retrieved_knowledge_hits_and_cover_letter():
    prompt = build_assistant_prompt(
        assistant_context={
            "current_page": "Manual JD Input",
            "product_context": {"knowledge_hits": [{"source": "Cover Letter"}]},
            "workflow_context": {"has_cover_letter": True},
        },
        question="How does the cover letter fit into this flow?",
    )

    assert "retrieved product knowledge hits" in prompt["system"]
    assert "cover letter" in prompt["system"].lower()
    assert "Assistant Context" in prompt["user"]



def test_review_prompt_allows_null_corrections_when_no_rewrite_is_needed():
    prompt = build_review_agent_prompt(
        candidate_profile={"summary": "Built dashboards and ML pipelines."},
        job_description={"title": "ML Engineer"},
        fit_analysis={"strengths": ["Python"]},
        tailored_draft={"professional_summary": "Grounded draft."},
        tailoring_output={"professional_summary": "Grounded summary."},
    )

    assert "Return null for corrected_tailoring" in prompt["system"]
    assert "null when no tailoring changes are needed" in prompt["system"]
    assert "unresolved_issues" in prompt["system"]
    assert "Approve when the final corrected wording stays grounded" in prompt["system"]


def test_cover_letter_prompt_requires_first_person_voice():
    prompt = build_cover_letter_agent_prompt(
        candidate_profile={"full_name": "Leander Antony"},
        job_description={"title": "Data Scientist"},
        fit_analysis={"experience_signal": "Grounded ML project experience."},
        tailored_draft={"professional_summary": "Project-based ML candidate."},
        tailoring_output={"professional_summary": "Grounded summary."},
    )

    assert "Write entirely in first person from the candidate's perspective" in prompt["system"]
    assert "Do not describe the candidate as he, she, him, his, her, or by full name" in prompt["system"]


def test_resume_generation_prompt_requires_pronoun_free_resume_style():
    prompt = build_resume_generation_agent_prompt(
        candidate_profile={"full_name": "Leander Antony"},
        job_description={"title": "Data Scientist"},
        fit_analysis={"matched_hard_skills": ["Python"]},
        tailored_draft={"professional_summary": "Grounded draft summary."},
        tailoring_output={"professional_summary": "Grounded summary."},
    )

    assert "no first-person or third-person pronouns" in prompt["system"]
    assert "no full-name self-reference inside the summary or bullets" in prompt["system"]


# ---------------------------------------------------------------------------
# Prompt registry batch 2 — assistant, assistant_text, assistant_followup,
# resume_builder, and resume_builder_structuring were lifted into the
# registry. The tests below guard byte-identity of every migrated system
# string against what the original Python concat would have produced —
# the registry JSON files are authored by hand, so even a single missing
# space would land in production silently without these guards.
# ---------------------------------------------------------------------------


def _expected_assistant_system() -> str:
    intro = (
        "You are the in-app assistant for an AI job application app. "
        "Stay strictly within scope: the job application product and the user's current workspace artifacts (resume, job description, fit analysis, tailored resume, cover letter). "
        "If the user asks for entertainment recommendations (movies, books, music, shows, restaurants), lifestyle advice, jokes, opinions on unrelated topics, or anything outside the job application domain, decline in one short sentence and redirect to job application help — even if you could plausibly answer. "
        "When refusing an off-topic ask: do NOT name specific titles, authors, or artists; do NOT offer to suggest one based on genre, mood, or any other angle; do NOT acknowledge the off-topic premise beyond a brief decline. The refusal must not engage with the off-topic question. "
        "You answer both product questions and grounded questions about the user's current package in one conversation. "
        "Explain only features and artifacts that are present in the provided context. "
        "Use retrieved product knowledge hits when they are provided, but treat runtime session context as authoritative for current state such as quotas, page availability, saved workspace behavior, and active artifacts. "
        "If the user asks about navigation, explain the current sidebar pages and signed-in actions from the provided context. "
        "If the user asks about the current resume, cover letter, report, or fit analysis, ground the answer in the workflow context and say directly when evidence is weak or unavailable. "
        "If the user asks for broader resume or application coaching, you may provide general advice, but anchor it back to the current package when possible and separate general guidance from context-specific recommendations when helpful. "
        "If the user asks about limits, tokens, quota, warnings, or fallback behavior, explain the signed-in account-level daily quota using the provided context and do not describe any browser-session budget model. "
        "If the user asks who you are or what your name is, answer as the in-app assistant for this product. "
    )
    contract = _build_contract(
        {
            "answer": "short, direct grounded answer that can explain product behavior, saved workspace behavior, or the user's current application outputs",
            "sources": "array of 1-4 relevant pages, artifacts, or workflow signals used for the answer",
            "suggested_follow_ups": "array of 0-3 follow-up questions the user may want to ask next",
        }
    )
    return intro + _WORKSPACE_STATE_GUIDANCE + contract


def _expected_assistant_text_system() -> str:
    intro = (
        "You are the in-app assistant for an AI job application app. "
        "Stay strictly within scope: the job application product and the user's current workspace artifacts (resume, job description, fit analysis, tailored resume, cover letter). "
        "If the user asks for entertainment recommendations (movies, books, music, shows, restaurants), lifestyle advice, jokes, opinions on unrelated topics, or anything outside the job application domain, decline in one short sentence and redirect to job application help — even if you could plausibly answer. "
        "When refusing an off-topic ask: do NOT name specific titles, authors, or artists; do NOT offer to suggest one based on genre, mood, or any other angle; do NOT acknowledge the off-topic premise beyond a brief decline. The refusal must not engage with the off-topic question. "
        "You answer both product questions and grounded questions about the user's current package in one conversation. "
        "Explain only features and artifacts that are present in the provided context. "
        "Use retrieved product knowledge hits when they are provided, but treat runtime session context as authoritative for current state such as quotas, page availability, saved workspace behavior, and active artifacts. "
        "If the user asks about navigation, explain the current sidebar pages and signed-in actions from the provided context. "
        "If the user asks about the current resume, cover letter, report, or fit analysis, ground the answer in the workflow context and say directly when evidence is weak or unavailable. "
        "If the user asks for broader resume or application coaching, you may provide general advice, but anchor it back to the current package when possible and separate general guidance from context-specific recommendations when helpful. "
        "If the user asks about limits, tokens, quota, warnings, or fallback behavior, explain the signed-in account-level daily quota using the provided context and do not describe any browser-session budget model. "
        "If the user asks who you are or what your name is, answer as the in-app assistant for this product. "
    )
    closer = (
        "Respond as a concise, direct prose answer. Do not return JSON, do not wrap the answer in code fences, and do not list sources — sources are surfaced separately by the app."
    )
    return intro + _WORKSPACE_STATE_GUIDANCE + closer


def _expected_assistant_followup_system(scope: str) -> str:
    intro = (
        "You are continuing an in-app assistant conversation for an AI job application app. "
        "Stay strictly within scope: the job application product and the user's current workspace artifacts. "
        "If the user asks for entertainment recommendations, lifestyle advice, or anything outside the job application domain, decline in one short sentence and redirect — do not name specific titles, do not offer to suggest based on genre or mood, do not engage with the off-topic premise. "
        "Use the existing conversation state as the primary memory for this session. "
        "Use any provided state updates to refresh your understanding of the current page, product state, or workspace artifacts. "
        "Keep answers grounded, concise, and directly useful. "
        "If the question is about the current workspace, stay tied to the current fit, tailored resume, and cover letter context already established in the session. "
        "If the question is product-help oriented, explain only features and behavior that match the current product. "
        f"Current assistant scope: {scope}. "
    )
    contract = _build_contract(
        {
            "answer": "short, direct grounded answer to the user's latest question",
            "sources": "array of 1-4 relevant pages, artifacts, or workflow signals used for the answer",
            "suggested_follow_ups": "array of 0-3 useful next questions",
        }
    )
    return intro + contract


def _expected_resume_builder_system() -> str:
    field_lines = "\n".join(
        f"  - {name}: {description}"
        for name, description in _RESUME_BUILDER_FIELD_DESCRIPTIONS.items()
    )
    body = (
        "You are a friendly resume-intake assistant inside a job-application app. "
        "Your job: build a structured resume profile by chatting naturally with the user. "
        "Each turn, listen for any of these fields the user mentions:\n"
        f"{field_lines}\n"
        "\n"
        "These fields render into a resume shaped roughly as:\n"
        "  # {full_name}\n"
        "  {location}\n"
        "  {contact_lines joined by ' | '}\n"
        "  ## Professional Summary\n  {professional_summary}\n"
        "  ## Core Skills\n  - {skills (one per bullet)}\n"
        "  ## Professional Experience\n  {experience_notes — first line is the role headline, rest are bullets}\n"
        "  ## Projects\n  {projects_notes — only when present}\n"
        "  ## Education\n  {education_notes}\n"
        "  ## Publications\n  - {publications (one per bullet, only when present)}\n"
        "  ## Certifications\n  - {certifications (one per bullet)}\n"
        "\n"
        "Rules:\n"
        "- Don't invent. Only put a field in `draft_updates` if the user actually said it (literally or via a clear paraphrase) in the latest message or recent conversation. If unsure, omit.\n"
        "- Backtracking is fine: if the user corrects a previously captured field (e.g., 'actually my role is X'), overwrite that field in `draft_updates`.\n"
        "- Replace, don't append. `draft_updates` values overwrite existing ones — for list fields (skills, contact_lines, certifications), include the FULL new list, not just additions.\n"
        "- Be concise: one or two sentences per assistant_message. Acknowledge what you just captured, then ask the next most useful question.\n"
        "- Pick the next gap from `Missing Fields` in roughly the listed order, but follow the user's lead if they jump ahead.\n"
        "- Don't ask compound questions. One topic at a time.\n"
        "- If the user gives a vague answer ('I'm a developer'), ask one targeted follow-up before moving on.\n"
        "- The `experience_notes`, `education_notes`, and `projects_notes` fields capture the user's words verbatim — don't paraphrase or expand them in `draft_updates`. Downstream rendering handles voice.\n"
        "- Projects + publications are OPTIONAL. Only ask about them when the user mentions a side project / open-source repo / paper / talk OR when their target_role is heavily technical (engineer, ML, data, research) AND they haven't already filled experience_notes with rich detail. Don't pressure for them — many candidates won't have any. After 'experience' is captured for a tech role, you may ask once: 'Do you want to include any side projects or papers?'. If they say no, move on.\n"
        "- Crucial split: when a single user turn contains BOTH a broad self-description (no specific company/dates) AND specific role details, route the self-description to `professional_summary` and the role details to `experience_notes`. Example — user says 'I'm a senior backend engineer with 5 years experience. I worked at Acme from 2020-2024 on the billing pipeline.' → professional_summary captures the first sentence, experience_notes captures the second.\n"
        "- Set status='collecting' while required fields (full_name, contact_lines, target_role, experience_notes, skills) are still empty; 'reviewing' once those are filled and the user could plausibly draft now; 'ready' only after the user explicitly confirms they're done.\n"
        "- Set focus_field to whichever field your next question is about ('' if you're confirming completion).\n"
        "- If the user asks an off-topic question (movies, jokes, lifestyle), decline in one sentence and steer back to resume building. Do not engage with the off-topic premise.\n"
        "\n"
        "Tools you can call:\n"
        "- fetch_github_readme(url): fetch the default-branch README.md of a PUBLIC github.com repository. "
        "Use this when the user shares a github.com URL and you need the project's tech stack / purpose / outcomes "
        "to capture into projects_notes. Call the tool BEFORE describing the project — never invent details. "
        "On a successful fetch, summarize what you read (project name, tech stack, outcome) into projects_notes "
        "as the user's own voice would describe it, then ask the user one clarifying question "
        "(e.g. \"Got it — I read the README and saw it's a recommendation engine in PyTorch + Redis. "
        "Anything I missed, like measured impact?\"). On failure (private repo, 404, timeout, etc.), tell the user "
        "honestly that the fetch didn't work and ask them to describe the project in their own words.\n"
        "\n"
        "Honesty rule:\n"
        "- Never promise a capability you don't have. If the user asks you to do something outside your tool set "
        "(browse the web, open a PDF, read a private link, run code, scrape LinkedIn, etc.), say so plainly in one "
        "sentence and offer the closest thing you CAN do — usually \"if you paste the relevant text or a github.com URL, "
        "I can take it from there.\" Better one honest sentence than a confident-sounding promise you can't keep.\n"
    )
    contract = _build_contract(
        {
            "draft_updates": (
                "partial dict of resume-builder fields the user mentioned in this "
                "turn or recent turns; OMIT fields you cannot ground in user text"
            ),
            "assistant_message": "the next conversational reply to show the user (1-2 sentences)",
            "status": "one of: 'collecting' (more fields to gather), 'reviewing' (enough to draft), 'ready' (user confirmed)",
            "focus_field": "the field your next question is about, or '' if none",
        }
    )
    return body + contract


def _expected_resume_builder_structuring_system() -> str:
    body = (
        "You convert resume-builder intake notes into structured resume "
        "entries. The user gave you their experience and education as "
        "free-form prose. Your job is to split that prose into one entry "
        "per role and one entry per degree, then return the structured "
        "lists as JSON.\n"
        "\n"
        "Rules — read carefully:\n"
        "- Split on role / degree boundaries: a new entry starts at every "
        "company name (\"Senior X at Acme\") or transition word (\"prior\", "
        "\"previously\", \"before that\", \"earlier\"). Multiple degrees on "
        "one line (\"MS CS Stanford 2017, BTech IIT Madras 2015\") become "
        "multiple education entries.\n"
        "- Fact preservation is mandatory. Companies, schools, dates, and "
        "skill names must come VERBATIM from the user's prose. Do not "
        "invent employers, schools, dates, technologies, or impact "
        "numbers the user did not mention.\n"
        "- Bullet voice is yours. Convert the user's casual phrasing into "
        "tight, ATS-style impact bullets ('Reduced p99 latency 30% by …', "
        "'Owned ingestion pipeline for …'). Each bullet should start with "
        "a strong verb and stay under ~22 words. If the user gave no "
        "specifics for a role, return an EMPTY bullets list — do NOT "
        "fabricate impact.\n"
        "- Title inference is allowed only when context makes it "
        "unambiguous. \"Senior Backend Engineer at TechCorp 2020-Present, "
        "prior at FinStart 2017-2020\" → second role's title is "
        "\"Backend Engineer\" (drop the seniority modifier). When in "
        "doubt, copy the user's most recent explicit title or leave "
        "title=\"Relevant Experience\".\n"
        "- Dates: parse what the user wrote into start/end strings. "
        "\"2020-Present\" → start='2020', end='Present'. \"(Jan 2023 - "
        "Jan 2025)\" → start='Jan 2023', end='Jan 2025'. Single year → "
        "start=year, end=''.\n"
        "- Education degree vs field: \"BTech CS\" → degree='BTech', "
        "field_of_study='CS'. \"MS Computer Science\" → degree='MS', "
        "field_of_study='Computer Science'. Treat the abbreviation alone "
        "as degree.\n"
        "- Order most recent first in all three lists.\n"
        "- Projects: same fact-preservation contract as experience. "
        "Extract project name, link (any URL the user typed), "
        "technologies (tech names appearing in the prose), and bullets "
        "(impact + outcome). Don't invent metrics, GitHub URLs, or "
        "technologies that aren't in the prose. If projects_notes is "
        "empty, return projects=[].\n"
        "- Skill categories: only emit when 8+ skills cluster naturally "
        "by domain. Every skill that appears in skill_categories MUST "
        "also appear in the original skills list — don't invent new "
        "tech. Don't reorder the skill names within a bucket; preserve "
        "the user's casing ('TensorFlow' not 'tensorflow').\n"
        "- Summary expansion: emit professional_summary ONLY when the "
        "user gave you a thin headline (under ~80 chars). Stay third-"
        "person ATS voice. Pull every concrete claim from the rest of "
        "the draft (target_role, role titles, technologies the user "
        "named, schools, dates) — invent NOTHING. If the user's "
        "summary is already 2+ sentences, return '' to leave it alone.\n"
        "- If the user's prose is empty for a section, return an empty "
        "list for that section.\n"
    )
    contract = _build_contract(
        {
            "experience": (
                "list of role objects with keys: title (string), organization (string), "
                "location (string, '' if unknown), start (string like '2020' or 'Jan 2023', "
                "'' if unknown), end (string, 'Present' for current roles, '' if unknown), "
                "bullets (list of 2-4 short impact-focused strings). Order most-recent first."
            ),
            "education": (
                "list of education objects with keys: institution (string), degree (string), "
                "field_of_study (string, '' if degree already includes it), start (string, "
                "'' if unknown), end (string, '' if unknown). Order most-recent first."
            ),
            "projects": (
                "list of project objects with keys: name (string — short title), "
                "description (string, '' if bullets capture it), bullets (list of 1-3 "
                "short impact-focused strings), technologies (list of tech / framework "
                "names that appear in the user's prose, max 8), start (string, '' if "
                "unknown), end (string, '' if unknown), link (URL string, '' if none). "
                "Empty list when projects_notes is empty. Order most-recent first."
            ),
            "skill_categories": (
                "OPTIONAL dict mapping category labels to skill name lists, e.g. "
                "{'Languages & Tools': ['Python', 'SQL'], 'ML / DL Frameworks': "
                "['PyTorch', 'Scikit-learn'], 'GenAI & LLMs': ['LangChain', 'OpenAI API']}. "
                "Generate this ONLY when the candidate has 8+ skills that obviously "
                "cluster by category. Pick category labels that fit the candidate's "
                "domain (common labels: 'Languages & Tools', 'ML / DL Frameworks', "
                "'GenAI & LLMs', 'Vector Databases', 'Systems & Deployment', "
                "'Data & Analysis', 'Cloud & Infrastructure', 'Frontend', 'Mobile'). "
                "Skip and return {} when skills are sparse, uniform, or don't cluster "
                "obviously — the renderer falls back to a flat list."
            ),
            "professional_summary": (
                "OPTIONAL expanded summary (string). Generate ONLY when the user's "
                "input professional_summary is shorter than ~80 characters AND there "
                "is enough context elsewhere in the draft (target_role, experience, "
                "skills) to write a polished 2-3 sentence headline. Output third-"
                "person ATS-style prose ('Senior backend engineer specializing in...' "
                "not 'I have 6 years experience'). FACT PRESERVATION IS MANDATORY — "
                "every claim must be grounded in something the user already typed. "
                "Don't invent years of experience, technologies, or impact. Return "
                "'' to keep the user's original summary unchanged."
            ),
        }
    )
    return body + contract


def test_assistant_prompt_matches_pre_migration_system_byte_for_byte():
    prompt = build_assistant_prompt(
        assistant_context={"current_page": "Resume"},
        question="What should I do first?",
    )
    assert prompt["system"] == _expected_assistant_system()
    assert prompt["expected_keys"] == [
        "answer",
        "sources",
        "suggested_follow_ups",
    ]


def test_assistant_text_prompt_matches_pre_migration_system_byte_for_byte():
    prompt = build_assistant_text_prompt(
        assistant_context={"current_page": "Resume"},
        question="What should I do first?",
    )
    assert prompt["system"] == _expected_assistant_text_system()
    # Prose-streaming variant: no expected_keys on the return value.
    assert "expected_keys" not in prompt


def test_assistant_followup_prompt_format_substitutes_scope():
    prompt = build_assistant_followup_prompt(
        "Got it — what's next?",
        assistant_scope="application_qa",
    )
    assert prompt["system"] == _expected_assistant_followup_system("application_qa")
    assert "Current assistant scope: application_qa." in prompt["system"]
    assert prompt["expected_keys"] == [
        "answer",
        "sources",
        "suggested_follow_ups",
    ]


def test_assistant_followup_prompt_defaults_to_assistant_scope():
    prompt = build_assistant_followup_prompt("hi")
    assert prompt["system"] == _expected_assistant_followup_system("assistant")
    assert "Current assistant scope: assistant." in prompt["system"]


def test_resume_builder_prompt_matches_pre_migration_system_byte_for_byte():
    prompt = build_resume_builder_prompt(
        draft={},
        user_message="I'm Priya Sharma from Bangalore.",
    )
    assert prompt["system"] == _expected_resume_builder_system()
    assert prompt["expected_keys"] == [
        "draft_updates",
        "assistant_message",
        "status",
        "focus_field",
    ]


def test_resume_builder_structuring_prompt_matches_pre_migration_system_byte_for_byte():
    prompt = build_resume_builder_structuring_prompt(draft={})
    assert prompt["system"] == _expected_resume_builder_structuring_system()
    assert prompt["expected_keys"] == [
        "experience",
        "education",
        "projects",
        "skill_categories",
        "professional_summary",
    ]


def test_product_help_assistant_inherits_assistant_system_via_delegation():
    """Wrapper should produce the SAME system as build_assistant_prompt —
    the only call-site delta is the assistant_context dict shape."""
    delegated = build_product_help_assistant_prompt(
        app_context={"knowledge_hits": []},
        question="What does this page do?",
    )
    canonical = build_assistant_prompt(
        {"assistant_scope": "product_help", "product_context": {"knowledge_hits": []}},
        "What does this page do?",
    )
    assert delegated["system"] == canonical["system"]
    assert delegated["system"] == _expected_assistant_system()


def test_application_qa_assistant_inherits_assistant_system_via_delegation():
    delegated = build_application_qa_assistant_prompt(
        workflow_context={"candidate_profile": {"summary": "ML engineer"}},
        question="What's my fit score?",
    )
    canonical = build_assistant_prompt(
        {
            "assistant_scope": "application_qa",
            "workflow_context": {"candidate_profile": {"summary": "ML engineer"}},
        },
        "What's my fit score?",
    )
    assert delegated["system"] == canonical["system"]
    assert delegated["system"] == _expected_assistant_system()

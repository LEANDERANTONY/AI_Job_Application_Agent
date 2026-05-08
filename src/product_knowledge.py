import re


PRODUCT_KNOWLEDGE_DOCUMENTS = [
    {
        "topic": "auth_required",
        "title": "Sign-in is required for the workspace",
        "source": "Workspace Auth",
        "keywords": [
            "sign in",
            "signed in",
            "sign-in",
            "signin",
            "log in",
            "login",
            "auth",
            "google",
            "oauth",
            "without signing in",
            "signed out",
            "redirect",
            "landing page",
        ],
        "content": (
            "The workspace is for signed-in users only. Sign-in is via Google OAuth from the landing page or the topbar. "
            "If a user is signed out (or their session expires), they are redirected to the landing page automatically — they cannot use Resume, Job Search, Job Detail, or Analysis without signing in. "
            "Signed-in actions include: parsing a resume, running the supervised analysis pipeline, generating tailored Resume + Cover Letter artifacts, exporting as PDF/DOCX, and saving the workspace snapshot for 24-hour reload."
        ),
    },
    {
        "topic": "step_flow",
        "title": "The four-step workspace flow",
        "source": "Step Rail",
        "keywords": [
            "steps",
            "flow",
            "four steps",
            "step 01",
            "step 02",
            "step 03",
            "step 04",
            "rail",
            "navigation",
            "workspace tabs",
        ],
        "content": (
            "The workspace is organized as four steps along a top rail: 01 Resume, 02 Job Search, 03 Job Detail (JD review), 04 Analysis. "
            "Steps 01–03 are independently accessible — a user can paste a JD before they have a resume, or browse listings without uploading anything. "
            "Step 04 (Analysis) is the only gated step: it requires both a parsed resume and a parsed JD before it will run, and the AnalysisRunner page surfaces what's missing if the user lands on it early."
        ),
    },
    {
        "topic": "resume_intake",
        "title": "Resume intake — upload or assistant builder",
        "source": "Resume",
        "keywords": [
            "resume",
            "upload",
            "build",
            "assistant builder",
            "resume builder",
            "pdf",
            "docx",
            "txt",
            "candidate profile",
            "parsed",
        ],
        "content": (
            "Step 01 (Resume) has two modes selectable via a top-right toggle: Upload and Build with assistant. "
            "Upload mode accepts PDF, DOCX, or TXT (up to 5 MB) and produces a parsed CandidateProfile (name, location, skills, experience entries, education, certifications). "
            "Build with assistant mode is a conversational chat that asks the user one question at a time across name, role target, location, experience, skills, education, projects, and publications; once enough fields are filled, the user generates a base resume and can download it directly as PDF or DOCX. "
            "Switching modes does not discard either mode's state — uploaded resumes stay uploaded, and in-progress assistant chats stay in progress. "
            "Resume-builder drafts auto-save to a 7-day TTL refreshed on activity, with a tri-state persistence indicator showing whether each field is saved, skipped, or unauthenticated."
        ),
    },
    {
        "topic": "job_search",
        "title": "Job Search — live listings + filters + import + saved drawer",
        "source": "Job Search",
        "keywords": [
            "job search",
            "search jobs",
            "greenhouse",
            "lever",
            "ashby",
            "workday",
            "shortlist",
            "saved jobs",
            "filter",
            "sort",
            "remote",
            "import",
        ],
        "content": (
            "Step 02 (Job Search) searches live listings across four ATS providers — Greenhouse, Lever, Ashby, and Workday — plus accepts a posting URL for direct import. "
            "Search takes a keyword and an optional location ('remote' or a city). "
            "Filter dropdowns control Source, Work mode, Type, Posted-within, and Sort (best match / most recent / alphabetical). "
            "Each result card shows title, company, source, summary, and a star 'Top match' badge on the leader. "
            "Cards have actions: Review role (loads the JD into Step 03), Open (external link), and Save (pin to shortlist). "
            "The 'Saved jobs' drawer above the results shows the count and expands to list saved postings; saved jobs persist server-side for signed-in users. "
            "If a saved job's upstream listing is tombstoned, the card gets an 'Expired' badge so the bookmark is preserved without misrepresenting application status."
        ),
    },
    {
        "topic": "jd_review",
        "title": "Job Detail (JD review)",
        "source": "Job Detail",
        "keywords": [
            "job description",
            "jd",
            "job detail",
            "paste",
            "import",
            "upload jd",
            "parsed jd",
            "match score",
            "hard skills",
            "soft skills",
            "must haves",
        ],
        "content": (
            "Step 03 (Job Detail) brings in the job description by paste, URL import, or file upload. "
            "Once parsed, the page shows: a hero with role title + company + location + source, three big metric tiles (Match score %, Hard skills count, Years required), and chip lists for Hard Skills, Soft Skills, and Must-haves. "
            "Below those are numbered body sections (Role Snapshot, Responsibilities, etc.) drawn verbatim from the JD parser output."
        ),
    },
    {
        "topic": "supervised_workflow",
        "title": "Supervised analysis workflow + agents",
        "source": "Analysis",
        "keywords": [
            "workflow",
            "analysis",
            "agents",
            "matchmaker",
            "forge",
            "gatekeeper",
            "workflow crew",
            "builder",
            "cover letter agent",
            "fit score",
            "review",
            "tailoring",
        ],
        "content": (
            "Step 04 (Analysis) runs a supervised pipeline of six specialist agents in sequence: "
            "1) Workflow crew (reads inputs and validates), "
            "2) Matchmaker (scores role fit and produces matched/missing skills), "
            "3) Forge agent (drafts the tailored resume), "
            "4) Gatekeeper (reviews outputs for quality), "
            "5) Builder (final assembly), "
            "6) Cover letter agent (drafts the cover letter from review-approved outputs). "
            "The page shows each stage as a card with an agent label, percent progress, and a status pip (done / running / standby). "
            "If AI-assisted execution fails mid-run, the UI surfaces a downgrade notice and the run completes via deterministic fallback."
        ),
    },
    {
        "topic": "exports",
        "title": "Artifact exports — PDF + DOCX, two themes",
        "source": "Artifact Viewer",
        "keywords": [
            "download",
            "export",
            "pdf",
            "docx",
            "word",
            "theme",
            "classic",
            "ats",
            "professional",
            "resume",
            "cover letter",
        ],
        "content": (
            "Tailored Resume and Cover Letter are exportable as PDF or DOCX. "
            "Each artifact has its own theme picker so a user can pair a classic_ats resume with a professional_neutral cover letter (or any combination). "
            "Markdown export was removed in 2026-05 — only PDF and DOCX remain. "
            "Buttons present as Download actions; on click, bytes generate with spinner feedback and then refresh into the browser download control."
        ),
    },
    {
        "topic": "saved_workspace",
        "title": "Reload Workspace — 24-hour saved snapshot",
        "source": "Reload Workspace",
        "keywords": [
            "saved workspace",
            "reload",
            "restore",
            "expires",
            "24 hours",
            "snapshot",
            "previous work",
            "earlier work",
            "ttl",
        ],
        "content": (
            "Signed-in users get one saved workspace snapshot per account, refreshed each time the analysis pipeline produces outputs. "
            "The Reload Workspace action in the topbar account popover restores that snapshot — bringing back the parsed resume, the parsed JD, the fit outputs, the imported job context when available, and the latest saved artifacts. "
            "The snapshot expires 24 hours after the last refresh; once expired, the user starts fresh."
        ),
    },
    {
        "topic": "command_palette",
        "title": "Command palette (⌘K)",
        "source": "Command Palette",
        "keywords": [
            "command palette",
            "cmd k",
            "ctrl k",
            "search workspace",
            "shortcut",
            "jump to",
            "keyboard",
        ],
        "content": (
            "The topbar has a 'Search or run command…' pill that opens the command palette, also reachable via Cmd+K (macOS) or Ctrl+K (Windows). "
            "The palette has four sections: Jump to (Resume / Job Search / JD / Analysis with their gating tooltips), Saved jobs (jumps to JD with that posting preloaded), Recent assistant turns (re-asks the question), and Actions (Run analysis, Re-upload resume, Clear workspace). "
            "Arrow keys navigate, Enter selects, Esc closes."
        ),
    },
    {
        "topic": "floating_assistant",
        "title": "Floating assistant (FAB)",
        "source": "Assistant",
        "keywords": [
            "assistant",
            "fab",
            "chat",
            "ask",
            "help",
            "question",
            "streaming",
            "history",
        ],
        "content": (
            "The floating assistant is a circular button anchored bottom-right of the workspace; clicking expands a 380×560 chat panel. "
            "The assistant answers both product-help questions ('how do I use this?', 'what's step 03 for?') and grounded questions about the user's current workspace ('summarize my fit', 'what's my match score?'). "
            "It is NOT gated on having run an analysis — it can answer product-help from the very first visit. When a workspace snapshot exists, answers ground in that snapshot; otherwise the assistant uses the live workspace_state (current step, parsed-or-not flags, saved-job count, last search) to give a state-aware response. "
            "Responses stream token-by-token via Server-Sent Events. Conversation history persists locally for the session and clears on Sign out or via the trash icon in the panel header."
        ),
    },
    {
        "topic": "cover_letter",
        "title": "Cover Letter artifact",
        "source": "Cover Letter",
        "keywords": [
            "cover letter",
            "letter",
            "introduction",
            "personalized",
        ],
        "content": (
            "The cover letter is a first-class output artifact alongside the tailored resume. "
            "It is generated by the Cover letter agent after the Gatekeeper review approves the upstream outputs, and is surfaced via tabs in the Artifact Viewer next to the Tailored Resume. "
            "Each cover letter can be exported as PDF or DOCX with its own theme."
        ),
    },
    {
        "topic": "quota_limits",
        "title": "Assisted-feature daily quota",
        "source": "Quota State",
        "keywords": [
            "quota",
            "limit",
            "token",
            "budget",
            "daily",
            "session",
            "rate",
            "exhausted",
        ],
        "content": (
            "AI-assisted features (resume parsing, analysis, tailoring, review, cover-letter generation, the assistant chat) require a signed-in account and use the authenticated account-level daily quota for the user's plan tier. "
            "When that daily quota is exhausted, assisted features remain unavailable until the next UTC reset or a plan change. The topbar account popover surfaces the quota usage strip and the plan tier."
        ),
    },
]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", str(text or "").lower()))


def retrieve_product_knowledge(question: str, current_page: str = "", limit: int = 3) -> list[dict]:
    question_text = str(question or "")
    question_tokens = _tokenize(question_text)
    page_tokens = _tokenize(current_page)
    scored_results = []

    for document in PRODUCT_KNOWLEDGE_DOCUMENTS:
        score = 0
        keyword_tokens = set()
        for keyword in document.get("keywords", []):
            keyword_str = str(keyword or "").lower()
            keyword_tokens.update(_tokenize(keyword_str))
            if keyword_str and keyword_str in question_text.lower():
                score += 4
        score += len(question_tokens & keyword_tokens)
        score += len(page_tokens & _tokenize(document.get("source", "")))
        if score <= 0:
            continue
        scored_results.append(
            (
                score,
                {
                    "title": document["title"],
                    "source": document["source"],
                    "topic": document["topic"],
                    "content": document["content"],
                },
            )
        )

    scored_results.sort(key=lambda item: (-item[0], item[1]["title"]))
    return [item[1] for item in scored_results[:limit]]

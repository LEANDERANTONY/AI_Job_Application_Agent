import re


PRODUCT_KNOWLEDGE_DOCUMENTS = [
    {
        "topic": "saved_workspace",
        "title": "Reload Workspace",
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
        ],
        "content": (
            "Signed-in users keep one saved workspace snapshot for 24 hours. "
            "The sidebar Reload Workspace action restores that snapshot back into Manual JD Input, including the resume-backed candidate state, fit outputs, and the latest saved artifacts when available."
        ),
    },
    {
        "topic": "exports",
        "title": "Export Downloads",
        "source": "Combined Export",
        "keywords": ["download", "export", "pdf", "bundle", "markdown", "zip"],
        "content": (
            "Markdown downloads are immediately available for the tailored resume, cover letter, and application package. PDF and ZIP bundle actions present as Download actions from the start, generate bytes on first click with spinner feedback, and then refresh into the browser download control."
        ),
    },
    {
        "topic": "cover_letter",
        "title": "Cover Letter Artifact",
        "source": "Cover Letter",
        "keywords": ["cover letter", "letter", "application package", "resume preview"],
        "content": (
            "The cover letter is a first-class artifact in the JD workflow. It is generated after review-approved workflow outputs exist, appears between Resume Preview and Application Package, and can be downloaded as Markdown or PDF."
        ),
    },
    {
        "topic": "quota_limits",
        "title": "Assisted Limits",
        "source": "Quota State",
        "keywords": ["quota", "limit", "token", "budget", "daily", "session"],
        "content": (
            "AI-assisted features require a signed-in account and use the authenticated account-level daily quota for the current plan tier. When that daily quota is exhausted, assisted features remain unavailable until the next UTC reset or a plan change."
        ),
    },
    {
        "topic": "supervised_workflow",
        "title": "Supervised Workflow",
        "source": "Manual JD Input",
        "keywords": ["workflow", "supervised", "agent", "review", "fit", "tailoring"],
        "content": (
            "The supervised workflow runs specialist agents for fit, tailoring, strategy, review, resume generation, and cover letter generation. The cover letter is generated after review-approved outputs exist. If AI-assisted execution fails mid-run, the UI shows that the workflow downgraded to deterministic fallback and why."
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

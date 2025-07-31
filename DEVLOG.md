# DEVLOG.md – AI Job Application Agent

This document tracks the day-by-day evolution, decisions, challenges, and technical improvements made during development.  
**Purpose:** To tell the story behind the code—for interviews, your portfolio, and personal growth.

---

## Day 1: Project Kickoff & Setup

- Initialized the GitHub repository and set up folders, `.gitignore`, and MIT licensing.
- Set up Python virtual environment, installed dependencies.
- Built initial Streamlit UI skeleton with navigation for all main features.
- **Decision:** Chose MVP-first approach for rapid progress; keep dependencies minimal early.

## Day 1: Setup Challenges & Key Decisions

- **Virtual Environment Activation Blocked in PowerShell**
  - *Challenge:* Windows PowerShell blocked venv activation due to script execution policy.
  - *Solution:* Used `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process` to temporarily allow script activation.
  - *Note:* Classic Windows Python setup hurdle—now resolved and understood.

- **pip Version Warning**
  - *Challenge:* Old pip version triggered a warning during package installation.
  - *Solution:* Upgraded pip within venv using `python -m pip install --upgrade pip`.
  - *Note:* Keeping pip updated is important for smoother package installs.

- **Dependency Version Mismatch Warning (tenacity and langchain)**
  - *Challenge:* Warning about `tenacity` version being newer than required by LangChain.
  - *Solution:* Chose to ignore for MVP since install completed and app runs; will revisit if it causes runtime errors.
  - *Note:* Real-world dev—don’t get stuck on warnings unless they’re blockers.

- **Terminal Choice & venv Activation Location**
  - *Challenge:* Needed clarity on which terminal and folder to activate venv.
  - *Solution:* Confirmed that activation works from any terminal, as long as you’re in the project directory.
  - *Note:* Useful lesson for future workflow and team members.

- **Streamlit Email Prompt**
  - *Challenge:* Streamlit asked for email on first launch, causing minor confusion.
  - *Solution:* Verified it’s optional and doesn’t affect local development; skipped prompt.
  - *Note:* Good to log user experience hurdles too.

- **Resume Parsing Library Choice for MVP**
  - *Decision Point:* Whether to use basic `pypdf`/`python-docx` or advanced LangChain/LlamaIndex loaders.
  - *Resolution:* Decided to use minimal dependencies for MVP, then upgrade after validating limitations and core pipeline stability.
  - *Note:* Follows iterative product best practices.

## Resume Parser Milestone

- **Module Complete:** Integrated basic resume parsing module using `pypdf` and `python-docx`.
- **Result:** App now parses and previews uploaded resumes (PDF or DOCX) directly in the UI.
- **Testing:** Successfully extracted text from several sample resumes.
- **Challenges Noted:** 
  - Simple formatting works well; complex layouts (tables, multi-columns) may have extraction issues.
  - Some scanned/image-based PDFs are not supported by pypdf (needs OCR in future).
- **Next Steps:** 
  - Gather more sample resumes to identify edge cases.
  - Plan future upgrade to LangChain/LlamaIndex loaders for richer extraction after MVP.
---


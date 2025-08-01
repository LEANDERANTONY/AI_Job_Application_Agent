# DEVLOG.md – AI Job Application Agent

This document tracks the day-by-day evolution, decisions, challenges, and technical improvements made during development.  

---

## Day 1: Project Kickoff & Setup

- Initialized the GitHub repository and set up folders, `.gitignore`, and MIT licensing.
- Set up Python virtual environment, installed dependencies.
- Built initial Streamlit UI skeleton with navigation for all main features.
- **Decision:** Chose MVP-first approach for rapid progress; keep dependencies minimal early.

### Setup Challenges & Key Decisions

- **Virtual Environment Activation Blocked in PowerShell**
  - *Challenge:* Windows PowerShell blocked venv activation due to script execution policy.
  - *Solution:* Used `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process` to temporarily allow script activation.

- **pip Version Warning**
  - *Challenge:* Old pip version triggered a warning during package installation.
  - *Solution:* Upgraded pip within venv using `python -m pip install --upgrade pip`.

- **Dependency Version Mismatch Warning (tenacity and langchain)**
  - *Challenge:* Warning about `tenacity` version being newer than required by LangChain.
  - *Solution:* Chose to ignore for MVP since install completed and app runs; will revisit if it causes runtime errors.

- **Resume Parsing Library Choice for MVP**
  - *Decision Point:* Whether to use basic `pypdf`/`python-docx` or advanced LangChain/LlamaIndex loaders.
  - *Resolution:* Decided to use minimal dependencies for MVP, then upgrade after validating limitations and core pipeline stability.
  - *Note:* Follows iterative product best practices.
    
- **Additional Learning:**
  - PAT (Personal Access Token) now required for pushing to GitHub via HTTPS; password authentication no longer supported.
  - Credential caching (via Windows Credential Manager) simplifies repeated pushes.

### Resume Parser Milestone

- **Module Complete:** Integrated basic resume parsing module using `pypdf` and `python-docx`.
- **Result:** App now parses and previews uploaded resumes (PDF or DOCX) directly in the UI.
- **Testing:** Successfully extracted text from several sample resumes.
- **Challenges Noted:** 
  - Simple formatting works well; complex layouts (tables, multi-columns) may have extraction issues.
  - Some scanned/image-based PDFs are not supported by pypdf (needs OCR in future).
- **Next Steps:** 
  - Plan future upgrade to LangChain/LlamaIndex loaders for richer extraction after MVP.

## Day 2: Sample File Integration & Unified File Parsing

### 📂 Sample JD + Resume Support  
Implemented support for preloaded demo job descriptions and resumes to aid testing and UX polish.

- **Demo JD Integration**  
  - Added `static/demo_jds/` directory  
  - Loaded `.pdf`, `.docx`, `.txt` files dynamically using `os.listdir()`  
  - Dropdown added to "Manual JD Input" tab for selecting demo JDs  

- **Demo Resume Integration**  
  - Created `static/demo_resumes/` folder  
  - Added sample selection in "Upload Resume" tab with same logic

### 🔁 Unified File Parsing (Uploads + Disk)  
**Challenge:** Streamlit’s uploaded files provide `.type`, but files opened with `open()` do not.  
**Fix:** Added `mimetypes.guess_type()` fallback to support both upload and local file parsing.

- Updated `parse_jd_file()` and `parse_resume()` to handle:
  - `application/pdf` via `pypdf`
  - `application/msword` and `docx` via `python-docx`
  - `text/plain` with `.decode("utf-8")`

### JD Parser Milestone  
- JD Text Cleanup + Info Extraction  
- Added `clean_text()` to normalize whitespace, strip symbols  
- Added `extract_job_details()` to extract:
  - Job title (assumed as first line)
  - Location (via regex)
  - Experience (e.g., “2+ years”)
  - Matched hard and soft skills from predefined lists

### 🧪 Testing  
- Verified JD/resume parsing via both upload and demo selection  
- Confirmed all supported formats worked as expected  
- Graceful handling of unsupported types added  


## ADR 1: Resume Parsing Approach

**Decision**: Start with `pypdf` and `python-docx` for initial resume parsing.

**Context**:
- Needed a lightweight, fast, and dependency-free way to extract resume text.
- Avoid premature optimization with LangChain/LlamaIndex loaders.
- Prioritized MVP speed and stability over complex formatting support.

---

## ADR 2: Add Sample JD/Resume Support

**Decision**: Add support for preloaded demo job descriptions and resumes from local directories.

**Context**:
- Users may not always have files on hand during testing.
- Sample data improves usability and allows quick validation of parsing pipelines.
- Needed for offline demos or reproducible test cases.

---

## ADR 3: Add File-Type Agnostic Parsing with `mimetypes`

**Decision**: Use `mimetypes.guess_type()` to determine file type when `.type` attribute is missing.

**Context**:
- Streamlit-uploaded files provide `.type`.
- Files opened using `open(path, "rb")` do not.
- Without this, local testing with sample files fails.

---

## ADR 4: Add Streamlit Caching for Parsing & Processing

**Decision**: Wrap parsing and JD cleaning/extraction logic in `@st.cache_data`.

**Context**:
- Re-parsing the same file on each UI interaction causes slowdown.
- Especially important for larger resumes or JD PDFs.

---

## ADR 5: Improve Navigation via Persistent State & Redirection

**Decision**: Use `st.session_state["redirect_to"]` and `st.session_state["current_menu"]` to control navigation between Streamlit sections.

**Context**:
- Navigation via sidebar menu should reflect user intent, especially when moving between sections like LinkedIn → JD Input.
- Earlier implementation caused state loss or incorrect screen resets.
- Resolved by adding:
  - `redirect_to` (for deferred redirect after button clicks)
  - `current_menu` (to persist selected menu item across reruns)

---

## ADR 6: Persist Parsed Output with `st.session_state`

**Decision**: Cache extracted resume/LinkedIn/JD text and metadata in `st.session_state`.

**Context**:
- Without storing parsed output, UI lost data when users navigated between pages.
- JD Input already persisted well; resume and LinkedIn needed similar treatment.
- Added:
  - `session_state["resume_text"]`, `session_state["linkedin_data"]`, `session_state["uploaded_jd_file"]`
  - Output preview logic reuses this session state if no new upload is made.

---

## ADR 7: Fallback Support for JD Parsing from Multiple Sources

**Decision**: Support JD input from sample file, uploaded file, or pasted text—all in one unified logic block.

**Context**:
- Users may input JD in multiple ways; all should work consistently.
- JD parsing logic must prioritize in order: uploaded file > sample > pasted text.
- Simplified logic also ensures reruns still use the last valid input via session state.

---

## ADR 8: LinkedIn Data Export as Input Instead of Direct API

**Decision**: Skip direct LinkedIn scraping/API access and rely on user-uploaded `.zip` archive.

**Context**:
- LinkedIn’s API has strict access policies and scraping violates TOS.
- Added clear instructions in UI to guide user on downloading their LinkedIn archive.
- Created parser to extract name, headline, experience, education, preferences, publications, etc., from available `.csv` and `.json` files.
- Handles missing files gracefully (e.g., no publications).

---


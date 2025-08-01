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

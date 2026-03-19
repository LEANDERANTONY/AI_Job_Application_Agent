from types import SimpleNamespace

from src.ui import pages


def test_render_job_description_page_reruns_after_successful_agentic_workflow(monkeypatch):
    rerun_calls = {"count": 0}

    class StopRender(Exception):
        pass

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.file_uploader = lambda *args, **kwargs: None
    fake_st.markdown = lambda *args, **kwargs: None
    fake_st.text_area = lambda *args, **kwargs: "jd text"
    fake_st.caption = lambda *args, **kwargs: None
    fake_st.columns = lambda count: [FakeColumn() for _ in range(count)]
    fake_st.expander = lambda *args, **kwargs: FakeColumn()
    fake_st.info = lambda *args, **kwargs: None
    fake_st.button = lambda label, **kwargs: label == "Run Agentic Analysis"
    fake_st.rerun = lambda: (_ for _ in ()).throw(StopRender())

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "render_metric_card", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "resolve_job_description_input", lambda **kwargs: ("jd text", "Pasted text"))
    monkeypatch.setattr(pages, "get_imported_job_posting", lambda: None)
    monkeypatch.setattr(pages, "set_imported_job_posting", lambda value: None)
    monkeypatch.setattr(
        pages,
        "build_job_workflow_view_model",
        lambda jd_text, jd_source: SimpleNamespace(
            jd_text=jd_text,
            jd_source=jd_source,
            job_description=SimpleNamespace(
                title="ML Engineer",
                requirements=SimpleNamespace(hard_skills=["Python"], soft_skills=["Communication"]),
            ),
            candidate_profile=object(),
            ai_session=SimpleNamespace(mode_label="AI-assisted"),
            agent_result=None,
        ),
    )
    monkeypatch.setattr(pages, "assisted_workflow_requires_login", lambda: False)
    monkeypatch.setattr(pages, "is_authenticated", lambda: True)
    monkeypatch.setattr(
        pages,
        "_run_supervised_workflow_with_progress",
        lambda workflow_view_model: SimpleNamespace(
            **{**workflow_view_model.__dict__, "agent_result": object()}
        ),
    )

    try:
        pages.render_job_description_page()
    except StopRender:
        rerun_calls["count"] += 1

    assert rerun_calls["count"] == 1


def test_render_job_search_page_imports_backend_job_and_navigates(monkeypatch):
    rerun_calls = {"count": 0}
    captured = {}

    class StopRender(Exception):
        pass

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.columns = lambda spec: [FakeColumn(), FakeColumn()]
    fake_st.text_input = lambda *args, **kwargs: "https://job-boards.greenhouse.io/narvar/jobs/7363442"
    fake_st.button = lambda label, **kwargs: label == "Load Job Into JD Flow"
    fake_st.info = lambda *args, **kwargs: None
    fake_st.success = lambda *args, **kwargs: None
    fake_st.warning = lambda *args, **kwargs: None
    fake_st.rerun = lambda: (_ for _ in ()).throw(StopRender())

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "render_metric_card", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "job_search_backend_enabled", lambda: True)
    monkeypatch.setattr(pages, "get_job_search_import_notice", lambda: None)
    monkeypatch.setattr(
        pages,
        "resolve_job_url_via_backend",
        lambda url: {
            "status": "ok",
            "job_posting": {
                "title": "Sr. AI Engineer",
                "source": "greenhouse",
                "description_text": "Machine Learning Engineer\nLocation: Remote - Canada\nRequired: Python, SQL, LLM systems.",
            },
        },
    )
    monkeypatch.setattr(
        pages,
        "build_job_description_from_text",
        lambda text: SimpleNamespace(title="Sr. AI Engineer", cleaned_text=text, requirements=SimpleNamespace(hard_skills=["Python"], soft_skills=[])),
    )
    monkeypatch.setattr(
        pages,
        "store_job_description_inputs",
        lambda raw_text, source_label, job_description: captured.update(
            {
                "raw_text": raw_text,
                "source_label": source_label,
                "job_description": job_description,
            }
        ),
    )
    monkeypatch.setattr(
        pages,
        "set_job_search_import_notice",
        lambda notice: captured.update({"notice": notice}),
    )
    monkeypatch.setattr(
        pages,
        "set_imported_job_posting",
        lambda job_posting: captured.update({"job_posting": job_posting}),
    )

    try:
        pages.render_job_search_page()
    except StopRender:
        rerun_calls["count"] += 1

    assert captured["source_label"] == "Imported from Greenhouse"
    assert "LLM systems" in captured["raw_text"]
    assert captured["job_posting"]["title"] == "Sr. AI Engineer"
    assert captured["notice"]["level"] == "success"
    assert rerun_calls["count"] == 1


def test_render_job_description_page_shows_imported_job_review(monkeypatch):
    captured = {"metrics": [], "lists": [], "expanders": []}

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.file_uploader = lambda *args, **kwargs: None
    fake_st.markdown = lambda *args, **kwargs: None
    fake_st.text_area = lambda *args, **kwargs: "jd text"
    fake_st.caption = lambda *args, **kwargs: None
    fake_st.columns = lambda count: [FakeColumn() for _ in range(count)]
    fake_st.expander = lambda label, **kwargs: captured["expanders"].append(label) or FakeColumn()
    fake_st.info = lambda *args, **kwargs: None
    fake_st.button = lambda *args, **kwargs: False

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pages,
        "render_metric_card",
        lambda label, value, *args, **kwargs: captured["metrics"].append((label, value)),
    )
    monkeypatch.setattr(pages, "_render_list", lambda title, items, empty_state: captured["lists"].append((title, list(items))))
    monkeypatch.setattr(pages, "resolve_job_description_input", lambda **kwargs: ("jd text", "Imported from Greenhouse"))
    monkeypatch.setattr(
        pages,
        "get_imported_job_posting",
        lambda: {
            "title": "Sr. AI Engineer",
            "company": "Narvar",
            "location": "Remote - Canada",
            "source": "greenhouse",
            "employment_type": "Full-time",
            "url": "https://job-boards.greenhouse.io/narvar/jobs/7363442",
            "posted_at": "2026-03-18T17:00:51-04:00",
            "metadata": {"departments": ["Engineering"], "offices": ["Remote - Canada"]},
        },
    )
    monkeypatch.setattr(pages, "set_imported_job_posting", lambda value: None)
    monkeypatch.setattr(
        pages,
        "build_job_workflow_view_model",
        lambda jd_text, jd_source: SimpleNamespace(
            jd_text=jd_text,
            jd_source=jd_source,
            job_description=SimpleNamespace(
                title="Unknown Role",
                cleaned_text="Senior AI Engineer role focused on production LLM systems, RAG pipelines, and customer support automation. Narvar Pay Range $180,000 - $230,000 CAD.",
                location="Remote - Canada",
                requirements=SimpleNamespace(
                    hard_skills=["Python", "SQL"],
                    soft_skills=["Communication"],
                    experience_requirement="5+ years",
                    must_haves=["Production LLM systems"],
                    nice_to_haves=["RAG pipelines"],
                ),
            ),
            candidate_profile=None,
            ai_session=SimpleNamespace(mode_label="AI-assisted"),
            agent_result=None,
        ),
    )

    pages.render_job_description_page()

    assert "Review Imported Job Details" in captured["expanders"]
    assert ("Target Role", "Sr. AI Engineer at Narvar") in captured["metrics"]
    assert ("Compensation", "Narvar Pay Range $180,000 - $230,000 CAD") in captured["metrics"]
    assert ("Hard Skills Required", ["Python", "SQL"]) in captured["lists"]

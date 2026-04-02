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
    monkeypatch.setattr(pages, "_render_job_review_panel", lambda *args, **kwargs: None)
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
                    cleaned_text="ML Engineer role focused on Python systems.",
                    location="",
                    requirements=SimpleNamespace(
                        hard_skills=["Python"],
                        soft_skills=["Communication"],
                        experience_requirement=None,
                    ),
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
    fake_st.checkbox = lambda *args, **kwargs: False
    fake_st.selectbox = lambda *args, **kwargs: None
    fake_st.text_input = lambda *args, **kwargs: "https://job-boards.greenhouse.io/narvar/jobs/7363442"
    fake_st.button = lambda label, **kwargs: label == "Load Job Into JD Flow"
    fake_st.info = lambda *args, **kwargs: None
    fake_st.markdown = lambda *args, **kwargs: None
    fake_st.success = lambda *args, **kwargs: None
    fake_st.warning = lambda *args, **kwargs: None
    fake_st.link_button = lambda *args, **kwargs: None
    fake_st.rerun = lambda: (_ for _ in ()).throw(StopRender())

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "render_metric_card", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "job_search_backend_enabled", lambda: True)
    monkeypatch.setattr(pages, "get_job_search_import_notice", lambda: None)
    monkeypatch.setattr(pages, "get_job_search_results", lambda: None)
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
        "_load_job_posting_into_jd_flow",
        lambda job_posting: captured.update({"job_posting": job_posting}) or (_ for _ in ()).throw(StopRender()),
    )
    monkeypatch.setattr(
        pages,
        "set_job_search_import_notice",
        lambda notice: captured.update({"notice": notice}),
    )
    monkeypatch.setattr(
        pages,
        "set_job_search_results",
        lambda payload: captured.update({"search_results": payload}),
    )

    try:
        pages.render_job_search_page()
    except StopRender:
        rerun_calls["count"] += 1

    assert captured["job_posting"]["title"] == "Sr. AI Engineer"
    assert rerun_calls["count"] == 1


def test_render_job_search_page_shows_search_coverage_for_results(monkeypatch):
    captured = {"metrics": [], "markdown": []}

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.columns = lambda spec: [FakeColumn() for _ in range(spec if isinstance(spec, int) else len(spec))]
    fake_st.checkbox = lambda *args, **kwargs: False
    fake_st.selectbox = lambda *args, **kwargs: None
    fake_st.text_input = lambda *args, **kwargs: ""
    fake_st.button = lambda *args, **kwargs: False
    fake_st.info = lambda *args, **kwargs: None
    fake_st.markdown = lambda *args, **kwargs: captured["markdown"].append(args[0] if args else "")
    fake_st.success = lambda *args, **kwargs: None
    fake_st.warning = lambda *args, **kwargs: None
    fake_st.link_button = lambda *args, **kwargs: None
    fake_st.caption = lambda *args, **kwargs: None
    fake_st.expander = lambda *args, **kwargs: FakeColumn()
    fake_st.rerun = lambda: None

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pages,
        "render_metric_card",
        lambda label, value, *args, **kwargs: captured["metrics"].append((label, value)),
    )
    monkeypatch.setattr(pages, "job_search_backend_enabled", lambda: True)
    monkeypatch.setattr(pages, "get_job_search_import_notice", lambda: None)
    monkeypatch.setattr(
        pages,
        "get_job_search_results",
        lambda: {
            "results": [
                {
                    "title": "Software Engineer",
                    "company": "Glean",
                    "source": "greenhouse",
                    "location": "Remote",
                    "description_text": "Software engineer role with Python.",
                    "summary": "Software engineer role with Python.",
                    "metadata": {"departments": ["Engineering"]},
                }
            ],
            "source_status": {
                "backend": "ready",
                "greenhouse": "ok",
                "gleanwork": "matched",
                "narvar": "no_match",
                "wayve": "error",
                "figma": "empty",
            },
        },
    )

    pages.render_job_search_page()

    assert ("Boards Searched", "4") in captured["metrics"]
    assert ("Matched Boards", "1") in captured["metrics"]
    assert ("No Match", "2") in captured["metrics"]
    assert ("Unavailable", "1") in captured["metrics"]
    assert "### Search Coverage" in captured["markdown"]


def test_render_job_search_page_shows_empty_state_for_no_results(monkeypatch):
    captured = {"info": []}

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.columns = lambda spec: [FakeColumn() for _ in range(spec if isinstance(spec, int) else len(spec))]
    fake_st.checkbox = lambda *args, **kwargs: False
    fake_st.selectbox = lambda *args, **kwargs: None
    fake_st.text_input = lambda *args, **kwargs: ""
    fake_st.button = lambda *args, **kwargs: False
    fake_st.info = lambda message, *args, **kwargs: captured["info"].append(message)
    fake_st.markdown = lambda *args, **kwargs: None
    fake_st.success = lambda *args, **kwargs: None
    fake_st.warning = lambda *args, **kwargs: None
    fake_st.link_button = lambda *args, **kwargs: None
    fake_st.caption = lambda *args, **kwargs: None
    fake_st.expander = lambda *args, **kwargs: FakeColumn()
    fake_st.rerun = lambda: None

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "render_metric_card", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "job_search_backend_enabled", lambda: True)
    monkeypatch.setattr(pages, "get_job_search_import_notice", lambda: None)
    monkeypatch.setattr(
        pages,
        "get_job_search_results",
        lambda: {
            "results": [],
            "source_status": {"backend": "ready", "greenhouse": "ok", "narvar": "no_match"},
        },
    )

    pages.render_job_search_page()

    assert any("No current jobs matched this search." in message for message in captured["info"])


def test_render_job_search_page_can_clear_results(monkeypatch):
    captured = {"cleared_results": 0, "cleared_notice": 0, "reruns": 0}

    class StopRender(Exception):
        pass

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.columns = lambda spec: [FakeColumn() for _ in range(spec if isinstance(spec, int) else len(spec))]
    fake_st.checkbox = lambda *args, **kwargs: False
    fake_st.selectbox = lambda *args, **kwargs: None
    fake_st.text_input = lambda *args, **kwargs: ""
    fake_st.button = lambda label, **kwargs: label == "Clear Results"
    fake_st.info = lambda *args, **kwargs: None
    fake_st.markdown = lambda *args, **kwargs: None
    fake_st.success = lambda *args, **kwargs: None
    fake_st.warning = lambda *args, **kwargs: None
    fake_st.link_button = lambda *args, **kwargs: None
    fake_st.caption = lambda *args, **kwargs: None
    fake_st.expander = lambda *args, **kwargs: FakeColumn()
    fake_st.rerun = lambda: (_ for _ in ()).throw(StopRender())

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "render_metric_card", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "job_search_backend_enabled", lambda: True)
    monkeypatch.setattr(pages, "get_job_search_import_notice", lambda: None)
    monkeypatch.setattr(
        pages,
        "get_job_search_results",
        lambda: {
            "results": [
                {
                    "title": "Software Engineer",
                    "company": "Glean",
                    "source": "greenhouse",
                    "location": "Remote",
                    "description_text": "Software engineer role with Python.",
                    "summary": "Software engineer role with Python.",
                    "metadata": {},
                }
            ],
            "source_status": {"backend": "ready", "greenhouse": "ok", "gleanwork": "matched"},
        },
    )
    monkeypatch.setattr(
        pages,
        "set_job_search_results",
        lambda payload: captured.update({"cleared_results": captured["cleared_results"] + (1 if payload is None else 0)}),
    )
    monkeypatch.setattr(
        pages,
        "set_job_search_import_notice",
        lambda payload: captured.update({"cleared_notice": captured["cleared_notice"] + (1 if payload is None else 0)}),
    )

    try:
        pages.render_job_search_page()
    except StopRender:
        captured["reruns"] += 1

    assert captured["cleared_results"] == 1
    assert captured["cleared_notice"] == 1
    assert captured["reruns"] == 1


def test_render_job_search_page_shows_saved_jobs_panel(monkeypatch):
    captured = {"saved_cards": []}

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.columns = lambda spec: [FakeColumn() for _ in range(spec if isinstance(spec, int) else len(spec))]
    fake_st.checkbox = lambda *args, **kwargs: False
    fake_st.selectbox = lambda *args, **kwargs: None
    fake_st.text_input = lambda *args, **kwargs: ""
    fake_st.button = lambda *args, **kwargs: False
    fake_st.info = lambda *args, **kwargs: None
    fake_st.markdown = lambda *args, **kwargs: None
    fake_st.success = lambda *args, **kwargs: None
    fake_st.warning = lambda *args, **kwargs: None
    fake_st.link_button = lambda *args, **kwargs: None
    fake_st.caption = lambda *args, **kwargs: None
    fake_st.expander = lambda *args, **kwargs: FakeColumn()
    fake_st.rerun = lambda: None

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "render_metric_card", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "job_search_backend_enabled", lambda: True)
    monkeypatch.setattr(pages, "get_job_search_import_notice", lambda: None)
    monkeypatch.setattr(pages, "get_job_search_results", lambda: None)
    monkeypatch.setattr(pages, "is_authenticated", lambda: True)
    monkeypatch.setattr(pages, "get_saved_jobs_notice", lambda: None)
    monkeypatch.setattr(
        pages,
        "_load_saved_jobs",
        lambda force=False: [
            {
                "id": "greenhouse:narvar:1",
                "title": "Sr. AI Engineer",
                "company": "Narvar",
                "source": "greenhouse",
                "summary": "AI engineer role.",
            }
        ],
    )
    monkeypatch.setattr(
        pages,
        "_render_job_search_result_card",
        lambda job_posting, index, saved=False: captured["saved_cards"].append(
            (job_posting["title"], index, saved)
        ),
    )

    pages.render_job_search_page()

    assert captured["saved_cards"] == [("Sr. AI Engineer", 0, True)]


def test_render_job_search_result_card_saves_job(monkeypatch):
    captured = {"persisted": None, "reruns": 0}

    class StopRender(Exception):
        pass

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.markdown = lambda *args, **kwargs: None
    fake_st.columns = lambda spec: [FakeColumn() for _ in range(spec if isinstance(spec, int) else len(spec))]
    fake_st.button = lambda label, **kwargs: label == "Save Job"
    fake_st.link_button = lambda *args, **kwargs: None
    fake_st.rerun = lambda: (_ for _ in ()).throw(StopRender())

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "_render_badge_row", lambda badges: None)
    monkeypatch.setattr(pages, "is_authenticated", lambda: True)
    monkeypatch.setattr(pages, "_load_job_posting_into_jd_flow", lambda job_posting: None)
    monkeypatch.setattr(pages, "_persist_saved_job", lambda job_posting: captured.update({"persisted": job_posting["id"]}))
    monkeypatch.setattr(pages, "set_saved_jobs_notice", lambda notice: None)

    try:
        pages._render_job_search_result_card(
            {
                "id": "greenhouse:narvar:1",
                "title": "Sr. AI Engineer",
                "company": "Narvar",
                "source": "greenhouse",
                "summary": "AI engineer role.",
            },
            0,
        )
    except StopRender:
        captured["reruns"] += 1

    assert captured["persisted"] == "greenhouse:narvar:1"
    assert captured["reruns"] == 1


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


def test_render_job_description_page_shows_review_panel_for_manual_jd(monkeypatch):
    captured = {"metrics": [], "review_calls": []}

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
    fake_st.button = lambda *args, **kwargs: False

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pages,
        "render_metric_card",
        lambda label, value, *args, **kwargs: captured["metrics"].append((label, value)),
    )
    monkeypatch.setattr(pages, "resolve_job_description_input", lambda **kwargs: ("jd text", "Pasted text"))
    monkeypatch.setattr(pages, "get_imported_job_posting", lambda: None)
    monkeypatch.setattr(pages, "set_imported_job_posting", lambda value: None)
    monkeypatch.setattr(
        pages,
        "_render_job_review_panel",
        lambda job_description, **kwargs: captured["review_calls"].append(
            {"title": job_description.title, "expander_title": kwargs.get("expander_title")}
        ),
    )
    monkeypatch.setattr(
        pages,
        "build_job_workflow_view_model",
        lambda jd_text, jd_source: SimpleNamespace(
            jd_text=jd_text,
            jd_source=jd_source,
            job_description=SimpleNamespace(
                title="Backend Engineer",
                cleaned_text="Backend Engineer role focused on APIs and analytics tooling. Compensation: $120,000 - $150,000 USD.",
                location="Chennai",
                requirements=SimpleNamespace(
                    hard_skills=["Python", "SQL"],
                    soft_skills=["Communication"],
                    experience_requirement="3+ years",
                ),
            ),
            candidate_profile=None,
            ai_session=SimpleNamespace(mode_label="AI-assisted"),
            agent_result=None,
        ),
    )

    pages.render_job_description_page()

    assert ("Target Role", "Backend Engineer") in captured["metrics"]
    assert ("Compensation", "$120,000 - $150,000 USD") in captured["metrics"]
    assert ("Location", "Chennai") in captured["metrics"]
    assert ("Experience", "3+ years") in captured["metrics"]
    assert ("Hard Skills", "2") in captured["metrics"]
    assert ("Soft Skills", "1") in captured["metrics"]
    assert captured["review_calls"] == [
        {"title": "Backend Engineer", "expander_title": "Review Job Details"}
    ]


def test_render_job_search_page_shows_backend_search_results(monkeypatch):
    captured = {"results": []}

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = SimpleNamespace()
    fake_st.columns = lambda spec: [FakeColumn(), FakeColumn()]
    fake_st.checkbox = lambda *args, **kwargs: False
    fake_st.selectbox = lambda *args, **kwargs: None
    fake_st.text_input = lambda label, **kwargs: "software engineer" if label == "Search Query" else ""
    fake_st.button = lambda label, **kwargs: False
    fake_st.info = lambda *args, **kwargs: None
    fake_st.markdown = lambda *args, **kwargs: None
    fake_st.success = lambda *args, **kwargs: None
    fake_st.warning = lambda *args, **kwargs: None
    fake_st.link_button = lambda *args, **kwargs: None
    fake_st.expander = lambda *args, **kwargs: FakeColumn()
    fake_st.rerun = lambda: None

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "render_metric_card", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "job_search_backend_enabled", lambda: True)
    monkeypatch.setattr(pages, "get_job_search_import_notice", lambda: None)
    monkeypatch.setattr(
        pages,
        "get_job_search_results",
        lambda: {
            "results": [
                {
                    "title": "Software Engineer, Backend",
                    "company": "Glean",
                    "location": "Bengaluru",
                    "source": "greenhouse",
                    "posted_at": "2026-03-19T09:00:00Z",
                    "summary": "Backend role working on distributed systems.",
                    "url": "https://example.com/job",
                }
            ]
        },
    )
    monkeypatch.setattr(
        pages,
        "_render_job_search_result_card",
        lambda job_posting, index: captured["results"].append((job_posting["title"], index)),
    )

    pages.render_job_search_page()

    assert captured["results"] == [("Software Engineer, Backend", 0)]

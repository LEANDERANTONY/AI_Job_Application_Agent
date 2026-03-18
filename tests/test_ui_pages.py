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
    fake_st.info = lambda *args, **kwargs: None
    fake_st.button = lambda label, **kwargs: label == "Run Agentic Analysis"
    fake_st.rerun = lambda: (_ for _ in ()).throw(StopRender())

    monkeypatch.setattr(pages, "st", fake_st)
    monkeypatch.setattr(pages, "render_page_divider", lambda: None)
    monkeypatch.setattr(pages, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "render_metric_card", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "resolve_job_description_input", lambda **kwargs: ("jd text", "Pasted text"))
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

from src.ui import page_history


def test_build_saved_workspace_explainer_without_saved_snapshot():
    lines = page_history._build_saved_workspace_explainer(False)

    assert any("inspection and download regeneration" in line.lower() for line in lines)
    assert any("no saved snapshot is available yet" in line.lower() for line in lines)


def test_build_saved_workspace_explainer_with_saved_snapshot():
    lines = page_history._build_saved_workspace_explainer(True)

    assert any("reload saved workspace" in line.lower() for line in lines)
    assert any("saved snapshot available right now" in line.lower() for line in lines)
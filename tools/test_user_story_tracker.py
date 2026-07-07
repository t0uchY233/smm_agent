import ast
from pathlib import Path


TRACKER = Path("docs/user-story-status.md")


def test_user_story_tracker_covers_all_top_level_tool_functions():
    tracker = TRACKER.read_text(encoding="utf-8")
    missing = []

    for path in sorted(Path("tools").glob("*.py")):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name not in tracker:
                missing.append(f"{path}:{node.name}")

    assert missing == []


def test_user_story_tracker_has_no_open_local_defects():
    tracker = TRACKER.read_text(encoding="utf-8")

    assert "| FAIL |" not in tracker
    assert "| Open |" not in tracker

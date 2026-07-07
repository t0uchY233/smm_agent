from pathlib import Path


APPROVAL_PHRASES = (
    "можно публиковать",
    "шеф внес правки",
    "шеф внёс правки",
    "правки внесены",
    "approved",
    "финальная версия",
)


def test_publish_from_script_requires_review_gate_before_ready():
    skill = Path(".codex/skills/publish-from-script/SKILL.md").read_text(encoding="utf-8")

    assert "review_needed" in skill
    assert '"status": "review_needed"' in skill
    assert '"status": "ready"' in skill
    assert "без явного разрешения" in skill

    for phrase in APPROVAL_PHRASES:
        assert phrase in skill


def test_project_docs_describe_review_needed_status():
    docs_path = Path("AGENTS.md") if Path("AGENTS.md").exists() else Path("AGENTS.md")
    docs = docs_path.read_text(encoding="utf-8")
    command = Path(".codex/commands/publish-from-script.md").read_text(encoding="utf-8")

    assert "review_needed" in docs
    assert "uploaded → review_needed → ready" in docs
    assert "review_needed" in command

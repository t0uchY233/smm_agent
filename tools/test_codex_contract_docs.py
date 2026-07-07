from pathlib import Path


DOCX_CONTRACT_PATHS = [
    Path(".codex/commands/video-script.md"),
    Path(".codex/skills/publish-from-script/SKILL.md"),
    Path(".codex/skills/render-with-visuals/SKILL.md"),
]


def test_codex_workflows_use_russian_title_docx_contract():
    for path in DOCX_CONTRACT_PATHS:
        text = path.read_text(encoding="utf-8")

        assert "YYYY-MM-DD-HHMM-alias.docx" not in text, path
        assert "YYYY-MM-DD-HHMM-Русский заголовок.docx" in text, path

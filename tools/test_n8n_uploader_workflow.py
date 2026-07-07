import json
from pathlib import Path


WORKFLOW = Path("n8n.json")


def test_uploader_workflow_exists_without_legacy_blog_publisher():
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    workflow_text = json.dumps(workflow, ensure_ascii=False)
    node_names = {node["name"] for node in workflow["nodes"]}

    assert "https://veselkov.me/api-publish.html" not in workflow_text
    assert "https://veselkov.me/api-set-cover.html" not in workflow_text
    assert "BLOG_API_KEY" not in workflow_text
    assert "📝 Blog publish" not in node_names

    assert "📁 Drive Trigger" in node_names
    assert "🎥 Загрузить на YouTube" in node_names
    assert "📊 Upsert Sheets (uploaded)" in node_names
    assert any(name.startswith("🔌 Webhook: Lookup") for name in node_names)
    assert any(name.startswith("🔌 Webhook: Update") for name in node_names)


def test_uploader_workflow_documents_russian_title_filename_contract():
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    workflow_text = json.dumps(workflow, ensure_ascii=False)

    assert "YYYY-MM-DD-HHMM-alias.mp4" not in workflow_text
    assert "YYYY-MM-DD-HHMM-Русский заголовок.mp4" in workflow_text
    assert "alias.replace(/-/g, ' ')" not in workflow_text

import json
from pathlib import Path


WORKFLOW = Path("n8n-wordpress-publisher.json")


def test_wordpress_publisher_workflow_uses_wordpress_node_instead_of_veselkov_http_api():
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    workflow_text = json.dumps(workflow, ensure_ascii=False)

    assert "https://veselkov.me/api-publish.html" not in workflow_text
    assert "https://veselkov.me/api-set-cover.html" not in workflow_text
    assert "BLOG_API_KEY" not in workflow_text

    blog_nodes = [node for node in workflow["nodes"] if node["name"] == "📝 Blog publish"]
    assert len(blog_nodes) == 1

    blog_node = blog_nodes[0]
    assert blog_node["type"] == "n8n-nodes-base.wordpress"
    assert blog_node["parameters"]["resource"] == "post"
    assert blog_node["parameters"]["operation"] == "create"
    assert blog_node["parameters"]["status"] == "publish"
    assert "cover_url" in blog_node["parameters"]["content"]
    assert "blog_html" in blog_node["parameters"]["content"]


def test_wordpress_publisher_updates_blog_url_from_wordpress_link():
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    mark_nodes = [node for node in workflow["nodes"] if node["name"] == "✅ Update Sheets (published)"]
    assert len(mark_nodes) == 1

    value = mark_nodes[0]["parameters"]["columns"]["value"]["blog_url"]
    assert "$('📝 Blog publish').item.json.link" in value
    assert "$('📝 Blog publish').item.json.url" in value

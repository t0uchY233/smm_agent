import json
from pathlib import Path


WORKFLOWS = [
    Path("n8n-wordpress-publisher.json"),
]

REQUIRED_FOOTER_LINKS = {
    "https://www.youtube.com/@veselkoveconomy/videos": "Подписывайтесь на наш YouTube-канал",
    "https://t.me/veselkoveconomy": "Подписывайтесь на наш телеграмм-канал",
    "https://www.litres.ru/book/sergey-veselkov/umnyy-biznes-ii-formula-uspeha-72925777/": "Умный бизнес + ИИ = формула успеха",
    "https://www.litres.ru/book/sergey-veselkov/sekrety-pribylnogo-biznesa-kontrintuitivnoe-upravlenie-na-70437511/chitat-onlayn/?clckid=aee1dd14": "Секреты прибыльного бизнеса",
    "https://krymov.skillspace.ru/course/24937/about?clckid=6612fe12": "Проходите бесплатный курс по экономике",
}


def _blog_publish_json_body(workflow_path: Path) -> str:
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    blog_nodes = [node for node in workflow["nodes"] if node["id"] == "blog-publish"]

    assert len(blog_nodes) == 1
    parameters = blog_nodes[0]["parameters"]
    return parameters.get("jsonBody") or parameters.get("content")


def test_blog_publish_appends_clickable_footer_links():
    for workflow_path in WORKFLOWS:
        json_body = _blog_publish_json_body(workflow_path)

        assert "blog_html" in json_body

        for url, link_text in REQUIRED_FOOTER_LINKS.items():
            assert url in json_body, workflow_path
            assert link_text in json_body, workflow_path

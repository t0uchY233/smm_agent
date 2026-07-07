import base64
import json
import os
from unittest.mock import patch


class FakeResponse:
    def __init__(self, payload, code=201):
        self.payload = payload
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_upload_media_posts_binary_to_wordpress_media_endpoint():
    os.environ["WORDPRESS_API_BASE_URL"] = "https://example.com/wp-json/wp/v2"
    os.environ["WORDPRESS_USERNAME"] = "bot"
    os.environ["WORDPRESS_APP_PASSWORD"] = "app pass"

    from tools.wordpress_media import upload_media_bytes

    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        captured["timeout"] = timeout
        return FakeResponse({"id": 77, "source_url": "https://example.com/wp-content/uploads/cover.png"})

    with patch("urllib.request.urlopen", fake_urlopen):
        result = upload_media_bytes(b"png-data", "cover.png", "image/png")

    assert captured["url"] == "https://example.com/wp-json/wp/v2/media"
    assert captured["method"] == "POST"
    assert captured["data"] == b"png-data"
    assert captured["headers"]["Content-type"] == "image/png"
    assert "attachment; filename=cover.png" in captured["headers"]["Content-disposition"]
    assert captured["headers"]["Authorization"].startswith("Basic ")
    assert base64.b64decode(captured["headers"]["Authorization"].split()[1]).decode() == "bot:app pass"
    assert result["id"] == 77
    assert result["source_url"] == "https://example.com/wp-content/uploads/cover.png"


def test_wordpress_api_base_url_supports_unicode_domain():
    os.environ.pop("WORDPRESS_API_BASE_URL", None)
    os.environ["WORDPRESS_BASE_URL"] = "https://веселков.рф"

    from tools.wordpress_media import get_wordpress_api_base_url

    assert get_wordpress_api_base_url() == "https://xn--b1aaiazfwu.xn--p1ai/wp-json/wp/v2"

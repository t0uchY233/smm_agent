import base64
import json
import sys

import pytest

from tools import generate_cover as gc


class FakeResponse:
    def __init__(self, payload, code=200):
        self.payload = payload
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_save_locally_transliterates_russian_title_and_writes_png(tmp_path):
    image_b64 = base64.b64encode(b"png-data").decode("ascii")

    filepath, filename = gc.save_locally(image_b64, "Топ 5 экономических инструментов", tmp_path)

    assert filename == "cover-top-5-ekonomicheskikh-instrumentov.png"
    assert (tmp_path / filename).read_bytes() == b"png-data"
    assert filepath == str(tmp_path / filename)


def test_generate_image_exits_when_openrouter_key_missing(monkeypatch):
    monkeypatch.setattr(gc, "OPENROUTER_API_KEY", "")

    with pytest.raises(SystemExit) as exc:
        gc.generate_image("Заголовок")

    assert exc.value.code == 1


def test_generate_image_extracts_base64_from_openrouter_message_images(monkeypatch):
    expected_b64 = base64.b64encode(b"image-bytes").decode("ascii")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "images": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/webp;base64,{expected_b64}"},
                                }
                            ]
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(gc, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(gc.urllib.request, "urlopen", fake_urlopen)

    image_b64, image_mime = gc.generate_image("Русский заголовок", style="blog", use_face=False)

    assert image_b64 == expected_b64
    assert image_mime == "image/webp"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["messages"][0]["content"][0]["type"] == "text"
    assert all(part.get("type") != "image_url" for part in captured["payload"]["messages"][0]["content"])
    assert captured["timeout"] == 120


def test_upload_to_wordpress_decodes_base64_and_returns_media(monkeypatch):
    captured = {}

    def fake_upload(data, filename, content_type):
        captured["args"] = (data, filename, content_type)
        return {
            "id": 11,
            "source_url": "https://example.com/uploads/cover.png",
            "filename": filename,
            "size": len(data),
        }

    monkeypatch.setattr(gc, "upload_media_bytes", fake_upload)

    result = gc.upload_to_wordpress(base64.b64encode(b"png-data").decode("ascii"), "cover.png")

    assert captured["args"] == (b"png-data", "cover.png", "image/png")
    assert result["id"] == 11
    assert result["source_url"] == "https://example.com/uploads/cover.png"


def test_generate_cover_main_prints_json_with_uploaded_media(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_cover.py",
            "Тестовая обложка",
            "--output",
            str(tmp_path),
            "--upload",
            "--no-face",
        ],
    )
    monkeypatch.setattr(gc, "generate_image", lambda title, style, use_face=True: (base64.b64encode(b"png-data").decode("ascii"), "image/png"))
    monkeypatch.setattr(
        gc,
        "upload_to_wordpress",
        lambda image_b64, filename: {"id": 9, "source_url": "https://example.com/uploads/cover.png"},
    )

    gc.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["filename"] == "cover-testovaya-oblozhka.png"
    assert payload["media_id"] == 9
    assert payload["url"] == "https://example.com/uploads/cover.png"
    assert (tmp_path / payload["filename"]).read_bytes() == b"png-data"

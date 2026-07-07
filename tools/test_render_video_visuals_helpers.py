import json
import subprocess
import urllib.error

import pytest
from PIL import Image

from tools import render_video_visuals as rv


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _make_raw_video(path, duration="1.2"):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=700:sample_rate=44100",
            "-t",
            duration,
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _make_card(path):
    Image.new("RGB", rv.CARD_SIZE, "#ffffff").save(path, "PNG")


def test_parse_env_strips_quotes_and_ignores_comments(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# comment",
                "PLAIN=value",
                "DOUBLE=\"quoted value\"",
                "SINGLE='single quoted'",
                "BROKEN",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert rv.parse_env(env_path) == {
        "PLAIN": "value",
        "DOUBLE": "quoted value",
        "SINGLE": "single quoted",
    }


def test_read_docx_via_tool_raises_render_error_on_subprocess_failure(monkeypatch):
    def fake_run(cmd, cwd, text, capture_output):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="bad docx")

    monkeypatch.setattr(rv.subprocess, "run", fake_run)

    with pytest.raises(rv.RenderVisualsError, match="bad docx"):
        rv.read_docx_via_tool("missing.docx")


def test_http_json_sends_payload_and_parses_response(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"ok": True})

    monkeypatch.setattr(rv.urllib.request, "urlopen", fake_urlopen)

    result = rv.http_json("POST", "https://api.example.test", "api-key", {"x": "тест"}, timeout=9)

    assert result == {"ok": True}
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "api-key"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["data"] == {"x": "тест"}
    assert captured["timeout"] == 9


def test_http_json_wraps_http_error_body(monkeypatch):
    class ErrorBody:
        def read(self):
            return b"failure detail"

        def close(self):
            return None

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url,
            500,
            "server error",
            hdrs={},
            fp=ErrorBody(),
        )

    monkeypatch.setattr(rv.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(rv.RenderVisualsError, match="AssemblyAI HTTP 500: failure detail"):
        rv.http_json("GET", "https://api.example.test", "api-key")


def test_upload_to_assemblyai_posts_audio_bytes(monkeypatch, tmp_path):
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"audio")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        captured["timeout"] = timeout
        return FakeResponse({"upload_url": "https://cdn.example/audio"})

    monkeypatch.setattr(rv.urllib.request, "urlopen", fake_urlopen)

    upload_url = rv.upload_to_assemblyai(audio_path, "api-key", base_url="https://assembly.example")

    assert upload_url == "https://cdn.example/audio"
    assert captured["url"] == "https://assembly.example/v2/upload"
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "api-key"
    assert captured["data"] == b"audio"
    assert captured["timeout"] == 300


def test_extract_audio_writes_mono_mp3_for_asr(tmp_path):
    raw = tmp_path / "raw.mp4"
    audio = tmp_path / "audio.mp3"
    _make_raw_video(raw)

    rv.extract_audio(raw, audio)

    assert audio.exists()
    assert audio.stat().st_size > 0


def test_render_video_with_enabled_overlays_creates_output_mp4(tmp_path):
    raw = tmp_path / "raw.mp4"
    card = tmp_path / "card.png"
    output = tmp_path / "overlay.mp4"
    _make_raw_video(raw)
    _make_card(card)

    rv.render_video_with_enabled_overlays(
        raw,
        [{"image_path": str(card), "start_sec": 0.2, "end_sec": 0.9}],
        output,
    )

    assert output.exists()
    assert output.stat().st_size > 0


def test_transcribe_with_assemblyai_polls_until_completed(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(rv, "upload_to_assemblyai", lambda audio_path, api_key, base_url: "https://cdn.example/audio")

    def fake_http_json(method, url, api_key, payload=None):
        calls.append((method, url, payload))
        if method == "POST":
            return {"id": "tr-1"}
        return {"status": "completed", "text": "готово", "words": []}

    monkeypatch.setattr(rv, "http_json", fake_http_json)

    result = rv.transcribe_with_assemblyai(
        tmp_path / "audio.mp3",
        "api-key",
        language_code="ru",
        base_url="https://assembly.example",
        poll_seconds=0,
        timeout_seconds=5,
    )

    assert result["text"] == "готово"
    assert calls[0] == (
        "POST",
        "https://assembly.example/v2/transcript",
        {
            "audio_url": "https://cdn.example/audio",
            "language_code": "ru",
            "speech_models": ["universal-3-pro", "universal-2"],
            "punctuate": True,
            "format_text": True,
        },
    )
    assert calls[1] == ("GET", "https://assembly.example/v2/transcript/tr-1", None)


def test_transcribe_with_assemblyai_raises_on_error_status(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "upload_to_assemblyai", lambda audio_path, api_key, base_url: "https://cdn.example/audio")
    monkeypatch.setattr(
        rv,
        "http_json",
        lambda method, url, api_key, payload=None: {"id": "tr-1"} if method == "POST" else {"status": "error", "error": "bad audio"},
    )

    with pytest.raises(rv.RenderVisualsError, match="bad audio"):
        rv.transcribe_with_assemblyai(tmp_path / "audio.mp3", "api-key", poll_seconds=0, timeout_seconds=5)

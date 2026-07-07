import pytest
import urllib.request

from tools import validate_dzen_rss as rss


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body.encode("utf-8")


def test_fetch_feed_uses_validator_user_agent(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["timeout"] = timeout
        return FakeResponse("<rss></rss>")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    xml = rss.fetch_feed("https://example.com/feed.xml")

    assert xml == "<rss></rss>"
    assert captured["url"] == "https://example.com/feed.xml"
    assert captured["headers"]["User-agent"] == "DzenRSSValidator/1.0"
    assert captured["timeout"] == 30


def test_validate_dzen_rss_main_exits_success_for_clean_feed(monkeypatch, capsys):
    monkeypatch.setattr(rss.sys, "argv", ["validate_dzen_rss.py", "https://example.com/feed.xml"])
    monkeypatch.setattr(rss, "fetch_feed", lambda url: "<rss></rss>")
    monkeypatch.setattr(rss, "validate_feed", lambda xml: [])

    with pytest.raises(SystemExit) as exc:
        rss.main()

    output = capsys.readouterr().out
    assert exc.value.code == 0
    assert "STATUS: PASS" in output


def test_validate_dzen_rss_main_exits_failure_when_fetch_fails(monkeypatch, capsys):
    def fail_fetch(url):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(rss.sys, "argv", ["validate_dzen_rss.py", "https://example.com/feed.xml"])
    monkeypatch.setattr(rss, "fetch_feed", fail_fetch)

    with pytest.raises(SystemExit) as exc:
        rss.main()

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "Cannot fetch feed" in output

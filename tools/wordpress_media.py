import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - keeps helper usable without python-dotenv
    load_dotenv = None

if load_dotenv:
    load_dotenv()


class WordPressMediaError(RuntimeError):
    pass


def _normalize_url(url):
    parts = urllib.parse.urlsplit(url.strip().rstrip("/"))
    host = parts.hostname.encode("idna").decode("ascii") if parts.hostname else ""
    if parts.port:
        host = f"{host}:{parts.port}"

    path = urllib.parse.quote(parts.path, safe="/%")
    query = urllib.parse.quote(parts.query, safe="=&?/:+,%")
    return urllib.parse.urlunsplit((parts.scheme, host, path, query, parts.fragment))


def get_wordpress_api_base_url():
    api_base = os.getenv("WORDPRESS_API_BASE_URL", "").strip()
    if api_base:
        return _normalize_url(api_base)

    site_base = os.getenv("WORDPRESS_BASE_URL", "").strip()
    if not site_base:
        raise WordPressMediaError("WORDPRESS_API_BASE_URL or WORDPRESS_BASE_URL is required")

    return _normalize_url(site_base.rstrip("/") + "/wp-json/wp/v2")


def _auth_header():
    username = os.getenv("WORDPRESS_USERNAME", "").strip()
    password = os.getenv("WORDPRESS_APP_PASSWORD", "").strip()
    if not username or not password:
        raise WordPressMediaError("WORDPRESS_USERNAME and WORDPRESS_APP_PASSWORD are required")

    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _safe_filename(filename):
    name = os.path.basename(filename or "image.png")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return name or "image.png"


def upload_media_bytes(data, filename, content_type, timeout=None):
    filename = _safe_filename(filename)
    endpoint = get_wordpress_api_base_url().rstrip("/") + "/media"
    timeout = int(timeout or os.getenv("WORDPRESS_TIMEOUT_SECONDS", "30"))

    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Authorization": _auth_header(),
            "Content-Type": content_type,
            "Content-Disposition": f"attachment; filename={filename}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise WordPressMediaError(f"WordPress media upload HTTP {e.code}: {body[:500]}") from e

    if not result.get("id") or not result.get("source_url"):
        raise WordPressMediaError(f"Unexpected WordPress media response: {json.dumps(result, ensure_ascii=False)[:500]}")

    return {
        "id": result["id"],
        "source_url": result["source_url"],
        "filename": filename,
        "size": len(data),
        "raw": result,
    }

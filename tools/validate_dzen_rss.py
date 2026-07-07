"""
Валидатор RSS-ленты для Яндекс Дзена.
Проверяет соответствие требованиям: https://dzen.ru/help/ru/website/rss-modify.html

Использование:
    python tools/validate_dzen_rss.py [URL]
    python tools/validate_dzen_rss.py  # по умолчанию https://veselkov.me/in/feed.xml
"""
import sys
import io
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs
from email.utils import parsedate_to_datetime

# UTF-8 настройка только при прямом запуске — см. main()

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

MIN_ITEMS = 10
MIN_CONTENT_LENGTH = 300  # символов текста без тегов
MIN_IMAGE_WIDTH = 700  # пикселей

REQUIRED_NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom",
}

# Теги, разрешённые Дзеном внутри content:encoded
ALLOWED_CONTENT_TAGS = {
    "p", "a", "b", "i", "u", "s",
    "h1", "h2", "h3", "h4",
    "blockquote",
    "ul", "ol", "li",
    "figure", "figcaption", "img",
    "video", "source",
    "span",  # только внутри figcaption с class="copyright"
    "br",
}

# Теги, запрещённые Дзеном
FORBIDDEN_CONTENT_TAGS = {
    "iframe", "div", "table", "tr", "td", "th", "thead", "tbody",
    "script", "style", "form", "input", "select", "textarea",
    "header", "footer", "nav", "section", "article", "aside",
    "meta", "link",
}

VALID_CATEGORIES = {
    "format-article", "format-post", "native-draft",
    "index", "noindex",
    "comment-all", "comment-subscribers", "comment-none",
}

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom",
    "georss": "http://www.georss.org/georss",
}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def strip_html(html: str) -> str:
    """Удаляет HTML-теги, возвращает чистый текст."""
    if not html:
        return ""
    return re.sub(r"<[^>]+>", "", html).strip()


def _extract_tags_from_html(html: str) -> set:
    """Извлекает все имена HTML-тегов из строки."""
    return {m.lower() for m in re.findall(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)", html) for m in [m[1]]}


def _extract_tags_from_html(html: str) -> set:
    """Извлекает все имена HTML-тегов из строки."""
    tags = set()
    for match in re.finditer(r"</?([a-zA-Z][a-zA-Z0-9]*)", html):
        tags.add(match.group(1).lower())
    return tags


# Атрибуты, разрешённые Дзеном (только на определённых тегах)
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height"},
    "video": {"src", "width", "height"},
    "source": {"src", "type"},
}

# Атрибуты, запрещённые на любых тегах
FORBIDDEN_ATTRIBUTES = {"class", "id", "style", "onclick", "onload"}


def _check_forbidden_attributes(html: str) -> list:
    """Проверяет наличие запрещённых атрибутов (class, data-*, id, style) на HTML-тегах."""
    issues = []
    # Ищем открывающие теги с атрибутами
    for match in re.finditer(r"<([a-zA-Z][a-zA-Z0-9]*)\s+([^>]+?)\/?>", html):
        tag = match.group(1).lower()
        attr_str = match.group(2)
        # Проверяем каждый атрибут
        for attr_match in re.finditer(r'([a-zA-Z_][\w-]*)\s*=', attr_str):
            attr_name = attr_match.group(1).lower()
            # data-* атрибуты запрещены
            if attr_name.startswith("data-"):
                issues.append(f"forbidden attribute '{attr_name}' on <{tag}>")
                continue
            # Явно запрещённые атрибуты
            if attr_name in FORBIDDEN_ATTRIBUTES:
                issues.append(f"forbidden attribute '{attr_name}' on <{tag}>")
                continue
            # Проверяем, разрешён ли атрибут для этого тега
            allowed = ALLOWED_ATTRIBUTES.get(tag, set())
            if attr_name not in allowed and attr_name not in {"href", "src", "alt", "title", "target", "width", "height", "type"}:
                issues.append(f"non-standard attribute '{attr_name}' on <{tag}>")
    return issues


# ---------------------------------------------------------------------------
# Парсинг
# ---------------------------------------------------------------------------

def fetch_feed(url: str) -> str:
    """Загружает RSS-ленту по URL."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "DzenRSSValidator/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_feed(xml_str: str) -> ET.Element:
    """Парсит XML-строку в ElementTree root."""
    if not xml_str:
        raise ET.ParseError("Empty XML string")
    return ET.fromstring(xml_str)


# ---------------------------------------------------------------------------
# Валидация channel
# ---------------------------------------------------------------------------

def validate_channel(root: ET.Element) -> list:
    """Проверяет метаданные channel."""
    errors = []
    channel = root.find("channel")
    if channel is None:
        return ["FAIL: Channel element missing"]

    title = channel.find("title")
    if title is None or not (title.text or "").strip():
        errors.append("FAIL: Channel title is missing or empty")

    link = channel.find("link")
    if link is None or not (link.text or "").strip():
        errors.append("FAIL: Channel link is missing or empty")

    lang = channel.find("language")
    if lang is None or not (lang.text or "").strip():
        errors.append("FAIL: Channel language is missing")
    elif lang.text.strip() not in ("ru", "ru-RU"):
        errors.append(f"WARN: Channel language is '{lang.text}', expected 'ru'")

    return errors


# ---------------------------------------------------------------------------
# Валидация item
# ---------------------------------------------------------------------------

def validate_item(item: ET.Element, index: int) -> list:
    """Проверяет один item на соответствие требованиям Дзена."""
    errors = []
    prefix = f"Item #{index + 1}"

    # title (обязательный)
    title_el = item.find("title")
    title_text = (title_el.text or "").strip() if title_el is not None else ""
    if not title_text:
        errors.append(f"FAIL: {prefix} — title is missing or empty")

    # link (обязательный, ЧПУ, без UTM)
    link_el = item.find("link")
    link_text = (link_el.text or "").strip() if link_el is not None else ""
    if not link_text:
        errors.append(f"FAIL: {prefix} — link is missing or empty")
    else:
        parsed = urlparse(link_text)
        params = parse_qs(parsed.query)
        if params:
            errors.append(f"FAIL: {prefix} — link has query params (UTM?): {link_text}")

    # guid (обязательный)
    guid_el = item.find("guid")
    guid_text = (guid_el.text or "").strip() if guid_el is not None else ""
    if not guid_text:
        errors.append(f"FAIL: {prefix} — guid is missing or empty")

    # pubDate (обязательный, RFC822)
    pubdate_el = item.find("pubDate")
    pubdate_text = (pubdate_el.text or "").strip() if pubdate_el is not None else ""
    if not pubdate_text:
        errors.append(f"FAIL: {prefix} — pubDate is missing or empty")
    else:
        try:
            parsedate_to_datetime(pubdate_text)
        except Exception:
            errors.append(f"FAIL: {prefix} — pubDate is not valid RFC822: '{pubdate_text}'")

    # category (обязательный)
    cat_el = item.find("category")
    cat_text = (cat_el.text or "").strip() if cat_el is not None else ""
    if not cat_text:
        errors.append(f"FAIL: {prefix} — category is missing or empty")
    elif cat_text not in VALID_CATEGORIES:
        errors.append(f"FAIL: {prefix} — category '{cat_text}' is invalid. Expected one of: {VALID_CATEGORIES}")

    # content:encoded (обязательный, ≥300 символов, разрешённые теги)
    content_el = item.find("content:encoded", NS)
    content_html = (content_el.text or "").strip() if content_el is not None else ""
    content_text = strip_html(content_html)

    if not content_text:
        errors.append(f"FAIL: {prefix} — content:encoded is missing or empty")
    elif len(content_text) < MIN_CONTENT_LENGTH:
        errors.append(
            f"FAIL: {prefix} — content:encoded text is {len(content_text)} chars, "
            f"minimum {MIN_CONTENT_LENGTH} required"
        )

    # Запрещённые теги в content
    if content_html:
        used_tags = _extract_tags_from_html(content_html)
        forbidden_found = used_tags & FORBIDDEN_CONTENT_TAGS
        if forbidden_found:
            errors.append(
                f"FAIL: {prefix} — content:encoded has forbidden tags: {', '.join(sorted(forbidden_found))}"
            )

    # YouTube iframe в content
    if content_html and re.search(r"<iframe[^>]*youtube", content_html, re.IGNORECASE):
        errors.append(
            f"FAIL: {prefix} — content:encoded has YouTube iframe. "
            f"Use plain link instead: https://www.youtube.com/watch?v=VIDEO_ID"
        )

    # Запрещённые атрибуты (class, data-*, id, style)
    if content_html:
        attr_issues = _check_forbidden_attributes(content_html)
        if attr_issues:
            # Дедуплицируем типы проблем для краткости
            unique_issues = sorted(set(attr_issues))
            summary = "; ".join(unique_issues[:5])
            if len(unique_issues) > 5:
                summary += f" ... (+{len(unique_issues) - 5} more)"
            errors.append(f"FAIL: {prefix} — content:encoded has forbidden HTML attributes: {summary}")

    # enclosure (рекомендуется)
    encl_el = item.find("enclosure")
    if encl_el is None:
        errors.append(f"WARN: {prefix} — enclosure (cover image) is missing")
    else:
        encl_type = encl_el.get("type", "")
        encl_url = encl_el.get("url", "")
        if not encl_url:
            errors.append(f"FAIL: {prefix} — enclosure url is empty")
        if not encl_type.startswith("image/"):
            errors.append(f"FAIL: {prefix} — enclosure type '{encl_type}' is not image/*")

    # description (рекомендуется)
    desc_el = item.find("description")
    desc_text = ""
    if desc_el is not None:
        desc_text = (desc_el.text or "").strip()
    if not desc_text:
        errors.append(f"WARN: {prefix} — description is empty (recommended for card display)")

    return errors


# ---------------------------------------------------------------------------
# Полная валидация фида
# ---------------------------------------------------------------------------

def validate_feed(xml_str: str) -> list:
    """Валидирует полный RSS-фид. Возвращает список ошибок/предупреждений."""
    errors = []
    root = parse_feed(xml_str)

    # Проверяем namespaces
    # ElementTree не хранит namespaces напрямую, парсим из raw XML
    for ns_name, ns_uri in REQUIRED_NAMESPACES.items():
        if ns_uri not in xml_str:
            errors.append(f"FAIL: Required namespace '{ns_name}' ({ns_uri}) missing")

    # Channel metadata
    errors.extend(validate_channel(root))

    # Items
    channel = root.find("channel")
    if channel is None:
        return errors

    items = channel.findall("item")

    if len(items) < MIN_ITEMS:
        errors.append(
            f"FAIL: Feed has {len(items)} items, minimum {MIN_ITEMS} required for Dzen initial submission"
        )

    # Уникальность guid
    guids = []
    for item in items:
        guid_el = item.find("guid")
        if guid_el is not None and guid_el.text:
            guids.append(guid_el.text.strip())
    if len(guids) != len(set(guids)):
        seen = set()
        duplicates = set()
        for g in guids:
            if g in seen:
                duplicates.add(g)
            seen.add(g)
        errors.append(f"FAIL: Duplicate guid(s) found: {', '.join(sorted(duplicates))}")

    # Валидация каждого item
    for i, item in enumerate(items):
        errors.extend(validate_item(item, i))

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Настройка UTF-8 для Windows
    if sys.stdout and hasattr(sys.stdout, "buffer") and (sys.stdout.encoding or "").lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    url = sys.argv[1] if len(sys.argv) > 1 else "https://veselkov.me/in/feed.xml"

    print(f"Validating RSS feed: {url}")
    print("=" * 60)

    try:
        xml_str = fetch_feed(url)
    except Exception as e:
        print(f"FAIL: Cannot fetch feed — {e}")
        sys.exit(1)

    errors = validate_feed(xml_str)

    fails = [e for e in errors if e.startswith("FAIL")]
    warns = [e for e in errors if e.startswith("WARN")]

    for e in errors:
        print(e)

    print("=" * 60)
    print(f"Results: {len(fails)} errors, {len(warns)} warnings")

    if fails:
        print("\nSTATUS: FAIL — feed does NOT meet Dzen requirements")
        sys.exit(1)
    elif warns:
        print("\nSTATUS: PASS with warnings")
        sys.exit(0)
    else:
        print("\nSTATUS: PASS — feed meets all Dzen requirements")
        sys.exit(0)


if __name__ == "__main__":
    main()

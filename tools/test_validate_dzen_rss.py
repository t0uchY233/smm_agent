"""
TDD-тесты для валидатора RSS-ленты Яндекс Дзена.
Требования: https://dzen.ru/help/ru/website/rss-modify.html

Запуск: pytest tools/test_validate_dzen_rss.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from validate_dzen_rss import (
    fetch_feed,
    parse_feed,
    validate_channel,
    validate_item,
    validate_feed,
    strip_html,
    _check_forbidden_attributes,
    ALLOWED_CONTENT_TAGS,
    FORBIDDEN_CONTENT_TAGS,
    MIN_ITEMS,
    MIN_CONTENT_LENGTH,
    MIN_IMAGE_WIDTH,
    REQUIRED_NAMESPACES,
)


# ---------------------------------------------------------------------------
# Фикстуры: минимальный валидный и невалидный RSS
# ---------------------------------------------------------------------------

VALID_ITEM_XML = """\
<item>
  <title>Тестовая статья о бизнесе</title>
  <link>https://veselkov.me/in/upravlenie/test-article.html</link>
  <guid>https://veselkov.me/in/upravlenie/test-article.html</guid>
  <pubDate>Tue, 15 Apr 2026 10:00:00 +0300</pubDate>
  <category>format-article</category>
  <description><![CDATA[Описание статьи для карточки в ленте Дзена.]]></description>
  <enclosure url="https://veselkov.me/assets/images/products/671/800x600/cover.jpg" type="image/jpeg"/>
  <content:encoded><![CDATA[<p>Это полноценный текст статьи, который содержит более трёхсот символов. Здесь мы разбираем важную тему управления бизнесом, обсуждаем ключевые метрики и показатели эффективности. Каждый предприниматель должен понимать, как работает поток денежных средств в компании и почему буфер запасов критически важен для стабильной работы бизнеса. Рассмотрим конкретный пример.</p><h2>Основная часть</h2><p>Продолжение текста статьи с деталями и примерами.</p>]]></content:encoded>
</item>"""


def _build_feed_xml(items_xml: str, num_items: int = 10) -> str:
    """Собирает полный RSS-фид из XML-строк items."""
    items = items_xml * num_items if num_items > 1 else items_xml
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:media="http://search.yahoo.com/mrss/"
  xmlns:atom="http://www.w3.org/2005/Atom"
  xmlns:georss="http://www.georss.org/georss">
<channel>
  <title>Блог Веселкова С.Н.</title>
  <link>https://veselkov.me/</link>
  <description>Блог о бизнесе, управлении и стратегии</description>
  <language>ru</language>
  {items}
</channel>
</rss>"""


def _make_item(**overrides) -> str:
    """Генерирует XML item с возможностью переопределения полей."""
    defaults = {
        "title": "Тестовая статья",
        "link": "https://veselkov.me/in/upravlenie/test.html",
        "guid": "https://veselkov.me/in/upravlenie/test.html",
        "pubDate": "Tue, 15 Apr 2026 10:00:00 +0300",
        "category": "format-article",
        "description": "Описание статьи.",
        "enclosure_url": "https://veselkov.me/img/cover.jpg",
        "enclosure_type": "image/jpeg",
        "content": "<p>" + ("А" * 350) + "</p>",
    }
    defaults.update(overrides)

    enclosure = ""
    if defaults.get("enclosure_url"):
        enclosure = f'<enclosure url="{defaults["enclosure_url"]}" type="{defaults["enclosure_type"]}"/>'

    description = ""
    if defaults.get("description"):
        description = f'<description><![CDATA[{defaults["description"]}]]></description>'

    return f"""\
<item>
  <title>{defaults["title"]}</title>
  <link>{defaults["link"]}</link>
  <guid>{defaults["guid"]}</guid>
  <pubDate>{defaults["pubDate"]}</pubDate>
  <category>{defaults["category"]}</category>
  {description}
  {enclosure}
  <content:encoded><![CDATA[{defaults["content"]}]]></content:encoded>
</item>"""


@pytest.fixture
def valid_feed_xml():
    return _build_feed_xml(VALID_ITEM_XML, num_items=10)


@pytest.fixture
def valid_feed(valid_feed_xml):
    return parse_feed(valid_feed_xml)


# ---------------------------------------------------------------------------
# 1. Парсинг XML
# ---------------------------------------------------------------------------

class TestFeedParsing:
    def test_valid_xml_parses(self, valid_feed_xml):
        result = parse_feed(valid_feed_xml)
        assert result is not None

    def test_invalid_xml_raises(self):
        with pytest.raises(ET.ParseError):
            parse_feed("<not>valid<xml")

    def test_empty_string_raises(self):
        with pytest.raises(ET.ParseError):
            parse_feed("")


# ---------------------------------------------------------------------------
# 2. Namespaces
# ---------------------------------------------------------------------------

class TestNamespaces:
    def test_required_namespaces_present(self, valid_feed_xml):
        errors = validate_feed(valid_feed_xml)
        ns_errors = [e for e in errors if "namespace" in e.lower()]
        assert len(ns_errors) == 0

    def test_missing_namespace_reported(self):
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Test</title>
  <link>https://example.com/</link>
  <language>ru</language>
</channel>
</rss>"""
        errors = validate_feed(xml)
        ns_errors = [e for e in errors if "namespace" in e.lower()]
        assert len(ns_errors) > 0


# ---------------------------------------------------------------------------
# 3. Channel metadata
# ---------------------------------------------------------------------------

class TestChannelMetadata:
    def test_channel_has_title(self, valid_feed_xml):
        errors = validate_feed(valid_feed_xml)
        assert not any("channel title" in e.lower() for e in errors)

    def test_channel_has_link(self, valid_feed_xml):
        errors = validate_feed(valid_feed_xml)
        assert not any("channel link" in e.lower() for e in errors)

    def test_channel_has_language_ru(self, valid_feed_xml):
        errors = validate_feed(valid_feed_xml)
        assert not any("language" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# 4. Количество items
# ---------------------------------------------------------------------------

class TestItemCount:
    def test_minimum_10_items(self, valid_feed_xml):
        errors = validate_feed(valid_feed_xml)
        assert not any("minimum" in e.lower() and "item" in e.lower() for e in errors)

    def test_fewer_than_10_items_fails(self):
        xml = _build_feed_xml(VALID_ITEM_XML, num_items=1)
        errors = validate_feed(xml)
        count_errors = [e for e in errors if "minimum" in e.lower() and "item" in e.lower()]
        assert len(count_errors) > 0

    def test_exactly_10_items_passes(self):
        items = ""
        for i in range(10):
            items += _make_item(
                guid=f"https://veselkov.me/in/article-{i}.html",
                link=f"https://veselkov.me/in/article-{i}.html",
            )
        xml = _build_feed_xml(items, num_items=1)
        errors = validate_feed(xml)
        count_errors = [e for e in errors if "minimum" in e.lower() and "item" in e.lower()]
        assert len(count_errors) == 0


# ---------------------------------------------------------------------------
# 5. Обязательные поля item
# ---------------------------------------------------------------------------

class TestItemRequiredFields:
    def test_item_has_title(self):
        item_xml = _make_item(title="")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("title" in e.lower() for e in errors)

    def test_item_has_link(self):
        item_xml = _make_item(link="")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("link" in e.lower() for e in errors)

    def test_item_has_guid(self):
        item_xml = _make_item(guid="")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("guid" in e.lower() for e in errors)

    def test_item_has_pubdate(self):
        item_xml = _make_item(pubDate="")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("pubdate" in e.lower() for e in errors)

    def test_item_has_category(self):
        item_xml = _make_item(category="")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("category" in e.lower() for e in errors)

    def test_item_has_content_encoded(self):
        item_xml = _make_item(content="")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("content" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# 6. pubDate формат RFC822
# ---------------------------------------------------------------------------

class TestPubDateFormat:
    def test_valid_rfc822(self):
        item_xml = _make_item(pubDate="Tue, 15 Apr 2026 10:00:00 +0300")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert not any("rfc822" in e.lower() for e in errors)

    def test_invalid_date_format(self):
        item_xml = _make_item(pubDate="2026-04-15")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("rfc822" in e.lower() or "pubdate" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# 7. category значения
# ---------------------------------------------------------------------------

class TestCategory:
    def test_format_article_valid(self):
        item_xml = _make_item(category="format-article")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert not any("category" in e.lower() and "invalid" in e.lower() for e in errors)

    def test_format_post_valid(self):
        item_xml = _make_item(category="format-post")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert not any("category" in e.lower() and "invalid" in e.lower() for e in errors)

    def test_invalid_category_reported(self):
        item_xml = _make_item(category="something-wrong")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("category" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# 8. content:encoded — длина и разрешённые теги
# ---------------------------------------------------------------------------

class TestContentEncoded:
    def test_content_min_300_chars(self):
        short = "<p>" + ("А" * 100) + "</p>"
        item_xml = _make_item(content=short)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("300" in e or "content" in e.lower() for e in errors)

    def test_content_300_chars_passes(self):
        long = "<p>" + ("А" * 350) + "</p>"
        item_xml = _make_item(content=long)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        content_len_errors = [e for e in errors if "300" in e and "content" in e.lower()]
        assert len(content_len_errors) == 0

    def test_iframe_forbidden(self):
        content = '<p>Текст статьи.</p><iframe src="https://youtube.com/embed/abc"></iframe><p>' + ("А" * 300) + '</p>'
        item_xml = _make_item(content=content)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("iframe" in e.lower() or "forbidden" in e.lower() or "запрещ" in e.lower() for e in errors)

    def test_div_forbidden(self):
        content = '<div><p>' + ("А" * 350) + '</p></div>'
        item_xml = _make_item(content=content)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("div" in e.lower() or "forbidden" in e.lower() or "запрещ" in e.lower() for e in errors)

    def test_allowed_tags_pass(self):
        content = '<p>Текст.</p><h2>Заголовок</h2><p><b>Жирный</b> и <i>курсив</i>.</p><ul><li>Пункт</li></ul><p>' + ("А" * 300) + '</p>'
        item_xml = _make_item(content=content)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        tag_errors = [e for e in errors if "forbidden" in e.lower() or "запрещ" in e.lower()]
        assert len(tag_errors) == 0

    def test_youtube_link_not_iframe(self):
        content = '<p>' + ("А" * 300) + '</p><p>https://www.youtube.com/watch?v=abc123</p>'
        item_xml = _make_item(content=content)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        yt_errors = [e for e in errors if "youtube" in e.lower() and "iframe" in e.lower()]
        assert len(yt_errors) == 0


# ---------------------------------------------------------------------------
# 9. enclosure
# ---------------------------------------------------------------------------

class TestEnclosure:
    def test_enclosure_present(self):
        item_xml = _make_item()
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert not any("enclosure" in e.lower() and "missing" in e.lower() for e in errors)

    def test_enclosure_missing_reported(self):
        item_xml = _make_item(enclosure_url=None)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("enclosure" in e.lower() for e in errors)

    def test_enclosure_has_image_type(self):
        item_xml = _make_item(enclosure_type="video/mp4")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("enclosure" in e.lower() and "image" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# 10. description
# ---------------------------------------------------------------------------

class TestDescription:
    def test_description_present(self):
        item_xml = _make_item(description="Хорошее описание.")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        desc_errors = [e for e in errors if "description" in e.lower() and "empty" in e.lower()]
        assert len(desc_errors) == 0

    def test_empty_description_warned(self):
        item_xml = _make_item(description="")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("description" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# 11. Уникальность guid
# ---------------------------------------------------------------------------

class TestGuidUniqueness:
    def test_duplicate_guids_reported(self):
        item = _make_item(guid="https://veselkov.me/same-guid.html")
        xml = _build_feed_xml(item, num_items=10)
        errors = validate_feed(xml)
        assert any("guid" in e.lower() and "duplic" in e.lower() for e in errors)

    def test_unique_guids_pass(self):
        items = ""
        for i in range(10):
            items += _make_item(
                guid=f"https://veselkov.me/in/article-{i}.html",
                link=f"https://veselkov.me/in/article-{i}.html",
            )
        xml = _build_feed_xml(items, num_items=1)
        errors = validate_feed(xml)
        guid_errors = [e for e in errors if "guid" in e.lower() and "duplic" in e.lower()]
        assert len(guid_errors) == 0


# ---------------------------------------------------------------------------
# 12. ЧПУ URL (без UTM, query params)
# ---------------------------------------------------------------------------

class TestUrlFormat:
    def test_clean_url_passes(self):
        item_xml = _make_item(link="https://veselkov.me/in/upravlenie/good-article.html")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        url_errors = [e for e in errors if "utm" in e.lower() or "query" in e.lower()]
        assert len(url_errors) == 0

    def test_utm_url_fails(self):
        item_xml = _make_item(link="https://veselkov.me/in/article.html?utm_source=rss")
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("utm" in e.lower() or "query" in e.lower() or "param" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# 13. strip_html утилита
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_strips_tags(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_handles_empty(self):
        assert strip_html("") == ""

    def test_preserves_text(self):
        assert strip_html("plain text") == "plain text"

    def test_strips_cdata_content(self):
        result = strip_html("<p>Текст</p><h2>Заголовок</h2>")
        assert "Текст" in result
        assert "Заголовок" in result


# ---------------------------------------------------------------------------
# 14. HTML-атрибуты
# ---------------------------------------------------------------------------

class TestForbiddenAttributes:
    def test_class_attribute_detected(self):
        html = '<p class="content--common-block__block-3U">Текст</p>'
        issues = _check_forbidden_attributes(html)
        assert any("class" in i for i in issues)

    def test_data_attribute_detected(self):
        html = '<p data-points="5">Текст</p>'
        issues = _check_forbidden_attributes(html)
        assert any("data-points" in i for i in issues)

    def test_id_attribute_detected(self):
        html = '<h2 id="section1">Заголовок</h2>'
        issues = _check_forbidden_attributes(html)
        assert any("id" in i for i in issues)

    def test_style_attribute_detected(self):
        html = '<p style="color:red">Текст</p>'
        issues = _check_forbidden_attributes(html)
        assert any("style" in i for i in issues)

    def test_clean_html_passes(self):
        html = '<p>Текст</p><h2>Заголовок</h2><a href="https://example.com">Ссылка</a>'
        issues = _check_forbidden_attributes(html)
        assert issues == []

    def test_allowed_attrs_pass(self):
        html = '<img src="https://img.com/pic.jpg" alt="Описание" width="800" height="600">'
        issues = _check_forbidden_attributes(html)
        assert issues == []

    def test_multiple_forbidden_attrs(self):
        html = '<p class="x" data-foo="1" data-bar="2">Текст</p>'
        issues = _check_forbidden_attributes(html)
        assert len(issues) >= 3

    def test_item_with_dirty_attrs_fails_validation(self):
        """validate_item должен ловить грязные атрибуты."""
        dirty_content = '<p class="block" data-id="5">' + ("А" * 350) + '</p>'
        item_xml = _make_item(content=dirty_content)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert any("forbidden HTML attributes" in e for e in errors)

    def test_item_with_clean_attrs_passes(self):
        """Чистый HTML без лишних атрибутов не генерирует ошибок атрибутов."""
        clean_content = '<p>' + ("А" * 350) + '</p><a href="https://example.com">Ссылка</a>'
        item_xml = _make_item(content=clean_content)
        xml = _build_feed_xml(item_xml, num_items=10)
        errors = validate_feed(xml)
        assert not any("forbidden HTML attributes" in e for e in errors)

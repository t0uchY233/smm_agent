"""
Чтение DOCX-сценария и парсинг scheduled_at из имени файла.

Использование:
  python tools/read_docx.py "<path-to-docx>"

Возвращает JSON:
  {title, body_text, scheduled_at, alias, source_path}

scheduled_at = "YYYY-MM-DD HH:MM" (MSK), извлекается из имени файла формата
  YYYY-MM-DD-HHMM-alias.docx (например 2026-05-01-1400-burovye-krs.docx).

Если имя в старом формате YYYY-MM-DD-alias.docx (без времени) —
scheduled_at = null, alias извлекается всё равно.
"""
import sys
import io
import os
import json
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from docx import Document


NEW_NAME_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})-(.+)\.docx$')
OLD_NAME_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})-(.+)\.docx$')


def parse_filename(filename):
    m = NEW_NAME_RE.match(filename)
    if m:
        y, mo, d, h, mi, alias = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}", alias
    m = OLD_NAME_RE.match(filename)
    if m:
        _, _, _, alias = m.groups()
        return None, alias
    return None, None


def read_docx(path):
    doc = Document(path)
    title = None
    body_parts = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # Игнорируем разделители и метаданные
        if text.startswith('— — —') or text.startswith('Публикация:'):
            continue
        # Первый Heading становится title
        if title is None and (para.style.name.startswith('Heading') or para.style.name == 'Title'):
            title = text
            continue
        body_parts.append(text)

    # Fallback: если нет Heading, берём первый параграф как title
    if title is None and body_parts:
        title = body_parts.pop(0)

    return title or "", "\n\n".join(body_parts)


def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Usage: python tools/read_docx.py <path-to-docx>"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    filename = os.path.basename(path)
    scheduled_at, alias = parse_filename(filename)

    try:
        title, body_text = read_docx(path)
    except Exception as e:
        print(json.dumps({"error": f"Failed to read DOCX: {e}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    result = {
        "title": title,
        "body_text": body_text,
        "scheduled_at": scheduled_at,
        "alias": alias,
        "source_path": os.path.abspath(path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

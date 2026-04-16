"""
Загрузка изображений на veselkov.me через ApiUpload.

Использование:
  python tools/upload_images.py image1.jpg image2.png
  python tools/upload_images.py --from-docx Вятка.docx

Возвращает JSON со списком загруженных URL.
"""
import sys
import io
import os
import json
import base64
import argparse
import urllib.request
import urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

API_URL = 'https://veselkov.me/api-upload.html'
API_KEY = os.getenv('BLOG_API_KEY')


def extract_images_from_docx(docx_path):
    """Извлекает изображения из DOCX, возвращает список {filename, data_b64, content_type}."""
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(docx_path)
    images = []
    idx = 0

    # Собираем rId изображений в порядке появления в документе
    body = doc.element.body
    seen_rids = []
    for child in body.iter():
        if child.tag.endswith('}blip') or 'blip' in child.tag:
            rid = child.get(qn('r:embed'))
            if rid and rid not in seen_rids:
                seen_rids.append(rid)

    for rid in seen_rids:
        if rid not in doc.part.rels:
            continue
        rel = doc.part.rels[rid]
        if 'image' not in rel.reltype:
            continue

        img_part = rel.target_part
        idx += 1
        ext = img_part.content_type.split('/')[-1]
        if ext == 'jpeg':
            ext = 'jpg'

        # Имя из оригинального ref или генерируем
        orig_name = os.path.splitext(os.path.basename(rel.target_ref))[0]
        filename = f"{orig_name}.{ext}" if orig_name else f"image-{idx}.{ext}"

        images.append({
            'filename': filename,
            'data': base64.b64encode(img_part.blob).decode('ascii'),
            'content_type': img_part.content_type,
        })

    return images


def extract_images_from_files(file_paths):
    """Читает файлы изображений, возвращает список {filename, data_b64, content_type}."""
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif',
    }
    images = []
    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        content_type = mime_map.get(ext)
        if not content_type:
            print(f"Пропуск {path}: неизвестный тип файла", file=sys.stderr)
            continue
        with open(path, 'rb') as f:
            data = base64.b64encode(f.read()).decode('ascii')
        images.append({
            'filename': os.path.basename(path),
            'data': data,
            'content_type': content_type,
        })
    return images


def upload_images(images):
    """Загружает изображения через ApiUpload, возвращает ответ сервера."""
    if not API_KEY:
        print("Ошибка: BLOG_API_KEY не задан в .env", file=sys.stderr)
        sys.exit(1)

    payload = {'images': images}
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-API-Key': API_KEY,
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode('utf-8')
            # MODX может оборачивать JSON в <p> теги
            raw = raw.strip()
            if raw.startswith('<p>') and raw.endswith('</p>'):
                raw = raw[3:-4]
            body = json.loads(raw)
            return body
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"HTTP {e.code}: {error_body}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Загрузка изображений на veselkov.me')
    parser.add_argument('files', nargs='*', help='Файлы изображений для загрузки')
    parser.add_argument('--from-docx', help='Извлечь и загрузить изображения из DOCX файла')
    parser.add_argument('--dry-run', action='store_true', help='Показать что будет загружено, без отправки')
    args = parser.parse_args()

    if args.from_docx:
        images = extract_images_from_docx(args.from_docx)
        print(f"Извлечено {len(images)} изображений из {args.from_docx}", file=sys.stderr)
    elif args.files:
        images = extract_images_from_files(args.files)
    else:
        parser.print_help()
        sys.exit(1)

    if not images:
        print("Нет изображений для загрузки", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        for img in images:
            size_kb = len(base64.b64decode(img['data'])) / 1024
            print(f"  {img['filename']} ({img['content_type']}, {size_kb:.0f} КБ)")
        print(f"\nИтого: {len(images)} файлов")
        return

    print(f"Загрузка {len(images)} изображений...", file=sys.stderr)
    result = upload_images(images)

    # Вывод результата как JSON
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

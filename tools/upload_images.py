"""
Загрузка изображений в WordPress Media Library.

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

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - keeps helper importable without python-dotenv
    load_dotenv = None

if load_dotenv:
    load_dotenv()

try:
    from wordpress_media import WordPressMediaError, upload_media_bytes
except ImportError:
    from tools.wordpress_media import WordPressMediaError, upload_media_bytes


def configure_utf8_stdout():
    if sys.stdout and hasattr(sys.stdout, 'buffer') and (sys.stdout.encoding or '').lower() not in ('utf-8', 'utf8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


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
    """Загружает изображения в WordPress, возвращает совместимый JSON."""
    uploaded = []

    for img in images:
        try:
            binary = base64.b64decode(img['data'])
            result = upload_media_bytes(binary, img['filename'], img['content_type'])
        except (WordPressMediaError, KeyError) as e:
            print(f"Ошибка загрузки {img.get('filename', 'image')}: {e}", file=sys.stderr)
            sys.exit(1)

        uploaded.append({
            'filename': result['filename'],
            'url': result['source_url'],
            'path': result['source_url'],
            'media_id': result['id'],
            'size': result['size'],
        })

    return {
        'success': True,
        'uploaded': uploaded,
        'count': len(uploaded),
    }


def main():
    configure_utf8_stdout()

    parser = argparse.ArgumentParser(description='Загрузка изображений в WordPress Media Library')
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

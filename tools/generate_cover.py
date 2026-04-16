"""
Генерация обложки для статьи блога через OpenRouter (Gemini image gen).

Использование:
  python tools/generate_cover.py "Заголовок статьи"
  python tools/generate_cover.py "Заголовок статьи" --upload
  python tools/generate_cover.py "Заголовок статьи" --upload --style youtube

Флаги:
  --upload     Загрузить на veselkov.me через ApiUpload и вернуть URL
  --style      youtube | blog (по умолчанию blog)
  --output     Путь для локального сохранения (по умолчанию .tmp/covers/)
  --no-face    Не использовать референсное лицо

Возвращает JSON: {url, local_path, filename}
"""
import sys
import io
import os
import json
import base64
import argparse
import urllib.request
import urllib.error
import re
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
BLOG_API_KEY = os.getenv('BLOG_API_KEY')
UPLOAD_URL = 'https://veselkov.me/api-upload.html'
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'

# Референсное фото Веселкова
FACE_REF_URL = 'https://i.ibb.co/TqcDsg6g/Chat-GPT-Image-16-2026-09-10-02.png'

PROMPTS = {
    'blog': (
        'Сгенерируй профессиональную обложку для статьи в блоге размером 1280x720. '
        'Заголовок статьи: "{title}". '
        'На обложке размести лицо человека с приложенного референсного изображения — '
        'сохрани черты лица, причёску и узнаваемость, но он может реагировать и '
        'изображать эмоцию исходя из темы статьи. '
        'Стиль: сдержанный, белый фон, крупный читаемый текст заголовка на русском языке, '
        'уместные геометрические фигуры или тематические элементы. Без мелких деталей.'
    ),
    'youtube': (
        'Сгенерируй профессиональную обложку (thumbnail) для YouTube видео размером 1280x720. '
        'Заголовок: "{title}". '
        'На обложке размести лицо человека с приложенного референсного изображения — '
        'сохрани черты лица, причёску и узнаваемость, но он может реагировать и '
        'изображать какую-то эмоцию исходя из заголовка и текста. '
        'Стиль: сдержанный, белый фон, крупный читаемый текст заголовка на русском языке, '
        'уместные геометрические фигуры. Без мелких деталей.'
    ),
    'blog_no_face': (
        'Сгенерируй профессиональную обложку для статьи в блоге размером 1280x720. '
        'Заголовок статьи: "{title}". '
        'Стиль: сдержанный, белый фон, крупный читаемый текст заголовка на русском языке в центре полотна (не много), '
        'тематические элементы и иконки по теме статьи, геометрические фигуры. '
        'Без фотографий людей. Минималистичный современный дизайн.'
    ),
}


def generate_image(title, style='blog', use_face=True):
    """Генерирует обложку через OpenRouter API."""
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == 'your_openrouter_api_key_here':
        print('Ошибка: OPENROUTER_API_KEY не задан в .env', file=sys.stderr)
        sys.exit(1)

    prompt_key = style if use_face else f'{style}_no_face'
    if prompt_key not in PROMPTS:
        prompt_key = 'blog_no_face' if not use_face else 'blog'

    prompt_text = PROMPTS[prompt_key].format(title=title)

    # Собираем content
    content = [{'type': 'text', 'text': prompt_text}]
    if use_face:
        content.append({
            'type': 'image_url',
            'image_url': {'url': FACE_REF_URL}
        })

    payload = {
        'model': 'google/gemini-3.1-flash-image-preview',
        'messages': [{'role': 'user', 'content': content}],
        'modalities': ['image', 'text'],
        'max_tokens': 4096,
        'temperature': 0.8,
    }

    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {OPENROUTER_API_KEY}',
            'HTTP-Referer': 'https://veselkov.me',
            'X-Title': 'Blog Cover Generator',
        },
        method='POST',
    )

    print(f'Генерация обложки для: "{title}"...', file=sys.stderr)

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='replace')
        print(f'OpenRouter HTTP {e.code}: {error_body[:500]}', file=sys.stderr)
        sys.exit(1)

    # Извлекаем изображение из ответа
    # OpenRouter/Gemini возвращает изображения в разных полях в зависимости от модели:
    #   - message.content (массив частей с type=image_url)
    #   - message.images (массив с type=image_url)
    #   - message.content (строка с inline base64)
    message = body.get('choices', [{}])[0].get('message', {})
    image_b64 = None
    image_mime = 'image/png'

    def extract_from_parts(parts):
        """Извлекает base64 из массива частей."""
        if not isinstance(parts, list):
            return None, None
        for part in parts:
            if part.get('type') == 'image_url':
                data_url = part.get('image_url', {}).get('url', '')
                if data_url.startswith('data:'):
                    header, b64data = data_url.split(',', 1)
                    mime = header.split(':')[1].split(';')[0]
                    return b64data, mime
        return None, None

    # Проверяем message.images (Gemini через OpenRouter)
    b64, mime = extract_from_parts(message.get('images'))
    if b64:
        image_b64, image_mime = b64, mime

    # Проверяем message.content (массив)
    if not image_b64:
        b64, mime = extract_from_parts(message.get('content'))
        if b64:
            image_b64, image_mime = b64, mime

    # Проверяем message.content (строка с inline base64)
    if not image_b64 and isinstance(message.get('content'), str):
        match = re.search(r'data:(image/[^;]+);base64,([A-Za-z0-9+/=]+)', message['content'])
        if match:
            image_mime = match.group(1)
            image_b64 = match.group(2)

    if not image_b64:
        print('Ошибка: изображение не найдено в ответе OpenRouter', file=sys.stderr)
        # Вывод структуры для диагностики (без огромных данных)
        diag = {k: type(v).__name__ for k, v in message.items()}
        print(f'Структура message: {diag}', file=sys.stderr)
        sys.exit(1)

    print(f'Обложка сгенерирована ({image_mime})', file=sys.stderr)
    return image_b64, image_mime


def save_locally(image_b64, title, output_dir):
    """Сохраняет изображение локально."""
    os.makedirs(output_dir, exist_ok=True)

    # Генерируем имя файла из заголовка
    alias = re.sub(r'[^a-zA-Zа-яА-Я0-9]', '-', title.lower())
    alias = re.sub(r'-+', '-', alias).strip('-')[:60]
    # Транслит для имени файла
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    filename = ''
    for c in alias:
        filename += translit_map.get(c, c)
    filename = re.sub(r'-+', '-', filename).strip('-')
    filename = f'cover-{filename}.png'

    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'wb') as f:
        f.write(base64.b64decode(image_b64))

    print(f'Сохранено: {filepath}', file=sys.stderr)
    return filepath, filename


def upload_to_blog(image_b64, filename):
    """Загружает обложку на veselkov.me через ApiUpload."""
    if not BLOG_API_KEY:
        print('Ошибка: BLOG_API_KEY не задан в .env', file=sys.stderr)
        sys.exit(1)

    payload = {
        'images': [{
            'filename': filename,
            'data': image_b64,
            'content_type': 'image/png',
        }]
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        UPLOAD_URL,
        data=data,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-API-Key': BLOG_API_KEY,
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode('utf-8').strip()
            if raw.startswith('<p>') and raw.endswith('</p>'):
                raw = raw[3:-4]
            result = json.loads(raw)
            if result.get('success') and result.get('uploaded'):
                url = result['uploaded'][0]['url']
                print(f'Загружено: {url}', file=sys.stderr)
                return url
            else:
                print(f'Ошибка загрузки: {json.dumps(result, ensure_ascii=False)}', file=sys.stderr)
                sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f'Upload HTTP {e.code}: {body[:500]}', file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Генерация обложки для статьи блога')
    parser.add_argument('title', help='Заголовок статьи')
    parser.add_argument('--upload', action='store_true', help='Загрузить на veselkov.me')
    parser.add_argument('--style', choices=['blog', 'youtube'], default='blog', help='Стиль обложки')
    parser.add_argument('--output', default='.tmp/covers', help='Директория для локального сохранения')
    parser.add_argument('--no-face', action='store_true', help='Без референсного лица')
    args = parser.parse_args()

    # Генерация
    image_b64, image_mime = generate_image(args.title, args.style, use_face=not args.no_face)

    # Локальное сохранение
    local_path, filename = save_locally(image_b64, args.title, args.output)

    result = {
        'local_path': local_path,
        'filename': filename,
    }

    # Загрузка на сервер
    if args.upload:
        url = upload_to_blog(image_b64, filename)
        result['url'] = url

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

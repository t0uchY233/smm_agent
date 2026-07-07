# SMM Agent

SMM Agent - рабочий контент-пайплайн для перепрофилирования YouTube-видео в публикации для Telegram-канала, WordPress-блога и Яндекс Дзена через RSS блога.

Проект разделяет ручную редакторскую часть и автоматическую публикацию:

- Codex готовит сценарии, DOCX для телесуфлера, тексты для Telegram/блога и обложки.
- n8n загружает видео на YouTube по расписанию, ведет очередь в Google Sheets и публикует готовые материалы.
- Google Sheets хранит состояние публикаций и защищает процесс через review gate.

Codex сам ничего не публикует в Telegram или блог. Он только готовит данные и обновляет строку очереди через n8n webhook.

## Pipeline

```text
0. /video-script
   Тема + дата/время публикации -> сценарий -> DOCX телесуфлера

1. Запись видео
   Пользователь записывает ролик по DOCX-сценарию.

1.5. /render-with-visuals или /render-docx-visuals
   Raw MP4 превращается в финальный MP4 с визуалами.
   Если DOCX уже содержит картинки/таблицы/схемы, используйте /render-docx-visuals.
   В Google Drive загружается rendered-файл, не raw.

2. Google Drive -> n8n
   Rendered MP4 с тем же именем загружается на YouTube как scheduled,
   строка создается или обновляется в Google Sheets.

3. /publish-from-script <youtube_url>
   Codex находит DOCX, готовит Telegram/blog тексты и обложку,
   затем ставит строку в status=review_needed.

4. Approval
   После правок DOCX пользователь пишет "можно публиковать <youtube_url>".
   Codex перечитывает DOCX и ставит status=ready.

5. n8n Publisher
   Каждые 5 минут берет строки status=ready и scheduled_at <= now,
   публикует исходное видео + текст в Telegram, статью в WordPress
   и обновляет статус.
```

## Главные Контракты

Имя DOCX и MP4 содержит дату и время отложенной публикации в MSK:

```text
YYYY-MM-DD-HHMM-Русский заголовок.docx
YYYY-MM-DD-HHMM-Русский заголовок.mp4
```

Пример:

```text
2026-06-25-1400-Топ 5 экономических инструментов.docx
2026-06-25-1400-Топ 5 экономических инструментов.mp4
```

Статусы очереди:

```text
uploaded -> review_needed -> ready -> publishing -> published
                                         \-> failed
```

`review_needed` - черновик подготовлен, но n8n не имеет права его публиковать. `ready` ставится только после явного разрешения пользователя.

## Быстрый Старт

1. Создайте `.env` из шаблона:

```bash
cp .env.example .env
```

2. Заполните ключи и URL в `.env`:

```text
TELEGRAM_BOT_TOKEN
OPENROUTER_API_KEY
ASSEMBLYAI_API_KEY
WORDPRESS_BASE_URL
WORDPRESS_API_BASE_URL
WORDPRESS_USERNAME
WORDPRESS_APP_PASSWORD
N8N_BASE_URL
N8N_WEBHOOK_LOOKUP
N8N_WEBHOOK_UPDATE
SMM_SCHEDULE_SPREADSHEET_ID
```

3. Установите Python-зависимости, если они еще не установлены:

```bash
python3 -m pip install python-docx python-dotenv pillow pytest
```

Для `/render-with-visuals` также нужен системный `ffmpeg`.

4. Импортируйте n8n workflow:

- основной файл: `n8n.json`
- WordPress publisher: `n8n-wordpress-publisher.json`
- инструкция: `n8n-migration.md`

После импорта проверьте credentials для Google Sheets, Google Drive, YouTube, Telegram, OpenRouter и WordPress.

## Команды Codex

### `/video-script`

Создает сценарий ролика и DOCX для телесуфлера в `.tmp/teleprompter/`.

Вход:

```text
/video-script тема ролика, публикация 2026-05-01 14:00
```

Результат:

```text
.tmp/teleprompter/YYYY-MM-DD-HHMM-Русский заголовок.docx
```

### `/publish-from-script`

Готовит Telegram-пост, blog HTML, SEO meta, обложку и обновляет Google Sheets через n8n.

Первый прогон:

```text
/publish-from-script https://youtube.com/watch?v=VIDEO_ID
```

Ставит:

```text
status=review_needed
```

Финальный прогон после правок:

```text
/publish-from-script шеф внес правки, можно публиковать https://youtube.com/watch?v=VIDEO_ID
```

Ставит:

```text
status=ready
```

### `/render-with-visuals`

Локально собирает финальный ролик с автоматическими карточками перед загрузкой в Google Drive.

Вход:

```text
/render-with-visuals ".tmp/raw/YYYY-MM-DD-HHMM-Русский заголовок.mp4"
```

Результат:

```text
.tmp/rendered/YYYY-MM-DD-HHMM-Русский заголовок.mp4
```

В Drive загружайте именно rendered MP4, не raw-видео. Имя файла должно остаться `YYYY-MM-DD-HHMM-Русский заголовок.mp4`, чтобы n8n распарсил дату публикации.

### `/render-docx-visuals`

Локально собирает финальный ролик с изображениями, уже вложенными в DOCX: таблицами, схемами, графиками.

Вход:

```text
/render-docx-visuals .tmp/video/raw.mp4 --docx ".tmp/docx/article.docx"
```

Результат:

```text
.tmp/rendered/<docx-name>.mp4
```

Используйте эту команду вместо `/render-with-visuals`, когда визуалы уже подготовлены внутри Word-документа. Команда держит изображения долго, до следующего визуала, и собирает webcam PiP без моргания между картинками.

## Локальные Инструменты

Прочитать DOCX и извлечь `title`, `body_text`, `scheduled_at`, `alias`:

```bash
python3 tools/read_docx.py ".tmp/teleprompter/2026-06-25-1400-Топ 5 экономических инструментов.docx"
```

Сгенерировать и загрузить обложку в WordPress Media Library:

```bash
python3 tools/generate_cover.py "Заголовок статьи" --upload
```

Извлечь и загрузить изображения из DOCX:

```bash
python3 tools/upload_images.py --from-docx ".tmp/teleprompter/file.docx"
```

Проверить изображения без загрузки:

```bash
python3 tools/upload_images.py --from-docx ".tmp/teleprompter/file.docx" --dry-run
```

Проверить RSS Дзена:

```bash
python3 tools/validate_dzen_rss.py
```

Собрать видео с визуальными карточками:

```bash
python3 tools/render_video_visuals.py ".tmp/raw/2026-06-25-1400-Топ 5 экономических инструментов.mp4" --force
```

Проверить генерацию карточек и timeline без AssemblyAI/FFmpeg-рендера:

```bash
python3 tools/render_video_visuals.py ".tmp/raw/2026-06-25-1400-Топ 5 экономических инструментов.mp4" --dry-run
```

Собрать видео с embedded images из DOCX:

```bash
python3 .codex/skills/render-docx-visuals/scripts/render_docx_visuals.py ".tmp/video/raw.mp4" --docx ".tmp/docx/article.docx" --force
```

Проверить extraction/timeline для embedded images без финального FFmpeg-рендера:

```bash
python3 .codex/skills/render-docx-visuals/scripts/render_docx_visuals.py ".tmp/video/raw.mp4" --docx ".tmp/docx/article.docx" --dry-run
```

## Структура

```text
.codex/
  commands/
    video-script.md
    publish-from-script.md
    render-with-visuals.md
    render-docx-visuals.md
  skills/
    video-script/
    publish-from-script/
    render-with-visuals/
    render-docx-visuals/
    smm-conductor/
.agents/
  skills/
    docx-manipulation/
    wordpress-content/
tools/
  read_docx.py
  generate_cover.py
  render_video_visuals.py
  upload_images.py
  validate_dzen_rss.py
.tmp/
  docx/
  rendered/
  teleprompter/        # создается /video-script при новых сценариях
n8n.json
n8n-wordpress-publisher.json
n8n-migration.md
smm-schedule-template.xlsx
tone-of-voice.md
publish-log.md
RECIPE.md
AGENTS.md
archive/unused-2026-06-10/
```

## Google Sheets

Очередь публикаций находится в таблице:

```text
13CleoQqkhSuWg65fX1bH20ScOgYhqzEx4yg20bNU3ZY
```

Лист:

```text
schedule
```

Ключ строки - `youtube_id`. n8n и Codex делают upsert по этому полю.

Важные поля:

- `scheduled_at` - время публикации в формате `YYYY-MM-DD HH:MM` MSK.
- `tg_text` - текст Telegram-поста; n8n отправляет его вместе с исходным видео.
- `blog_html` - HTML статьи для блога и RSS Дзена.
- `blog_meta` - meta description.
- `blog_alias` - slug из имени DOCX.
- `blog_parent` - категория блога.
- `cover_url` - URL обложки в WordPress Media Library.
- `status` - текущий этап публикации.

Полная схема описана в `AGENTS.md` и в skill `.codex/skills/publish-from-script/SKILL.md`.

## n8n

`n8n.json` содержит объединенный workflow:

- `Drive Trigger` - берет MP4 из Google Drive.
- YouTube upload - ставит scheduled publish.
- Sheets upsert - создает или обновляет строку.
- `Publisher Trigger (5 min)` - публикует готовые строки.
- `Webhook: Lookup (GET)` - поиск строки по `youtube_id`.
- `Webhook: Update (POST)` - upsert строки из Codex.

Webhook lookup:

```bash
curl "$N8N_WEBHOOK_LOOKUP?youtube_id=VIDEO_ID"
```

Webhook update:

```bash
curl -X POST "$N8N_WEBHOOK_UPDATE" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data-binary @.tmp/sheets_payload.json
```

Для больших JSON с кириллицей payload нужно писать во временный файл и отправлять через `--data-binary @file.json`.

## Тесты

Запуск локальных проверок:

```bash
python3 -m pytest tools/test_validate_dzen_rss.py -v
python3 -m pytest tools/test_n8n_blog_footer.py -v
python3 -m pytest tools/test_review_gate_docs.py -v
```

Если меняется схема review gate, n8n footer или RSS-формат, соответствующие тесты нужно обновлять вместе с изменением.

## Важные Файлы

- `AGENTS.md` - основная проектная инструкция для агентов.
- `tone-of-voice.md` - стиль Сергея Веселкова и правила контента.
- `RECIPE.md` - SOP и ретроспективный план сборки проекта.
- `n8n-migration.md` - импорт и проверка n8n workflow.
- `.env.example` - список переменных окружения без секретов.
- `publish-log.md` - лог отправок в очередь.

## Правила Эксплуатации

- Не коммитить `.env`.
- Не публиковать напрямую в Telegram или блог из Codex.
- Не ставить `status=ready` без явной фразы approval.
- Не брать контент из YouTube-транскрипта: источник текста - DOCX.
- Не менять порядок колонок Google Sheets без синхронного изменения n8n.
- Для Дзена использовать только разрешенные HTML-теги и plain YouTube link без iframe.
- После `/render-with-visuals` в Google Drive загружать rendered MP4, не raw.

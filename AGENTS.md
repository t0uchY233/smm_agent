# AGENTS.md

This file provides guidance to Codex (codex) when working with code in this repository.

# SMM Agent — Unified Content Pipeline

Перепрофилирование YouTube-видео в контент для Telegram-канала, WordPress-блога и Яндекс Дзен (через RSS блога) с **отложенной публикацией по расписанию**.

## Pipeline: полный цикл

```
[Шаг 0] /video-script → Тема + дата/время публикации → Сценарий → Телесуфлёр-DOCX
        Имя DOCX: YYYY-MM-DD-HHMM-Русский заголовок.docx (имя = время публикации MSK)
        Все таблицы/схемы/дашборды/KPI-блоки сразу генерируются через встроенный GPT Image 2 (`gpt-image-2`)
        и вставляются в DOCX как embedded images; текстовых таблиц в DOCX быть не должно
        После создания DOCX Codex всегда пишет мини-гайд "что делать дальше" по SOP

[Шаг 1] Запись видео (пользователь)

[Шаг 1.5] /render-with-visuals raw.mp4 или /render-docx-visuals raw.mp4 --docx file.docx:
        - найти DOCX по имени raw-видео
        - default: DOCX уже содержит embedded images, использовать /render-docx-visuals
        - если embedded images нет — это допустимо только когда сценарий реально не требует визуалов; иначе вернуться к /video-script и сгенерировать visual inserts
        - распознать речь через AssemblyAI
        - наложить визуалы через FFmpeg
        - сохранить .tmp/rendered/YYYY-MM-DD-HHMM-Русский заголовок.mp4

[Шаг 2] Google Drive (имя YYYY-MM-DD-HHMM-Русский заголовок.mp4, rendered MP4, не raw) → n8n:
        - upload на YouTube как scheduled (publishAt = время из имени)
        - AI-thumbnail → загрузка
        - upsert строки в Sheets (status=uploaded, scheduled_at, youtube_url)
        - Telegram уведомление в служебный канал

[Шаг 3] /publish-from-script <youtube_url>:
        - lookup в Sheets по youtube_id → достать scheduled_at и найти DOCX
        - read_docx.py → title + body_text
        - DOCX является единым источником для WordPress и Яндекс Дзен: в тексте не должно быть служебных video-only маркеров
        - generate_cover.py → cover_url
        - адаптация текстов для Telegram + блога
        - превью пользователю
        - POST в n8n webhook → строка в Sheets обновляется до status=review_needed
        - после правок шефа: повторный запуск с фразой «можно публиковать» перечитывает DOCX и ставит status=ready

[Шаг 4] n8n Publisher Trigger (каждые 5 мин):
        - читает Sheets, фильтрует status=ready и scheduled_at <= now
        - публикует в Telegram канал и WordPress-блог
        - обновляет статус → published, шлёт уведомление в служебный канал
```

**n8n** (24/7 сервер): загружает видео на YouTube, готовит thumbnail, потом каждые 5 минут забирает готовые посты из Sheets и публикует в Telegram + блог.

**Codex** (ручные сессии): получает YouTube URL, читает DOCX-сценарий, готовит платформенные тексты + обложку, кладёт строку в Sheets через webhook. **Сам ничего не публикует.**

## Скиллы

**`/video-script`** (Шаг 0) — генерация сценария для YouTube. Тема + дата/время публикации → диалог → сценарий → телесуфлёр-DOCX. Все таблицы, схемы, дашборды, KPI-блоки, сравнения и матрицы с самого начала генерируются через встроенный GPT Image 2 (`gpt-image-2`) и вставляются в DOCX как embedded images; текстовые/Markdown-таблицы запрещены. Для visual inserts не нужен и не проверяется `OPENAI_API_KEY`: использовать встроенную image-generation capability Codex. В теле DOCX запрещены служебные подписи вроде `ВИЗУАЛ НА ЭКРАН`, потому что этот же DOCX без ручной чистки идёт в WordPress и Яндекс Дзен через `/publish-from-script`. Имя файла = `YYYY-MM-DD-HHMM-Русский заголовок.docx` (время публикации зашито в имя; заголовок сохранять на русском, без транслита). Express mode: тема + детали + дата/время в одном сообщении. После создания DOCX обязательно вывести мини-гайд по следующим шагам SOP.

**`/render-with-visuals`** (Шаг 1.5) — локальный монтаж visual layer. Raw MP4 + DOCX → карточки/схемы → AssemblyAI transcript → timeline → FFmpeg render → `.tmp/rendered/YYYY-MM-DD-HHMM-Русский заголовок.mp4`. В Google Drive загружать rendered MP4, не raw.

**`/render-docx-visuals`** (вариант Шага 1.5) — локальный монтаж, когда DOCX уже содержит готовые изображения/таблицы/схемы. Raw MP4 + DOCX embedded images → extraction → AssemblyAI transcript → long visual timeline → FFmpeg render без моргания webcam PiP → `.tmp/rendered/<docx-name>.mp4`. Использовать вместо генерации карточек, если визуалы уже вложены в Word-документ.

**`/publish-from-script`** (Шаг 3) — подготовка постов из DOCX-сценария и постановка в очередь Sheets. YouTube URL → lookup в Sheets → DOCX → тексты + обложка → POST в n8n webhook. Первый прогон ставит `status=review_needed`; после фразы пользователя «можно публиковать» скилл заново читает исправленный DOCX и ставит `status=ready`. Express mode: вставить URL → автоматический поиск DOCX и подготовка контента.

## Конфигурация

**Файл `.env`** содержит ключи:
- `TELEGRAM_BOT_TOKEN` — от @BotFather (используется как контроль длины caption)
- `WORDPRESS_BASE_URL`, `WORDPRESS_API_BASE_URL`, `WORDPRESS_USERNAME`, `WORDPRESS_APP_PASSWORD` — для WordPress REST API
- `OPENROUTER_API_KEY` — для генерации обложек
- `OPENAI_API_KEY`, `OPENAI_IMAGE_MODEL=gpt-image-2` — не требуются для `/video-script`; визуалы сценария генерируются встроенным GPT Image 2 Codex. Эти переменные не проверять и не использовать как блокер для embedded visual images.
- `ASSEMBLYAI_API_KEY`, `ASSEMBLYAI_LANGUAGE_CODE` — для распознавания речи и синхронизации визуальных карточек в `/render-with-visuals`
- `N8N_BASE_URL`, `N8N_WEBHOOK_LOOKUP`, `N8N_WEBHOOK_UPDATE` — endpoint'ы n8n
- `SMM_SCHEDULE_SPREADSHEET_ID` — ID Google Sheets очереди

**`tone-of-voice.md`** — системная инструкция по стилю контента (цифровой двойник Сергея Веселкова, инженерно-прагматичный тон, аудитория 40+).

**`publish-log.md`** — лог отправок в очередь.

**`n8n.json`** — n8n workflow для импорта (Google Drive → YouTube scheduled → Sheets upsert → Telegram уведомление).

**`n8n-wordpress-publisher.json`** — актуальный n8n Publisher workflow (каждые 5 мин читает Sheets и публикует в Telegram + WordPress-блог).

## Google Sheets очередь

**ID:** `13CleoQqkhSuWg65fX1bH20ScOgYhqzEx4yg20bNU3ZY`
**Лист:** `schedule`

**Колонки** (порядок важен — n8n матчит по позиции):

| Колонка | Кто пишет | Когда |
|---|---|---|
| `youtube_id` | n8n upload | после YouTube upload (primary key для upsert) |
| `youtube_url` | n8n upload | после YouTube upload |
| `drive_file_id` | n8n upload | после download |
| `title` | n8n upload | парсинг имени видео |
| `scheduled_at` | n8n upload | парсинг имени видео (формат `YYYY-MM-DD HH:MM` MSK) |
| `tg_text` | /publish-from-script | подготовка постов |
| `blog_html` | /publish-from-script | подготовка постов |
| `blog_meta` | /publish-from-script | подготовка постов |
| `blog_alias` | /publish-from-script | подготовка постов |
| `blog_parent` | /publish-from-script | подготовка постов |
| `cover_url` | /publish-from-script | URL обложки в WordPress Media Library |
| `cover_local_path` | /publish-from-script | генерация обложки |
| `status` | оба | uploaded → review_needed → ready → publishing → published / failed |
| `published_at` | n8n publisher | после успешной публикации |
| `tg_msg_id` | n8n publisher | после Telegram send |
| `blog_url` | n8n publisher | после blog publish |
| `error` | n8n publisher | при failure |

**Жизненный цикл строки:**
1. n8n создаёт строку (status=uploaded) после загрузки видео на YouTube
2. /publish-from-script дополняет контентом (status=review_needed)
3. Шеф правит тот же DOCX-файл на месте
4. После фразы «шеф внёс правки, можно публиковать <youtube_url>» /publish-from-script перечитывает DOCX и ставит status=ready
5. n8n Publisher Trigger в назначенное время (`scheduled_at <= now`) ставит status=publishing → публикует → status=published
6. На failure → status=failed, поле error заполнено, alert в служебный канал

## n8n endpoints

- `N8N_BASE_URL=https://bigetn8n.casacam.net`
- **Webhook Lookup** (GET): `/webhook/e5bdfd41-4fad-4442-b707-1d416bd5c3b2?youtube_id=<id>` → возвращает строку Sheets как JSON
- **Webhook Update** (POST): `/webhook/905e8882-caab-4e40-8f42-c6f63524f3e8` → upsert в Sheets по `youtube_id`
- Auth: нет (открытые webhooks)

## Категории блога

| Категория | parent ID | Ключевые слова для auto-detect |
|-----------|-----------|-------------------------------|
| Бизнес | 34 | бизнес, предпринимательство, финансы, деньги |
| Маркетинг | 29 | маркетинг, продажи, реклама, клиенты |
| Управление | 32 | управление, ТОС, ограничения, менеджмент, операции |

## Технические особенности

- **Windows / Кириллица:** при вызове Python через Bash всегда добавлять `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')` во избежание ошибок cp1251.
- **JSON payload для webhook:** при POST в n8n webhook с большим JSON и кириллицей всегда писать payload во временный файл (`.tmp/sheets_payload.json`) и отправлять через `curl --data-binary @file.json` — иначе проблемы с экранированием в shell.
- **Telegram video caption:** n8n скачивает исходный `.mp4` из Google Drive по `drive_file_id` и отправляет его через `sendVideo`. Caption лимит 1024 символа; при превышении n8n ставит в caption `blog_meta`, а полный текст отправляет отдельным `sendMessage` (до 4096).
- **Blog publish:** n8n публикует статью в WordPress. Старый `veselkov.me` API больше не используется.
- **Review gate:** n8n публикует только `status=ready`. `review_needed` означает, что контент подготовлен, но ждёт правок шефа и явного разрешения публикации.
- **Blog class_key:** `msProduct` (не `modDocument`), иначе статья не появится на главной.
- **RSS / Дзен:** после публикации WordPress-статья автоматически попадает в RSS → Яндекс Дзен. Контент должен использовать только разрешённые Дзеном HTML-теги, YouTube как plain link, ≥300 знаков текста.
- **Telegram chat_id канала:** `-1001972632255` (публикации).
- **n8n служебный канал:** `-1003932006777` (уведомления о загрузке и публикации, alerts).
- **Имя DOCX:** `/video-script` сохраняет в `.tmp/teleprompter/YYYY-MM-DD-HHMM-Русский заголовок.docx`. Время в имени = время отложенной публикации MSK. Заголовок после времени всегда на русском языке, без транслита; пробелы разрешены. Запрещены только символы Windows-пути: `< > : " / \ | ? *`. По имени `/publish-from-script` находит файл при lookup в Sheets.
- **Имя видеофайла в Drive:** `YYYY-MM-DD-HHMM-Русский заголовок.mp4` (тот же формат что DOCX, без расширения совпадает). n8n парсит дату/время из имени для `publishAt` YouTube и `scheduled_at` в Sheets.
- **DOCX visual source:** `/video-script` не должен оставлять таблицы, схемы, дашборды, KPI-блоки, сравнения или матрицы текстом. Каждый такой элемент сначала генерируется через встроенный GPT Image 2 (`gpt-image-2`) через image-generation capability Codex, сохраняется рядом с DOCX в `.tmp/teleprompter/<docx-base>_assets/` и вставляется в DOCX как embedded image. Не проверять `OPENAI_API_KEY` и не заменять GPT Image 2 локальными Pillow/HTML/SVG-слайдами только из-за отсутствия ключа. Не добавлять в тело DOCX служебные video-only маркеры или подписи: `ВИЗУАЛ НА ЭКРАН`, `СХЕМА НА ЭКРАН`, `КАРТИНКА НА ЭКРАН` и аналоги. Перед завершением проверять, что в DOCX есть `word/media/*` для каждого embedded visual image и что `read_docx.py` не возвращает служебных маркеров.
- **DOCX как источник публикаций:** тот же DOCX без ручных изменений используется в `/publish-from-script` для WordPress-блога и Яндекс Дзен через RSS. Любой текстовый маркер, добавленный для монтажа, попадёт в статью. Визуалы должны быть embedded images между обычными абзацами, а не текстовыми инструкциями для монтажёра.
- **Visual layer:** после записи raw-видео по умолчанию запускать `/render-docx-visuals`, потому что DOCX должен уже содержать embedded images. `/render-with-visuals` использовать только как fallback для старых DOCX или сценариев без готовых visual inserts. В Drive загружать только `.tmp/rendered/YYYY-MM-DD-HHMM-Русский заголовок.mp4`, не raw, иначе YouTube получит ролик без карточек/таблиц. Для DOCX-visuals default: картинки висят до следующего визуала, webcam PiP не должен моргать между картинками.
- **После DOCX — мини-гайд SOP:** в финальном ответе после создания DOCX всегда писать короткий блок "Дальше по SOP": (1) записать raw-видео по DOCX; (2) запустить `/render-docx-visuals raw.mp4 --docx <docx_path>`; (3) получить `.tmp/rendered/YYYY-MM-DD-HHMM-Русский заголовок.mp4`; (4) загрузить rendered MP4 в Google Drive с тем же base-name; (5) после YouTube upload взять URL из n8n-уведомления; (6) запустить `/publish-from-script <youtube_url>`. Не добавлять отдельный пункт про правки шефа: все дальнейшие действия по SOP выполняет Шеф.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# SMM Agent — Unified Content Pipeline

Перепрофилирование YouTube-видео в контент для Telegram-канала, WordPress-блога и Яндекс Дзен (через RSS блога) с **отложенной публикацией по расписанию**.

## Pipeline: полный цикл

```
[Шаг 0] /video-script → Тема + дата/время публикации → Сценарий → Телесуфлёр-DOCX
        Имя DOCX: YYYY-MM-DD-HHMM-alias.docx (имя = время публикации MSK)

[Шаг 1] Запись видео (пользователь)

[Шаг 2] Google Drive (имя YYYY-MM-DD-HHMM-alias.mp4) → n8n:
        - upload на YouTube как scheduled (publishAt = время из имени)
        - AI-thumbnail → загрузка
        - upsert строки в Sheets (status=uploaded, scheduled_at, youtube_url)
        - Telegram уведомление в служебный канал

[Шаг 3] /publish-from-script <youtube_url>:
        - lookup в Sheets по youtube_id → достать scheduled_at и найти DOCX
        - read_docx.py → title + body_text
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

**Claude Code** (ручные сессии): получает YouTube URL, читает DOCX-сценарий, готовит платформенные тексты + обложку, кладёт строку в Sheets через webhook. **Сам ничего не публикует.**

## Скиллы

**`/video-script`** (Шаг 0) — генерация сценария для YouTube. Тема + дата/время публикации → диалог → сценарий → телесуфлёр-DOCX. Имя файла = `YYYY-MM-DD-HHMM-alias.docx` (время публикации зашито в имя). Express mode: тема + детали + дата/время в одном сообщении.

**`/publish-from-script`** (Шаг 3) — подготовка постов из DOCX-сценария и постановка в очередь Sheets. YouTube URL → lookup в Sheets → DOCX → тексты + обложка → POST в n8n webhook. Первый прогон ставит `status=review_needed`; после фразы пользователя «можно публиковать» скилл заново читает исправленный DOCX и ставит `status=ready`. Express mode: вставить URL → автоматический поиск DOCX и подготовка контента.

## Конфигурация

**Файл `.env`** содержит ключи:
- `TELEGRAM_BOT_TOKEN` — от @BotFather (используется как контроль длины caption)
- `WORDPRESS_BASE_URL`, `WORDPRESS_API_BASE_URL`, `WORDPRESS_USERNAME`, `WORDPRESS_APP_PASSWORD` — для WordPress REST API
- `OPENROUTER_API_KEY` — для генерации обложек
- `N8N_BASE_URL`, `N8N_WEBHOOK_LOOKUP`, `N8N_WEBHOOK_UPDATE` — endpoint'ы n8n
- `SMM_SCHEDULE_SPREADSHEET_ID` — ID Google Sheets очереди

**`tone-of-voice.md`** — системная инструкция по стилю контента (цифровой двойник Сергея Веселкова, инженерно-прагматичный тон, аудитория 40+).

**`publish-log.md`** — лог отправок в очередь.

**`n8n.json`** — n8n workflow для импорта (Google Drive → YouTube scheduled → Sheets upsert → Telegram уведомление).

**`n8n_actual.json`** — n8n Publisher workflow (каждые 5 мин читает Sheets и публикует в Telegram + блог).

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
- **Имя DOCX:** `/video-script` сохраняет в `.tmp/teleprompter/YYYY-MM-DD-HHMM-alias.docx`. Время в имени = время отложенной публикации MSK. По нему `/publish-from-script` находит файл при lookup в Sheets.
- **Имя видеофайла в Drive:** `YYYY-MM-DD-HHMM-alias.mp4` (тот же формат что DOCX, без расширения совпадает). n8n парсит дату/время из имени для `publishAt` YouTube и `scheduled_at` в Sheets.

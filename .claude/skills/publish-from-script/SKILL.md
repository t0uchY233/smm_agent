---
name: publish-from-script
description: Use when a recorded video is uploaded to YouTube via n8n and a DOCX script exists in .tmp/teleprompter/ — reads DOCX content (no YouTube transcript), generates Telegram and blog posts plus cover image, queues them in Google Sheets via n8n webhook for scheduled publishing. Requires YouTube URL.
---

# Publish from Script

## Overview

Шаг 3 в контент-пайплайне. Источник контента — DOCX-сценарий из `/video-script` (НЕ YouTube транскрипт). Скилл сам ничего не публикует — он готовит тексты + обложку и кладёт строку в Google Sheets через n8n webhook со `status=ready`. n8n Publisher Trigger каждые 5 минут забирает готовые строки и публикует в назначенное время.

**Pipeline context:**
1. **/video-script** (раньше): создал DOCX `.tmp/teleprompter/YYYY-MM-DD-HHMM-alias.docx` (имя = время публикации MSK)
2. **n8n** (автоматически): загрузил видео на YouTube → прислал URL в служебный канал
3. **Этот скилл:** YouTube URL + DOCX → тексты + обложка → POST в n8n webhook (Sheets row, status=ready)
4. **n8n Publisher** (каждые 5 мин): забирает ready+due → публикует в Telegram канал и блог

**Express mode:** пользователь даёт YouTube URL первым сообщением — найти соответствующий DOCX в `.tmp/teleprompter/` (через lookup в Sheets или по самому свежему файлу) и идти к Step 3.

## Prerequisites

В `.env` (в корне проекта `F:\program\claude_code_project\smm_agent\.env`):
- `TELEGRAM_BOT_TOKEN` — для проверки длины tg_text (лимит 1024 для caption)
- `BLOG_API_KEY` — не используется напрямую (его потребляет n8n)
- `N8N_BASE_URL`, `N8N_WEBHOOK_LOOKUP`, `N8N_WEBHOOK_UPDATE` — endpoint'ы n8n
- `OPENROUTER_API_KEY` — для генерации обложки

`tone-of-voice.md` в корне проекта — стиль Веселкова.

**НИКОГДА не просить ключи в чате — читать только из .env.**

## Workflow

### Step 1: Input

1. **Прочитать `.env`** через Read tool (`F:\program\claude_code_project\smm_agent\.env`).
2. **Прочитать `tone-of-voice.md`** через Read tool.
3. **Получить YouTube URL** — обязательный аргумент. Если не дан — спросить через AskUserQuestion.
4. **Извлечь youtube_id** регексом из URL: `(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})`. Если не извлекается — стоп, попросить корректный URL.

### Step 2: Найти DOCX

Стратегия (по приоритету):

**А. Lookup в Sheets через n8n webhook:**
```bash
curl -s "$(grep N8N_WEBHOOK_LOOKUP .env | cut -d= -f2)?youtube_id=YOUTUBE_ID_HERE"
```
Ожидаемый ответ — JSON со строкой Sheets (если найдена) или `{}`/пусто (если нет).

- Если найдена строка со `status=published` — стоп, сообщить пользователю «Уже опубликовано».
- Если найдена со `status=ready` — предупредить и спросить: «Заменить контент? [Да/Нет]».
- Если найдена со `status=uploaded` и есть `scheduled_at` — искать DOCX по этой дате/времени:
  - Преобразовать `scheduled_at` (`YYYY-MM-DD HH:MM`) в префикс имени файла: `YYYY-MM-DD-HHMM`.
  - Glob: `.tmp/teleprompter/YYYY-MM-DD-HHMM-*.docx`. Если 1 файл — взять. Если несколько — самый свежий по mtime. Если ноль — перейти к стратегии Б.

**Б. Если lookup пустой или DOCX не найден:**
- Показать через `ls .tmp/teleprompter/` список файлов (отсортированных по mtime, новые сверху).
- Через AskUserQuestion попросить выбрать нужный файл (или Other для ввода имени).

### Step 3: Прочитать DOCX

```bash
python tools/read_docx.py "<path-to-docx>"
```

Ожидаемый JSON:
```json
{
  "title": "...",
  "body_text": "...",
  "scheduled_at": "2026-05-01 14:00",
  "alias": "burovye-krs",
  "source_path": "<abs-path>"
}
```

- Если `scheduled_at: null` (старый формат имени без времени) — спросить пользователя дату+время через AskUserQuestion (формат `YYYY-MM-DD HH:MM`, не в прошлом).
- Если строка из Sheets уже содержит `scheduled_at` (стратегия А выше) — оно приоритетнее DOCX.

### Step 4: Auto-detect category

Анализировать `body_text` по ключевым словам:
- бизнес, предпринимательство, финансы, деньги → **Бизнес** (parent=34)
- маркетинг, продажи, реклама, клиенты → **Маркетинг** (parent=29)
- управление, ТОС, ограничения, менеджмент, операции, бутылочное горлышко, КРС, бурение → **Управление** (parent=32)

Показать пользователю определённую категорию через AskUserQuestion с возможностью переопределить.

### Step 5: Сгенерировать обложку

```bash
python tools/generate_cover.py "ARTICLE_TITLE" --upload
```

Возвращает JSON: `{url, local_path, filename}`. Сохранить `cover_url` (remote) и `cover_local_path` (локальный путь).

Если генерация упала — стоп, сообщить пользователю. Без обложки не продолжаем (n8n требует cover_url).

### Step 6: Адаптировать контент

Используя `title`, `body_text` из DOCX и `tone-of-voice.md`, сгенерировать:

**Telegram пост (`tg_text`):**
- Цепляющий, с ключевыми тезисами из сценария
- В конце — ссылка на YouTube видео: `📺 <a href="YOUTUBE_URL">Смотреть на YouTube</a>`
- Лимит 1024 символа (caption sendPhoto). Если больше — n8n сам отправит фото отдельно + текст отдельным sendMessage (до 4096).
- Только разрешённые HTML-теги: `<b>`, `<i>`, `<a>`, `<code>`, `<pre>`

**Blog статья (`blog_html`) — Дзен-совместимая:**
- Полноценная статья с `<h2>` подзаголовками
- Вступление, 3-5 ключевых пунктов, выводы
- YouTube видео как plain link (НЕ iframe): `https://www.youtube.com/watch?v=VIDEO_ID` (Дзен сам сделает виджет)
- **Разрешённые теги:** p, a, b, i, u, s, h1-h4, blockquote, ul/li, ol/li, figure, img, br
- **Запрещены:** iframe, div, span, table, script, style, form, section, article
- Минимум 300 символов чистого текста (без тегов)

**SEO meta (`blog_meta`):** 150-160 символов, используется как описание в RSS-карточке Дзена.

**Blog alias (`blog_alias`):** взять из имени DOCX (`alias` поле из `read_docx.py`). Это уже транслит lowercase с дефисами.

**Blog parent (`blog_parent`):** ID категории из Step 4.

### Step 7: Превью пользователю

Показать через AskUserQuestion компактно:

```
Title: {title}
Категория: {Бизнес/Маркетинг/Управление}
Публикация: {scheduled_at} MSK

Telegram ({len} chars): {first 200 chars}...
Blog ({len} chars): {first 200 chars}... (ещё N абзацев)
Обложка: {cover_url}

Поставить в очередь? [OK / Изменить / Отмена]
```

Если «Изменить» — спросить что и поправить нужный блок.
Если «Отмена» — стоп.
Если «OK» — Step 8.

### Step 8: Upsert в Sheets через n8n webhook

```bash
curl -s -X POST "$(grep N8N_WEBHOOK_UPDATE .env | cut -d= -f2)" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data-binary @.tmp/sheets_payload.json
```

Где `.tmp/sheets_payload.json` содержит:
```json
{
  "youtube_id": "...",
  "youtube_url": "https://youtube.com/watch?v=...",
  "title": "...",
  "scheduled_at": "2026-05-01 14:00",
  "tg_text": "...",
  "blog_html": "...",
  "blog_meta": "...",
  "blog_alias": "...",
  "blog_parent": 32,
  "cover_url": "https://veselkov.me/...",
  "cover_local_path": ".tmp/covers/...",
  "status": "ready"
}
```

n8n webhook делает upsert по `youtube_id` — повторный вызов обновит ту же строку, дубль не создастся.

Проверить ответ. Если HTTP 200 и body содержит OK — успех. Иначе — показать пользователю ответ и спросить что делать.

**Внимание для Bash под Windows:** при больших JSON с кириллицей всегда писать payload во временный файл (через Write tool в `.tmp/sheets_payload.json`) и передавать через `--data-binary @file.json`, чтобы избежать экранирования кавычек и проблем с кириллицей в shell.

### Step 9: Подтверждение

Сообщить пользователю:
```
✅ В очереди.
🕐 n8n опубликует {scheduled_at} MSK
📺 YouTube: {youtube_url}
📝 Категория: {category}
📊 Sheets row updated: status=ready
```

Записать в `publish-log.md` (в корне проекта) строку:
```
| {scheduled_at} | {youtube_url} | scheduled | - | - |
```

После публикации статуса «published» n8n обновит Sheets и пришлёт уведомление в служебный канал `-1003932006777`. Этот скилл больше ничего не делает.

## API Quick Reference

| Tool/Endpoint | Method | Purpose |
|---------------|--------|---------|
| `tools/read_docx.py` (Python) | — | Извлечь title/body_text из DOCX + scheduled_at из имени |
| `tools/generate_cover.py` (Python) | — | Сгенерировать AI-обложку через OpenRouter, загрузить на veselkov.me |
| `N8N_WEBHOOK_LOOKUP` (n8n) | GET | Lookup строки Sheets по `youtube_id` |
| `N8N_WEBHOOK_UPDATE` (n8n) | POST | Upsert строки Sheets (matchingColumns: youtube_id) |

## Google Sheets schema

Лист `schedule` в таблице `13CleoQqkhSuWg65fX1bH20ScOgYhqzEx4yg20bNU3ZY`. Колонки:

| Колонка | Кто пишет | Когда |
|---|---|---|
| `youtube_id` | n8n upload | после YouTube upload |
| `youtube_url` | n8n upload | после YouTube upload |
| `drive_file_id` | n8n upload | после download |
| `title` | n8n upload | парсинг имени видео |
| `scheduled_at` | n8n upload | парсинг имени видео |
| `tg_text` | этот скилл | step 8 |
| `blog_html` | этот скилл | step 8 |
| `blog_meta` | этот скилл | step 8 |
| `blog_alias` | этот скилл | step 8 |
| `blog_parent` | этот скилл | step 8 |
| `cover_url` | этот скилл | step 8 |
| `cover_local_path` | этот скилл | step 8 |
| `status` | оба | uploaded → ready → publishing → published / failed |
| `published_at` | n8n publisher | после успешной публикации |
| `tg_msg_id` | n8n publisher | после Telegram send |
| `blog_url` | n8n publisher | после blog publish |
| `error` | n8n publisher | при failure |

## Error Handling

| Error | Action |
|-------|--------|
| YouTube URL не парсится | Попросить корректный URL формата https://youtube.com/watch?v=ID |
| DOCX не найден ни одним способом | Список через ls + AskUserQuestion с просьбой указать вручную |
| `read_docx.py` упал | Показать stderr пользователю, не продолжать |
| Cover generation failed | Стоп, сообщить пользователю — без обложки публикация не идёт |
| n8n webhook вернул не-200 | Показать ответ, спросить retry/cancel |
| .env отсутствует | Стоп, сообщить пользователю заполнить .env |
| Lookup в Sheets — статус published | Стоп, не пересоздавать публикацию |
| Lookup в Sheets — статус ready | Спросить «Заменить?» — если да, перезаписать через тот же webhook |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Брать контент из YouTube транскрипта | НЕ. Источник всегда DOCX из `.tmp/teleprompter/` |
| Публиковать напрямую в Telegram/blog API | НЕ. Только через POST в n8n webhook со `status=ready`. Публикует n8n. |
| Sharing API keys in chat | NEVER. Always read from .env file |
| Shell state assumptions | Каждый Bash вызов независим — перечитывать .env при необходимости |
| Создавать DOCX с произвольным именем | Имя строго `YYYY-MM-DD-HHMM-alias.docx` — иначе scheduled_at не извлечётся |
| Игнорировать ответ webhook | Всегда проверять HTTP код и body — если не OK, не репортить пользователю успех |

---
name: publish-from-script
description: Use when a recorded video is uploaded to YouTube via n8n and a DOCX script exists in .tmp/teleprompter/ — reads DOCX content (no YouTube transcript), generates Telegram and blog posts plus cover image, queues them in Google Sheets via n8n webhook for scheduled publishing. Requires YouTube URL.
---

# Publish from Script

## Overview

Шаг 3 в контент-пайплайне. Источник контента — DOCX-сценарий из `/video-script` (НЕ YouTube транскрипт). Скилл сам ничего не публикует — он готовит тексты + обложку и кладёт строку в Google Sheets через n8n webhook. По умолчанию строка получает `status=review_needed`, чтобы n8n не опубликовал черновик до правок шефа. `status=ready` ставится только после явного разрешения пользователя.

**Pipeline context:**
1. **/video-script** (раньше): создал DOCX `.tmp/teleprompter/YYYY-MM-DD-HHMM-Русский заголовок.docx` (имя = время публикации MSK)
2. **n8n** (автоматически): загрузил видео на YouTube → прислал URL в служебный канал
3. **Этот скилл:** YouTube URL + DOCX → тексты + обложка → POST в n8n webhook (Sheets row, status=review_needed)
4. **Шеф:** правит тот же DOCX-файл на месте
5. **Этот скилл повторно:** фраза подтверждения + YouTube URL → заново читает исправленный DOCX → preview → POST со `status=ready`
6. **n8n Publisher** (каждые 5 мин): забирает ready+due → публикует в Telegram канал и блог

**Express mode:** пользователь даёт YouTube URL первым сообщением — найти соответствующий DOCX в `.tmp/teleprompter/` (через lookup в Sheets или по самому свежему файлу) и идти к Step 3.

**Approval mode:** если вместе с YouTube URL пользователь явно пишет, что правки внесены и можно публиковать, перечитать тот же DOCX с диска и после финального preview поставить `status=ready`.

Фразы, которые включают approval mode:
- `можно публиковать`
- `шеф внес правки`
- `шеф внёс правки`
- `правки внесены`
- `approved`
- `финальная версия`

Без явного разрешения не ставить `status=ready`.

## Prerequisites

В `.env` в корне проекта:
- `TELEGRAM_BOT_TOKEN` — для проверки длины tg_text (лимит 1024 для caption)
- `WORDPRESS_BASE_URL`, `WORDPRESS_API_BASE_URL`, `WORDPRESS_USERNAME`, `WORDPRESS_APP_PASSWORD` — для загрузки обложек и DOCX-изображений в WordPress
- `N8N_BASE_URL`, `N8N_WEBHOOK_LOOKUP`, `N8N_WEBHOOK_UPDATE` — endpoint'ы n8n
- `OPENROUTER_API_KEY` — для генерации обложки

`tone-of-voice.md` в корне проекта — стиль Веселкова.

**НИКОГДА не просить ключи в чате — читать только из .env.**

## Workflow

### Step 1: Input

1. **Прочитать `.env`** из корня проекта.
2. **Прочитать `tone-of-voice.md`** из корня проекта.
3. **Получить YouTube URL** — обязательный аргумент. Если не дан — коротко спросить URL у пользователя.
4. **Определить режим:** если во входе есть фраза из списка approval mode — `target_status=ready`, иначе `target_status=review_needed`.
5. **Извлечь youtube_id** регексом из URL: `(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})`. Если не извлекается — стоп, попросить корректный URL.

### Step 2: Найти DOCX

Стратегия (по приоритету):

**А. Lookup в Sheets через n8n webhook:**
```bash
curl -s "$(grep N8N_WEBHOOK_LOOKUP .env | cut -d= -f2)?youtube_id=YOUTUBE_ID_HERE"
```
Ожидаемый ответ — JSON со строкой Sheets (если найдена) или `{}`/пусто (если нет).

- Если найдена строка со `status=published` — стоп, сообщить пользователю «Уже опубликовано».
- Если найдена со `status=ready` — предупредить и спросить: «Публикация уже разрешена. Перечитать DOCX и заменить контент? [Да/Нет]».
- Если найдена со `status=review_needed`:
  - В обычном режиме: перечитать DOCX и обновить черновик, оставив `status=review_needed`.
  - В approval mode: перечитать DOCX, показать финальный preview и при OK поставить `status=ready`.
- Если найдена со `status=uploaded` и есть `scheduled_at` — искать DOCX по этой дате/времени:
  - Преобразовать `scheduled_at` (`YYYY-MM-DD HH:MM`) в префикс имени файла: `YYYY-MM-DD-HHMM`.
  - Glob: `.tmp/teleprompter/YYYY-MM-DD-HHMM-*.docx`. Если 1 файл — взять. Если несколько — самый свежий по mtime. Если ноль — перейти к стратегии Б.

**Б. Если lookup пустой или DOCX не найден:**
- Показать через `ls .tmp/teleprompter/` список файлов (отсортированных по mtime, новые сверху).
- Попросить пользователя указать нужный файл вручную.

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

- Если `scheduled_at: null` (старый формат имени без времени) — спросить пользователя дату+время (формат `YYYY-MM-DD HH:MM`, не в прошлом).
- Если строка из Sheets уже содержит `scheduled_at` (стратегия А выше) — оно приоритетнее DOCX.
- Проверить, есть ли в DOCX изображения:
  ```bash
  python tools/upload_images.py --from-docx "<path-to-docx>" --dry-run
  ```
  Если изображения есть, перед финальным payload загрузить их в WordPress через `python tools/upload_images.py --from-docx "<path-to-docx>"` и вставить в `blog_html` как `<figure><img src="IMAGE_URL" alt=""></figure>`. Сохранять порядок изображений из DOCX; если позиция в тексте неоднозначна — спросить пользователя перед approval.

### Step 4: Auto-detect category

Анализировать `body_text` по ключевым словам:
- бизнес, предпринимательство, финансы, деньги → **Бизнес** (parent=34)
- маркетинг, продажи, реклама, клиенты → **Маркетинг** (parent=29)
- управление, ТОС, ограничения, менеджмент, операции, бутылочное горлышко, КРС, бурение → **Управление** (parent=32)

Показать пользователю определённую категорию и дать возможность переопределить.

### Step 5: Сгенерировать обложку

```bash
python tools/generate_cover.py "ARTICLE_TITLE" --upload
```

Возвращает JSON: `{url, local_path, filename}`. `url` — это URL файла в WordPress Media Library. Сохранить его как `cover_url`, а локальный путь как `cover_local_path`.

Если генерация упала — стоп, сообщить пользователю. Без обложки не продолжаем (n8n требует cover_url).

### Step 6: Подготовить контент

Используя `title`, `body_text` из DOCX и `tone-of-voice.md`, подготовить два разных блока:
- `tg_text` — адаптировать под Telegram.
- `blog_html` — не адаптировать и не пересказывать; только разметить исходный `body_text` в HTML.

**Telegram пост (`tg_text`):**

Структура поста — три обязательные части в этом порядке:

1. **Основной текст** — по tone-of-voice (тезис → 3–5 пунктов → жёсткий призыв). В этой части допустимы только функциональные эмодзи: `→ • ▪ ⚙`. Никаких 🔥💪🚀❤️ и подобных.

2. **Строка-связка с ссылками** (всегда, дословно):
   ```
   👉 Читайте об этом подробнее в блоге <a href="{BLOG_URL}">по ссылке</a> или смотрите видео на <a href="YOUTUBE_URL">YouTube</a>
   ```
   - `{BLOG_URL}` — пишется **буквально как литерал** `{BLOG_URL}` (с фигурными скобками). На этапе Step 6 финальный URL статьи ещё не известен — его подставит n8n-publisher после публикации блога. Не пытайся угадать URL.
   - `YOUTUBE_URL` — подставляется здесь сразу, мы его знаем (поле `youtube_url`).

3. **Блок реакций** — три строки в формате `{эмодзи}  —  {фраза}`:
   ```
   {emoji1}  —  {фраза 1}
   {emoji2}  —  {фраза 2}
   {emoji3}  —  {фраза 3}
   ```
   Правила подбора (LLM делает это под каждую тему):
   - 3 **разных** эмодзи из стандартного набора реакций Telegram-канала (например: `👍 ❤️ 🔥 🥰 👏 😁 🤔 🤯 😱 🎉 🤩 🙏 👌 💯 🤣 ⚡ ❤️‍🔥 🤝 🫡 💔 🥱 🤨 🗿`). Канал использует дефолтный список реакций, не кастомные.
   - Каждая фраза — **2–6 слов**, по теме поста. Эмодзи и фраза бьют в одну точку: эмодзи — реакция, фраза — что эта реакция значит для этой темы.
   - Хороший паттерн (но не догма): один на согласие («да, узнаю себя»), один на инсайт («теперь понятнее»), один на провокацию/несогласие («ну вы перегибаете»).

**Лимиты и формат:**
- Лимит 1024 символа (caption sendPhoto). Если больше — n8n сам отправит фото отдельно + текст отдельным sendMessage (до 4096).
- Только разрешённые HTML-теги: `<b>`, `<i>`, `<a>`, `<code>`, `<pre>`.
- Блок реакций — **единственное место в посте, где разрешены украшающие эмодзи**. В основном тексте по-прежнему только функциональные `→ • ▪ ⚙`.

**Blog статья (`blog_html`) — Дзен-совместимая:**
- Работай как верстальщик, не как редактор: сохранить смысл, порядок, структуру и авторскую подачу исходного `body_text`.
- Не сокращать текст, не переписывать фразы, не добавлять новые мысли, не объединять разные смысловые блоки и не превращать сценарий в новую статью.
- В `blog_html` не включать заголовок `title` и дату публикации: заголовок уже лежит в поле `title`, дата — в `scheduled_at`. Если `body_text` начинается отдельной строкой даты, убрать только эту строку.
- Обычные смысловые абзацы оборачивать в `<p>...</p>`.
- Явные разделы и подзаголовки исходного текста оборачивать в `<h2>...</h2>`. Не придумывать подзаголовки, если их нет в исходнике.
- Списки, которые уже есть в исходнике, размечать как `<ul>/<li>` или `<ol>/<li>` без изменения формулировок пунктов.
- YouTube видео давать как plain link (НЕ iframe): `https://www.youtube.com/watch?v=VIDEO_ID` (Дзен сам сделает виджет).
- После удаления HTML-тегов чистый текст должен практически совпадать с исходным `body_text`, кроме удалённых заголовка/даты и нормализации пробелов.
- **Разрешённые теги:** p, a, b, i, u, s, h1-h4, blockquote, ul/li, ol/li, figure, img, br
- **Запрещены:** iframe, div, span, table, script, style, form, section, article
- Минимум 300 символов чистого текста (без тегов)

**SEO meta (`blog_meta`):** 150-160 символов, используется как описание в RSS-карточке Дзена.

**Blog alias (`blog_alias`):** взять из имени DOCX (`alias` поле из `read_docx.py`). Это уже транслит lowercase с дефисами.

**Blog parent (`blog_parent`):** ID категории из Step 4.

### Step 7: Превью пользователю

Показать компактно:

```
Title: {title}
Категория: {Бизнес/Маркетинг/Управление}
Публикация: {scheduled_at} MSK

Telegram ({len} chars): {first 200 chars}...
Blog ({len} chars): {first 200 chars}... (ещё N абзацев)
Обложка: {cover_url}

Режим: {review_needed или ready}
Вопрос:
- обычный режим: «Сохранить черновик и ждать правок шефа? [OK / Изменить / Отмена]»
- approval mode: «Поставить в публикацию? [OK / Изменить / Отмена]»
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
  "cover_url": "https://.../wp-content/uploads/...",
  "cover_local_path": ".tmp/covers/...",
  "status": "review_needed"
}
```

В approval mode после финального OK payload должен содержать `"status": "ready"`. В обычном режиме payload должен содержать `"status": "review_needed"`.

n8n webhook делает upsert по `youtube_id` — повторный вызов обновит ту же строку, дубль не создастся.

Проверить ответ. Если HTTP 200 и body содержит OK — успех. Иначе — показать пользователю ответ и спросить что делать.

**Внимание для Bash под Windows:** при больших JSON с кириллицей всегда писать payload во временный файл (через Write tool в `.tmp/sheets_payload.json`) и передавать через `--data-binary @file.json`, чтобы избежать экранирования кавычек и проблем с кириллицей в shell.

### Step 9: Подтверждение

Сообщить пользователю:

Если `status=review_needed`:
```
📝 Черновик сохранён и ждёт правок шефа.
🕐 План: {scheduled_at} MSK
📺 YouTube: {youtube_url}
📝 Категория: {category}
📊 Sheets row updated: status=review_needed

После правок напишите: «шеф внёс правки, можно публиковать {youtube_url}».
```

Если `status=ready`:
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
| `tools/generate_cover.py` (Python) | — | Сгенерировать AI-обложку через OpenRouter, загрузить в WordPress Media Library |
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
| `status` | оба | uploaded → review_needed → ready → publishing → published / failed |
| `published_at` | n8n publisher | после успешной публикации |
| `tg_msg_id` | n8n publisher | после Telegram send |
| `blog_url` | n8n publisher | после blog publish |
| `error` | n8n publisher | при failure |

## Error Handling

| Error | Action |
|-------|--------|
| YouTube URL не парсится | Попросить корректный URL формата https://youtube.com/watch?v=ID |
| DOCX не найден ни одним способом | Список через `ls` + просьба указать файл вручную |
| `read_docx.py` упал | Показать stderr пользователю, не продолжать |
| Cover generation failed | Стоп, сообщить пользователю — без обложки публикация не идёт |
| n8n webhook вернул не-200 | Показать ответ, спросить retry/cancel |
| .env отсутствует | Стоп, сообщить пользователю заполнить .env |
| Lookup в Sheets — статус published | Стоп, не пересоздавать публикацию |
| Lookup в Sheets — статус ready | Спросить «Заменить?» — если да, перезаписать через тот же webhook |
| Lookup в Sheets — статус review_needed | В обычном режиме обновить черновик; в approval mode перечитать DOCX и после OK поставить ready |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Брать контент из YouTube транскрипта | НЕ. Источник всегда DOCX из `.tmp/teleprompter/` |
| Публиковать напрямую в Telegram/blog API | НЕ. Только через POST в n8n webhook. Публикует n8n. |
| Ставить `status=ready` без явного разрешения | НЕ. Первый прогон всегда `review_needed`; `ready` только после фразы approval mode и финального OK. |
| Sharing API keys in chat | NEVER. Always read from .env file |
| Shell state assumptions | Каждый Bash вызов независим — перечитывать .env при необходимости |
| Создавать DOCX с произвольным именем | Имя строго `YYYY-MM-DD-HHMM-Русский заголовок.docx` — иначе scheduled_at не извлечётся |
| Игнорировать ответ webhook | Всегда проверять HTTP код и body — если не OK, не репортить пользователю успех |

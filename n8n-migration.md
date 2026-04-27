# n8n Migration Guide — импорт нового n8n.json

Один объединённый workflow заменяет старые `n8n.json` + `n8n_actual.json`. Делает 4 вещи: загружает видео из Drive на YouTube (scheduled), читает Sheets каждые 5 минут и публикует в Telegram + блог, отдаёт два webhook'а для Claude Code.

## Шаг 1. Бэкап старого workflow в n8n UI

Если старый workflow уже импортирован — **деактивируйте его** (toggle Active → off), но не удаляйте, пока новый не заработает. Потом можно удалить.

## Шаг 2. Импорт

n8n UI → **Workflows → Import from File** → выбрать `F:\program\claude_code_project\smm_agent\n8n.json`.

## Шаг 3. Заменить credential ID для Google Sheets

В файле во всех узлах Google Sheets стоит placeholder `REPLACE_ME_GOOGLE_SHEETS_CRED_ID`. Откройте каждый Sheets-узел и выберите свой `googleSheetsOAuth2Api` credential из дропдауна. Узлы Sheets:

1. `📊 Upsert Sheets (uploaded)` (uploader)
2. `📊 Read Sheets` (publisher)
3. `🔒 Lock row (publishing)` (publisher)
4. `✅ Mark published` (publisher)
5. `❌ Mark failed` (publisher)
6. `📊 Read schedule (lookup)` (lookup webhook)
7. `📊 Update row` (update webhook)

Остальные credentials (Google Drive, YouTube, OpenRouter, Telegram) уже прописаны — должны подтянуться автоматически из существующих n8n credentials.

## Шаг 4. Создать Header Auth credential для блога

В n8n UI:
- **Credentials → New → Header Auth**
- **Name:** `Veselkov Blog API`
- **Header Name:** `X-API-Key`
- **Header Value:** `NiyWVKGUmi3VQfExifLiD6pZQG_9vTID` (это `BLOG_API_KEY` из локального `.env`)
- Save

После создания — открыть узлы `📝 Blog publish` и `🖼️ Blog set cover` и в поле **Credential** выбрать `Veselkov Blog API` (placeholder `REPLACE_ME_BLOG_API_CRED_ID` подменится на реальный ID).

В файле workflow `Content-Type: application/json; charset=utf-8` оставлен как обычный header — n8n догенерирует `X-API-Key` из credential.

## Шаг 5. Активация

Toggle **Active** в правом верхнем углу. Должны загореться зелёные индикаторы у всех 4 триггеров:

- `📁 Drive Trigger` (polling каждую минуту)
- `⏰ Publisher Trigger (5 min)` (раз в 5 минут)
- `🔌 Webhook: Lookup (GET)` (на пути `/webhook/e5bdfd41-4fad-4442-b707-1d416bd5c3b2`)
- `🔌 Webhook: Update (POST)` (на пути `/webhook/905e8882-caab-4e40-8f42-c6f63524f3e8`)

## Проверка после активации

**Test Lookup webhook:**
```bash
curl "https://bigetn8n.casacam.net/webhook/e5bdfd41-4fad-4442-b707-1d416bd5c3b2?youtube_id=test123"
```
Ожидание: `{"found": false, "row": null}`.

**Test Update webhook (создаст тестовую строку):**
```bash
curl -X POST "https://bigetn8n.casacam.net/webhook/905e8882-caab-4e40-8f42-c6f63524f3e8" \
  -H "Content-Type: application/json" \
  -d '{"youtube_id":"test123","title":"Test","status":"ready","scheduled_at":"2030-01-01 00:00"}'
```
Ожидание: `{"ok": true, "youtube_id": "test123", "status": "ready"}`. После теста удалить строку вручную в Sheets.

**End-to-end:**
1. Через `/video-script` создать DOCX с датой публикации now+15 минут.
2. Загрузить mp4 в Drive с тем же именем без расширения (`YYYY-MM-DD-HHMM-alias.mp4`).
3. Через 1-2 минуты — Telegram-уведомление в `-1003932006777` со ссылкой на YouTube + командой `/publish-from-script`.
4. Запустить эту команду в Claude Code → строка в Sheets обновится со `status=ready`.
5. В назначенное время (через 15 мин) — пост в `-1001972632255` + статья на блоге + уведомление «✅ Опубликовано» в служебный канал.

## Что встроено в новый workflow (изменения относительно legacy)

- **Парсер имени mp4** упрощён до regex `^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})-(.+)\.mp4$`. Категория YouTube зафиксирована на `22` (People & Blogs).
- **YouTube `publishAt`** автоматически проставляется когда дата в имени валидна и в будущем (минимум now+15 мин). Privacy = `private` для scheduled, `public` для immediate.
- **Все Sheets-узлы** имеют явный `defineBelow` mapping и `matchingColumns: ["youtube_id"]` — нет риска создать дубль строки.
- **`🔒 Lock row (publishing)`** ставит `status=publishing` перед публикацией — защита от parallel runs.
- **`✅ Mark published`** ставит `status=published`, `published_at` (текущее время MSK), `tg_msg_id`, `blog_url`.
- **`❌ Mark failed`** ставит `status=failed` и пишет error message. Подключён ко всем точкам отказа: TG send, Blog publish, Fetch cover.
- **Telegram уведомление об uploaded** упоминает `/publish-from-script` (не старый `/repurpose-youtube-video`).
- **Reminder ветка удалена** — никаких напоминаний за 1-3 часа до публикации.
- **Webhooks без auth** (как просили): `httpMethod: GET/POST` без `authentication: headerAuth`.
- **Update webhook** имеет `📦 Unpack body` ноду — она распаковывает payload из `$json.body` в плоский item (без этого Sheets autoMapInputData не видит поля). Также фильтрует только разрешённые колонки (защита от мусора).

## Backup

Старые файлы сохранены:
- `n8n.legacy.json` — старый uploader-only workflow
- `n8n_actual.legacy.json` — старый publisher workflow

Если что-то пошло не так — импортируете обратно из них.

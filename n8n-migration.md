# n8n Migration Guide

This project now uses two importable n8n workflows:

1. `n8n.json` - uploader + lookup/update webhooks.
2. `n8n-wordpress-publisher.json` - scheduled Telegram + WordPress publisher.

Codex prepares content and updates Google Sheets through webhooks. n8n is the only component that uploads/schedules/publishes.

## Filename Contract

Rendered MP4 files uploaded to Google Drive must use:

```text
YYYY-MM-DD-HHMM-Русский заголовок.mp4
```

Example:

```text
2026-06-25-1400-Топ 5 экономических инструментов.mp4
```

`n8n.json` parses the date/time from the prefix, keeps the Russian title tail as the YouTube title, and writes `scheduled_at` to Sheets as `YYYY-MM-DD HH:MM` in MSK.

Upload only the rendered MP4 from `.tmp/rendered/`, not raw camera footage.

## Import

In n8n UI:

1. Open **Workflows -> Import from File**.
2. Import `n8n.json`.
3. Import `n8n-wordpress-publisher.json`.
4. Keep old workflows inactive until the new pair is verified.

## Credentials

After import, open every credential-bearing node and select the local n8n credential:

- Google Drive: Drive trigger, video download/upload/download nodes.
- YouTube OAuth: `🎥 Загрузить на YouTube`.
- Google Sheets: all schedule read/update/upsert nodes.
- Telegram: notification and publish nodes.
- WordPress: `📝 Blog publish`.
- OpenRouter: thumbnail generation node in `n8n.json`, if used by the imported workflow.

Do not reintroduce the old `veselkov.me/api-publish.html` or `api-set-cover.html` HTTP API nodes. Publishing to the blog must use the WordPress node.

## Webhooks

Current `.env` endpoints:

```text
N8N_WEBHOOK_LOOKUP=/webhook/e5bdfd41-4fad-4442-b707-1d416bd5c3b2
N8N_WEBHOOK_UPDATE=/webhook/905e8882-caab-4e40-8f42-c6f63524f3e8
```

Lookup smoke test:

```bash
curl "https://bigetn8n.casacam.net/webhook/e5bdfd41-4fad-4442-b707-1d416bd5c3b2?youtube_id=test123"
```

Update smoke test creates or updates a test row:

```bash
curl -X POST "https://bigetn8n.casacam.net/webhook/905e8882-caab-4e40-8f42-c6f63524f3e8" \
  -H "Content-Type: application/json" \
  --data-binary '{"youtube_id":"test123","title":"Test","status":"review_needed","scheduled_at":"2030-01-01 00:00"}'
```

Delete the test row from Sheets after checking.

## Sheets

Use `smm-schedule-template.xlsx` or create a sheet named `schedule` with the column order documented in `AGENTS.md`.

The lifecycle is:

```text
uploaded -> review_needed -> ready -> publishing -> published
                                      \-> failed
```

The publisher workflow only publishes rows with `status=ready` and `scheduled_at <= now`.

## End-to-End Check

1. Create a DOCX with `/video-script`; it should be named `YYYY-MM-DD-HHMM-Русский заголовок.docx`.
2. Record raw video.
3. Render visuals with `/render-docx-visuals raw.mp4 --docx <docx_path>`.
4. Upload `.tmp/rendered/YYYY-MM-DD-HHMM-Русский заголовок.mp4` to Google Drive.
5. Wait for the service-channel YouTube upload notification.
6. Run `/publish-from-script <youtube_url>` to prepare content; Sheets status becomes `review_needed`.
7. After explicit approval, run `/publish-from-script шеф внёс правки, можно публиковать <youtube_url>`; Sheets status becomes `ready`.
8. At scheduled time, verify Telegram video, WordPress post, `published_at`, `tg_msg_id`, and `blog_url`.

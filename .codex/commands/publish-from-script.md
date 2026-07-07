---
description: Подготовить посты Telegram + блог из DOCX-сценария и сохранить в Google Sheets через n8n. Аргумент — YouTube URL загруженного видео.
---

Следуй workflow из `.codex/skills/publish-from-script/SKILL.md`, используя аргументы пользователя (`$ARGUMENTS`).

Контекст для модели:
- Аргумент `$ARGUMENTS` обычно содержит YouTube URL (`https://youtube.com/watch?v=...` или `https://youtu.be/...`).
- Если URL не передан — коротко спроси URL у пользователя.
- Дальше следуй workflow из skill SKILL.md: lookup в Sheets → найти DOCX в `.tmp/teleprompter/` → прочитать через `tools/read_docx.py` → сгенерировать обложку через `tools/generate_cover.py` → адаптировать `tg_text` и `blog_html` → preview → POST в n8n webhook.
- Первый прогон без явного разрешения ставит `status=review_needed`, чтобы n8n не публиковал черновик.
- Если пользователь пишет, что шеф внёс правки и можно публиковать, перечитай тот же DOCX заново и только после финального OK поставь `status=ready`.

НЕ публикуй сам в Telegram/блог — только обновляешь строку в Sheets. n8n публикует только строки со `status=ready` в назначенное `scheduled_at`.

---
description: Подготовить посты Telegram + блог из DOCX-сценария и поставить в очередь Google Sheets через n8n. Аргумент — YouTube URL загруженного видео.
---

Запусти skill `publish-from-script` через Skill tool, передав в него аргументы пользователя ($ARGUMENTS).

Контекст для модели:
- Аргумент `$ARGUMENTS` обычно содержит YouTube URL (`https://youtube.com/watch?v=...` или `https://youtu.be/...`).
- Если URL не передан — спроси через AskUserQuestion.
- Дальше следуй workflow из skill SKILL.md: lookup в Sheets → найти DOCX в `.tmp/teleprompter/` → прочитать через `tools/read_docx.py` → сгенерировать обложку через `tools/generate_cover.py` → адаптировать `tg_text` и `blog_html` → preview → POST в n8n webhook со `status=ready`.

НЕ публикуй сам в Telegram/блог — только кладёшь строку в Sheets, n8n опубликует в назначенное `scheduled_at`.

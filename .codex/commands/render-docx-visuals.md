---
description: Смонтировать raw MP4 с изображениями, таблицами и схемами из DOCX перед загрузкой в Google Drive.
---

Запусти skill `render-docx-visuals`, передав аргументы пользователя (`$ARGUMENTS`).

Правила:
- Используй wrapper `.codex/skills/render-docx-visuals/scripts/render_docx_visuals.py`.
- DOCX обязателен: `--docx "<path>"`.
- Если путь к raw MP4 или DOCX не передан и в `.tmp/video/` / `.tmp/docx/` есть ровно один очевидный кандидат, используй его; если кандидатов несколько, спроси точный путь.
- По умолчанию нужен anti-flicker режим: изображения висят до следующей картинки, webcam идёт непрерывным PiP.
- Итоговый файл должен лежать в `.tmp/rendered/` и называться по DOCX stem.
- В Google Drive загружать rendered MP4, не raw.

Типовой запуск:

```bash
python3 .codex/skills/render-docx-visuals/scripts/render_docx_visuals.py \
  "<raw_mp4>" \
  --docx "<docx_path>" \
  --force
```

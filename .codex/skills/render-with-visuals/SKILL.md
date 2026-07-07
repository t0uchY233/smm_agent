---
name: render-with-visuals
description: Use when a raw talking-head MP4 should be converted into a final MP4 with automatic visual cards/slides overlaid before upload to Google Drive and YouTube
---

# Render With Visuals

## Overview

Локальный шаг `1.5` между записью и загрузкой в Google Drive. Шеф записывает raw-видео по DOCX-телесуфлёру без листания слайдов. Этот skill генерирует карточки из DOCX, синхронизирует их с речью через AssemblyAI и собирает финальный MP4 через `tools/render_video_visuals.py`.

В n8n ничего не публикуем и не загружаем. После рендера пользователь загружает в Google Drive уже готовый файл `.tmp/rendered/YYYY-MM-DD-HHMM-Русский заголовок.mp4`.

## Requirements

- `.env` содержит `ASSEMBLYAI_API_KEY`.
- В системе доступен `ffmpeg`.
- DOCX лежит в `.tmp/teleprompter/YYYY-MM-DD-HHMM-Русский заголовок.docx`.
- Raw MP4 желательно назвать тем же basename: `YYYY-MM-DD-HHMM-Русский заголовок.mp4`.

## Embedded DOCX Visual Guard

If the DOCX contains embedded files under `word/media/*`, do not continue with generated text-card mode. Use `render-docx-visuals` instead.

In DOCX visual mode, `embedded_images` only proves extraction. It does not prove that charts, dashboards, schemes, screenshots, and tables reached the rendered video. After every render, compare:

- all `slides[].id` values in `embedded_visual_plan.json`;
- all `slide_id` values in `timeline.json`.

Every `docx_visual_*` from the slide plan must appear in the timeline. If any are missing, treat the render as failed, fix timing/anchor handling, and re-render before reporting success.

## Workflow

1. Получить путь к raw MP4.
2. Если пользователь явно передал DOCX — использовать его. Иначе искать `.tmp/teleprompter/<video-stem>.docx`.
3. Запустить:
   ```bash
   python3 tools/render_video_visuals.py "<raw_mp4>" --force
   ```
4. Если нужно проверить без AssemblyAI и финального рендера:
   ```bash
   python3 tools/render_video_visuals.py "<raw_mp4>" --dry-run
   ```
5. Показать пользователю JSON-результат: `output_video`, `slide_plan`, `timeline`, `asr_matches`, `fallback_matches`.
6. Сказать, что в Google Drive нужно загрузить `output_video`, не raw-файл.

## Output Contract

Артефакты:

```text
.tmp/visuals/<base>/slide_plan.json
.tmp/visuals/<base>/transcript.json
.tmp/visuals/<base>/timeline.json
.tmp/visuals/<base>/slide_001.png
.tmp/rendered/<base>.mp4
```

`<base>` должен совпадать с `YYYY-MM-DD-HHMM-Русский заголовок`, чтобы n8n дальше распарсил публикацию без изменений.

## Failure Handling

| Ошибка | Действие |
|---|---|
| DOCX не найден | Попросить пользователя передать `--docx <path>` |
| Нет `ASSEMBLYAI_API_KEY` | Остановиться и попросить заполнить `.env` |
| AssemblyAI не распознал часть якорей | Продолжить: timeline использует fallback по позиции текста |
| FFmpeg упал | Показать stderr и не загружать raw в Drive |

## Common Mistakes

- Не загружать raw MP4 в Drive после появления этого шага.
- Не менять имя rendered-файла: n8n ждёт `YYYY-MM-DD-HHMM-Русский заголовок.mp4`.
- Не ставить слайды вручную во время записи: вся синхронизация делается после записи.

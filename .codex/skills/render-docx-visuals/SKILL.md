---
name: render-docx-visuals
description: Use whenever a raw talking-head MP4 must be edited with images, tables, charts, schemes, screenshots, or embedded visuals from a DOCX document before Google Drive upload. Preferred for requests like "сделай монтаж по DOCX", "вставь картинки из DOCX", "таблицы должны висеть долго", "убери моргание вебкамеры", or any SMM render where DOCX already contains visuals.
---

# Render DOCX Visuals

## Purpose

Render step `1.5` in the SMM pipeline. Use it after raw video recording and before Google Drive upload when the DOCX already contains ready images/tables/schemes. The skill does not publish or upload anything; it produces a checked MP4 in `.tmp/rendered/`.

Default behavior is the anti-flicker DOCX mode:

- use embedded DOCX images, not generated text cards;
- pass `--use-docx-images` to the root render tool through the wrapper;
- keep visuals long with `until-next` timing;
- preserve every embedded DOCX visual in the final timeline, including charts, dashboards, schemes, screenshots, and tables;
- render visual cards as one continuous visual block after the first visual appears;
- keep webcam as continuous PiP over visuals, avoiding per-image webcam blink;
- name the output from the DOCX stem when possible, so Drive gets the scheduled filename.

## Primary Command

Prefer the bundled wrapper. It chooses the output filename, reuses an existing transcript when found, calls FFmpeg through the root tool, and validates the rendered MP4.

```bash
python3 .codex/skills/render-docx-visuals/scripts/render_docx_visuals.py \
  "<raw_mp4>" \
  --docx "<docx_path>" \
  --force
```

If system Python lacks `pillow` or `python-docx`, the wrapper automatically uses:

```bash
uv run --with pillow --with python-docx python tools/render_video_visuals.py ...
```

## Inputs

- `raw_mp4`: raw talking-head video, usually in `.tmp/video/`.
- `--docx`: required DOCX with embedded images in `word/media/*`, usually in `.tmp/docx/` or `.tmp/teleprompter/`.
- `--transcript-json`: optional existing AssemblyAI transcript. If omitted, the wrapper checks `.tmp/visuals/<raw-stem>/transcript.json` and `.tmp/visuals/<docx-stem>/transcript.json` before allowing the root tool to call AssemblyAI.
- `--output-file`: optional exact output path. Default is `.tmp/rendered/<docx-stem>.mp4`.
- `--force`: overwrite existing rendered MP4.
- `--dry-run`: build extraction/timeline artifacts without final FFmpeg render.

## Workflow

1. Confirm both paths exist. Do not guess a missing DOCX if multiple candidates exist.
2. Run a dry-run first only when the user asks to inspect timing or when the file pairing is uncertain.
3. Run the wrapper with `--force` for the final render.
4. Read the wrapper JSON. Report:
   - `output_video`
   - `embedded_images`
   - `asr_matches` / `fallback_matches`
   - validation duration and video shape
5. Run the timeline completeness gate:
   - read `embedded_visual_plan.json` and collect every `slides[].id`;
   - read `timeline.json` and collect every `slide_id`;
   - verify `len(timeline) == embedded_images == len(slides)` and `set(timeline.slide_id) == set(slides.id)`;
   - if any `docx_visual_*` is missing, do not call the render finished. Fix timing/anchor handling and re-render.
6. Extract QA frames for at least one early visual and one non-table visual such as a chart, dashboard, scheme, or screenshot.
7. Tell the user to upload `output_video` to Google Drive, not the raw MP4.

## Output Contract

Expected artifacts:

```text
.tmp/rendered/<docx-stem>.mp4
.tmp/rendered/<docx-stem>.segments/
.tmp/visuals/<docx-stem>/embedded_visual_plan.json
.tmp/visuals/<docx-stem>/timeline.json
.tmp/visuals/<docx-stem>/docx_images/docx_visual_001.png
.tmp/visuals/<docx-stem>/docx_visual_001.png
```

The rendered MP4 must pass `ffprobe` validation:

- container duration and video duration differ by no more than 1 second;
- audio duration, if present, differs by no more than 1 second;
- video is 1920x1080 H.264/yuv420p.
- timeline completeness passes: every embedded `docx_visual_*` from the slide plan appears in `timeline.json`.
- every timeline item is visible for at least 5 seconds: `end_sec - start_sec >= 5.0`.

## Timing Policy

- Default mode is `until-next`: each image stays until the next image starts.
- The last image stays until the end of the video.
- Anchors come from image captions, cleaned captions, previous paragraph, and next paragraph.
- Fallback matches are acceptable, but report their count.
- Repeated or close anchors are common when a chart and table share nearby narration. Do not drop a visual only because its computed duration is short. Prefer a short visible segment over losing dashboards/charts/images.
- Minimum visibility is 5 seconds for every visual. If two anchors are too close, push the later visual start forward; do not create 2-3 second flashes.

## Failure Handling

| Problem | Action |
|---|---|
| DOCX has no embedded images | Stop and use `render-with-visuals` instead if generated cards are acceptable |
| `timeline.json` has fewer rows than embedded images | Treat as render failure; identify missing `docx_visual_*`, fix timing/anchor handling, and re-render |
| Any timeline item is shorter than 5 seconds | Treat as render failure; push close starts forward and re-render |
| No transcript and no `ASSEMBLYAI_API_KEY` | Ask for `.env` fix or a `--transcript-json` path |
| Validation fails | Do not upload to Drive; fix render command or timeline first |
| Output exists | Re-run with `--force` only if overwriting is intended |

## Do Not

- Do not upload raw MP4 after a rendered MP4 exists.
- Do not use generated text-card mode when DOCX already has visuals.
- Do not report success when only tables appear but DOCX also contains charts, dashboards, schemes, or screenshots.
- Do not rely on `embedded_images` alone; it proves extraction, not placement in the rendered video.
- Do not manually publish to YouTube, Telegram, or WordPress from this skill.

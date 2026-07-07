"""
Локальный рендер визуальных карточек поверх raw-видео.

Использование:
  python3 tools/render_video_visuals.py ".tmp/raw/2026-06-25-1400-Топ 5 экономических инструментов.mp4"
  python3 tools/render_video_visuals.py raw.mp4 --docx .tmp/teleprompter/file.docx

Возвращает JSON с путями к артефактам.
"""
import argparse
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
CARD_SIZE = (1920, 1080)
MIN_VISUAL_DURATION_SEC = 5.0
VISUAL_TIMELINE_GAP_SEC = 0.1
ASSEMBLYAI_BASE_URL = "https://api.assemblyai.com"
XML_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


class RenderVisualsError(RuntimeError):
    pass


def parse_env(path=ROOT / ".env"):
    values = {}
    if not Path(path).exists():
        return values
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_missing_api_key(value):
    value = (value or "").strip()
    return not value or value in {"your_assemblyai_api_key_here", "your_api_key_here", "YOUR_API_KEY"}


def normalize_text(text):
    text = (text or "").lower().replace("ё", "е")
    chars = []
    for char in text:
        chars.append(char if char.isalnum() else " ")
    return " ".join("".join(chars).split())


def tokenize(text):
    normalized = normalize_text(text)
    return normalized.split() if normalized else []


def find_matching_docx(video_path, teleprompter_dir=ROOT / ".tmp" / "teleprompter"):
    video_path = Path(video_path)
    teleprompter_dir = Path(teleprompter_dir)
    exact = teleprompter_dir / f"{video_path.stem}.docx"
    if exact.exists():
        return exact

    stem = video_path.stem
    m = re.match(r"^(\d{4}-\d{2}-\d{2}-\d{4})-(.+)$", stem)
    if not m:
        return None
    prefix = m.group(1)
    candidates = sorted(
        teleprompter_dir.glob(f"{prefix}-*.docx"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def read_docx_via_tool(docx_path):
    cmd = [sys.executable, str(ROOT / "tools" / "read_docx.py"), str(docx_path)]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RenderVisualsError(proc.stderr.strip() or "read_docx.py failed")
    return json.loads(proc.stdout)


def xml_text(element):
    return " ".join(
        "".join(node.text or "" for node in element.findall(".//w:t", XML_NS)).split()
    )


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def rel_target_to_zip_path(target):
    if target.startswith("/"):
        return target.lstrip("/").replace("\\", "/")
    return f"word/{target}".replace("\\", "/")


def clean_caption_anchor(text):
    return re.sub(r"^(таблица|схема|график|рисунок)\s+\d+\s*[.:]\s*", "", text or "", flags=re.IGNORECASE).strip()


def extract_docx_embedded_images(docx_path, output_dir):
    docx_path = Path(docx_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(docx_path) as archive:
        rel_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rel_root}
        root = ET.fromstring(archive.read("word/document.xml"))
        body = root.find("w:body", XML_NS)
        if body is None:
            raise RenderVisualsError(f"DOCX body not found: {docx_path}")

        items = []
        paragraph_index = 0
        for child in list(body):
            kind = local_name(child.tag)
            if kind == "p":
                paragraph_index += 1
            if kind not in {"p", "tbl"}:
                continue
            text = xml_text(child)
            image_rids = [
                blip.attrib.get(f"{{{XML_NS['r']}}}embed")
                for blip in child.findall(".//a:blip", XML_NS)
                if blip.attrib.get(f"{{{XML_NS['r']}}}embed")
            ]
            if text or image_rids:
                items.append(
                    {
                        "kind": kind,
                        "paragraph_index": paragraph_index if kind == "p" else None,
                        "text": text,
                        "image_rids": image_rids,
                    }
                )

        visuals = []
        for item_index, item in enumerate(items):
            for rid in item["image_rids"]:
                target = rels.get(rid)
                if not target:
                    continue
                zip_path = rel_target_to_zip_path(target)
                image_bytes = archive.read(zip_path)
                suffix = Path(zip_path).suffix or ".png"
                visual_id = f"docx_visual_{len(visuals) + 1:03d}"
                source_image_path = output_dir / f"{visual_id}{suffix}"
                source_image_path.write_bytes(image_bytes)

                with Image.open(io.BytesIO(image_bytes)) as image:
                    dimensions = image.size

                before = nearest_text(items, item_index, direction=-1)
                after = nearest_text(items, item_index, direction=1)
                own_text = item["text"]
                caption = own_text or after
                cleaned_caption = clean_caption_anchor(caption)
                anchor_candidates = [
                    candidate
                    for candidate in [cleaned_caption, caption, before, after]
                    if candidate
                ]
                visuals.append(
                    {
                        "id": visual_id,
                        "source": "docx_image",
                        "relationship_id": rid,
                        "source_zip_path": zip_path,
                        "source_image_path": str(source_image_path),
                        "width": dimensions[0],
                        "height": dimensions[1],
                        "caption": caption,
                        "paragraph_before": before,
                        "paragraph_after": after,
                        "anchor": caption,
                        "anchor_candidates": list(dict.fromkeys(anchor_candidates)),
                    }
                )

    return visuals


def nearest_text(items, start_index, direction):
    index = start_index + direction
    while 0 <= index < len(items):
        text = items[index].get("text", "").strip()
        if text:
            return text
        index += direction
    return ""


def best_visual_anchor(visual):
    candidates = visual.get("anchor_candidates") or [visual.get("anchor", "")]
    return candidates[0] if candidates else ""


def render_docx_image_card(visual, output_dir, video_title=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{visual['id']}.png"

    image = Image.new("RGB", CARD_SIZE, "#f7f7f2")
    draw = ImageDraw.Draw(image)
    small_font = find_font(bold=True, size=28)

    accent = "#2858a3"
    draw.rectangle((0, 0, 1920, 26), fill=accent)
    draw.rounded_rectangle((105, 76, 1815, 984), radius=22, fill="#ffffff", outline="#dfdfd8", width=3)
    draw.text((140, 106), "VISUAL", fill=accent, font=small_font)

    with Image.open(visual["source_image_path"]) as source:
        source = source.convert("RGB")
        source.thumbnail((1640, 680), Image.LANCZOS)
        x = 140 + (1640 - source.width) // 2
        y = 150 + (680 - source.height) // 2
        image.paste(source, (x, y))

    draw.line((470, 935, 1780, 935), fill="#e6e2d8", width=2)
    footer = f"Сергей Веселков | {video_title or 'инженерный разбор бизнеса'}"
    draw.text((470, 952), footer, fill="#565656", font=small_font)

    image.save(output, "PNG")
    return output


def generate_docx_image_visual_plan(title, docx_path, output_dir, duration_sec=24, footer_title=None):
    visuals = extract_docx_embedded_images(docx_path, Path(output_dir) / "docx_images")
    if not visuals:
        raise RenderVisualsError(f"No embedded images found in DOCX: {docx_path}")

    slides = []
    for visual in visuals:
        card_path = render_docx_image_card(visual, output_dir, video_title=footer_title or title)
        slides.append(
            {
                "id": visual["id"],
                "title": visual.get("caption") or visual["id"],
                "kind": "docx_image",
                "source": "docx_image",
                "source_image_path": visual["source_image_path"],
                "image_path": str(card_path),
                "anchor": best_visual_anchor(visual),
                "anchor_candidates": visual.get("anchor_candidates", []),
                "caption": visual.get("caption", ""),
                "duration_sec": duration_sec,
            }
        )

    return {
        "title": title,
        "slides": slides,
    }


def split_sentences(text):
    parts = []
    for paragraph in re.split(r"\n\s*\n+", text or ""):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
        if len(sentences) <= 2:
            cleaned = " ".join(sentences)
            if cleaned:
                parts.append(cleaned)
            continue
        group_size = 2 if len(sentences) <= 16 else 3
        for index in range(0, len(sentences), group_size):
            cleaned = " ".join(sentences[index : index + group_size]).strip()
            if cleaned:
                parts.append(cleaned)
    if parts:
        return parts
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def shorten_words(text, max_words):
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()


def extract_bullets(chunk):
    sentences = [s.strip(" \n\t.-") for s in re.split(r"(?<=[.!?])\s+", chunk) if s.strip()]
    if len(sentences) >= 2:
        return [shorten_words(sentence, 9) for sentence in sentences[:4]]

    tokens = chunk.split()
    if not tokens:
        return []
    groups = []
    group_size = max(5, math.ceil(len(tokens) / 3))
    for index in range(0, min(len(tokens), group_size * 4), group_size):
        groups.append(" ".join(tokens[index : index + group_size]).strip(" ,.;:!?"))
    return [group for group in groups if group][:4]


def generate_visual_plan(title, body_text, max_slides=10):
    chunks = split_sentences(body_text)
    if len(chunks) > max_slides:
        step = len(chunks) / max_slides
        chunks = [chunks[int(i * step)] for i in range(max_slides)]

    slides = []
    kinds = ["problem", "principle", "metric", "process", "result"]
    for index, chunk in enumerate(chunks[:max_slides], start=1):
        clean_chunk = " ".join(chunk.split())
        anchor = clean_chunk[:120].rstrip(" ,.;:!?")
        slide_title = shorten_words(clean_chunk.strip(" .!?"), 6)
        bullets = extract_bullets(clean_chunk)
        if not bullets:
            bullets = [slide_title]
        slides.append(
            {
                "id": f"slide_{index:03d}",
                "title": slide_title,
                "kind": kinds[(index - 1) % len(kinds)],
                "anchor": anchor,
                "bullets": bullets,
                "duration_sec": 24,
            }
        )

    return {
        "title": title,
        "slides": slides,
    }


def find_font(bold=False, size=64):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/tahomabd.ttf" if bold else "C:/Windows/Fonts/tahoma.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def wrap_text(draw, text, font, max_width):
    lines = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def render_slide_card(slide, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{slide['id']}.png"

    image = Image.new("RGB", CARD_SIZE, "#f7f7f2")
    draw = ImageDraw.Draw(image)

    title_font = find_font(bold=True, size=76)
    bullet_font = find_font(size=46)
    small_font = find_font(bold=True, size=30)

    accent = {
        "problem": "#c43d2f",
        "principle": "#1f6f5b",
        "metric": "#2858a3",
        "process": "#8a5a1f",
        "result": "#5a3f91",
    }.get(slide.get("kind"), "#2858a3")

    draw.rectangle((0, 0, 1920, 26), fill=accent)
    draw.rounded_rectangle((105, 96, 1815, 984), radius=22, fill="#ffffff", outline="#dfdfd8", width=3)
    draw.text((140, 126), slide.get("kind", "visual").upper(), fill=accent, font=small_font)

    y = 190
    for line in wrap_text(draw, slide["title"], title_font, 1500)[:3]:
        draw.text((140, y), line, fill="#171717", font=title_font)
        y += 92

    y += 30
    for bullet in slide.get("bullets", [])[:4]:
        lines = wrap_text(draw, bullet, bullet_font, 1340)
        draw.ellipse((150, y + 18, 176, y + 44), fill=accent)
        for line in lines[:2]:
            draw.text((205, y), line, fill="#242424", font=bullet_font)
            y += 58
        y += 32

    draw.line((140, 890, 1780, 890), fill="#e6e2d8", width=2)
    draw.text((140, 920), "Сергей Веселков | инженерный разбор бизнеса", fill="#565656", font=small_font)

    image.save(output, "PNG")
    return output


def http_json(method, url, api_key, payload=None, timeout=120):
    data = None
    headers = {"Authorization": api_key}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RenderVisualsError(f"AssemblyAI HTTP {exc.code}: {body[:500]}") from exc


def upload_to_assemblyai(audio_path, api_key, base_url=ASSEMBLYAI_BASE_URL):
    req = urllib.request.Request(
        f"{base_url}/v2/upload",
        data=Path(audio_path).read_bytes(),
        headers={
            "Authorization": api_key,
            "Content-Type": "application/octet-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RenderVisualsError(f"AssemblyAI upload HTTP {exc.code}: {body[:500]}") from exc
    return result["upload_url"]


def transcribe_with_assemblyai(audio_path, api_key, language_code="ru", base_url=ASSEMBLYAI_BASE_URL, poll_seconds=5, timeout_seconds=1800):
    upload_url = upload_to_assemblyai(audio_path, api_key, base_url)
    transcript = http_json(
        "POST",
        f"{base_url}/v2/transcript",
        api_key,
        {
            "audio_url": upload_url,
            "language_code": language_code,
            "speech_models": ["universal-3-pro", "universal-2"],
            "punctuate": True,
            "format_text": True,
        },
    )
    transcript_id = transcript["id"]
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = http_json("GET", f"{base_url}/v2/transcript/{transcript_id}", api_key)
        status = result.get("status")
        if status == "completed":
            return result
        if status == "error":
            raise RenderVisualsError(result.get("error") or "AssemblyAI transcription failed")
        time.sleep(poll_seconds)
    raise RenderVisualsError("AssemblyAI transcription timeout")


def find_anchor_in_words(anchor, words, min_score=0.68, start_index=0):
    anchor_tokens = tokenize(anchor)
    if not anchor_tokens or not words:
        return None, 0.0, start_index
    word_tokens = [tokenize(word.get("text", ""))[0] if tokenize(word.get("text", "")) else "" for word in words]
    window_size = max(2, len(anchor_tokens))
    best = (None, 0.0, start_index)
    anchor_norm = " ".join(anchor_tokens)

    for index in range(start_index, max(start_index, len(word_tokens) - window_size + 1)):
        window = " ".join(token for token in word_tokens[index : index + window_size] if token)
        if not window:
            continue
        score = SequenceMatcher(None, anchor_norm, window).ratio()
        if score > best[1]:
            best = (index, score, index + window_size)
    if best[0] is not None and best[1] >= min_score:
        return best
    return None, best[1], start_index


def fallback_start(anchor, body_text, video_duration, index, total):
    body_norm = normalize_text(body_text)
    anchor_norm = normalize_text(anchor)
    if body_norm and anchor_norm:
        pos = body_norm.find(anchor_norm)
        if pos >= 0:
            return round((pos / max(1, len(body_norm))) * max(1, video_duration - 10), 2)
    return round(((index + 1) / (total + 1)) * max(1, video_duration - 10), 2)


def extend_timeline_until_next(timeline, video_duration, min_duration=MIN_VISUAL_DURATION_SEC, last_duration=45.0):
    extended = []
    ordered = sorted(timeline, key=lambda row: row["start_sec"])
    for index, item in enumerate(ordered):
        updated = dict(item)
        if index + 1 < len(ordered):
            end_sec = round(float(ordered[index + 1]["start_sec"]) - VISUAL_TIMELINE_GAP_SEC, 2)
        else:
            end_sec = min(float(video_duration), float(updated["start_sec"]) + float(last_duration))
        if end_sec - float(updated["start_sec"]) >= min_duration:
            updated["end_sec"] = round(end_sec, 2)
            extended.append(updated)
    return extended


def build_timeline(slides, transcript, body_text, video_duration, duration_mode="fixed"):
    words = transcript.get("words") or []
    timeline = []
    cursor = 0

    for index, slide in enumerate(slides):
        anchors = slide.get("anchor_candidates") or [slide.get("anchor", "")]
        match_index = None
        score = 0.0
        next_cursor = cursor
        matched_anchor = slide.get("anchor", "")
        for anchor in anchors:
            candidate_index, candidate_score, candidate_cursor = find_anchor_in_words(anchor, words, start_index=cursor)
            if candidate_index is not None:
                match_index = candidate_index
                score = candidate_score
                next_cursor = candidate_cursor
                matched_anchor = anchor
                break
            if candidate_score > score:
                score = candidate_score
                matched_anchor = anchor
        if match_index is not None:
            start_sec = round((words[match_index]["start"] or 0) / 1000, 2)
            method = "asr"
            cursor = next_cursor
        else:
            start_sec = fallback_start(matched_anchor, body_text, video_duration, index, len(slides))
            method = "fallback"

        if timeline:
            min_next_start = timeline[-1]["start_sec"] + MIN_VISUAL_DURATION_SEC + VISUAL_TIMELINE_GAP_SEC
            if start_sec < min_next_start:
                start_sec = round(min_next_start, 2)

        end_sec = min(video_duration, start_sec + int(slide.get("duration_sec", 24)))
        timeline.append(
            {
                "slide_id": slide["id"],
                "start_sec": start_sec,
                "end_sec": round(end_sec, 2),
                "match_method": method,
                "score": round(score, 3),
            }
        )

    if duration_mode == "until-next":
        return extend_timeline_until_next(timeline, video_duration)
    if duration_mode != "fixed":
        raise RenderVisualsError(f"Unsupported visual duration mode: {duration_mode}")

    for index in range(len(timeline) - 1):
        next_start = timeline[index + 1]["start_sec"]
        if timeline[index]["end_sec"] >= next_start:
            timeline[index]["end_sec"] = max(timeline[index]["start_sec"] + 1, round(next_start - 0.1, 2))

    return timeline


def run_checked(cmd, capture=True):
    proc = subprocess.run(cmd, text=True, capture_output=capture)
    if proc.returncode != 0:
        if capture:
            raise RenderVisualsError(proc.stderr.strip() or f"Command failed: {' '.join(cmd)}")
        raise RenderVisualsError(f"Command failed: {' '.join(cmd)}")
    return proc.stdout if capture else ""


def ffprobe_duration(video_path):
    out = run_checked(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )
    return float(out.strip())


def extract_audio(video_path, audio_path):
    run_checked(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(audio_path),
        ],
        capture=False,
    )


def overlay_enable_expression(timeline, duration):
    parts = []
    for item in sorted(timeline, key=lambda row: row["start_sec"]):
        start = max(0.0, min(float(item["start_sec"]), duration))
        end = max(start, min(float(item["end_sec"]), duration))
        if end - start > 0.25:
            parts.append(f"between(t,{start:.3f},{end:.3f})")
    return "+".join(parts) or "0"


def render_video(raw_video, timeline, output_path, continuous_visuals=False):
    raw_video = Path(raw_video)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = ffprobe_duration(raw_video)

    if not continuous_visuals:
        return render_segmented_video(raw_video, timeline, duration, output_path)

    valid_items = []
    for item in sorted(timeline, key=lambda row: row["start_sec"]):
        start = max(0.0, min(float(item["start_sec"]), duration))
        end = max(start, min(float(item["end_sec"]), duration))
        if end - start > 0.25:
            valid_items.append({**item, "start_sec": start, "end_sec": end})

    if not valid_items:
        render_plain_segment(raw_video, 0, duration, output_path)
        return output_path

    return render_continuous_visual_block(raw_video, valid_items, duration, output_path)


def render_segmented_video(raw_video, timeline, duration, output_path):
    segments_dir = output_path.parent / f"{output_path.stem}.segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    for old in segments_dir.glob("segment_*.mp4"):
        old.unlink()

    segments = []
    cursor = 0.0
    for item in sorted(timeline, key=lambda row: row["start_sec"]):
        start = max(0.0, min(float(item["start_sec"]), duration))
        end = max(start, min(float(item["end_sec"]), duration))
        if start - cursor > 0.25:
            segment = segments_dir / f"segment_{len(segments):03d}_plain.mp4"
            render_plain_segment(raw_video, cursor, start - cursor, segment)
            segments.append(segment)
        if end - start > 0.25:
            segment = segments_dir / f"segment_{len(segments):03d}_card.mp4"
            render_card_segment(raw_video, item["image_path"], start, end - start, segment)
            segments.append(segment)
        cursor = max(cursor, end)

    if duration - cursor > 0.25:
        segment = segments_dir / f"segment_{len(segments):03d}_plain.mp4"
        render_plain_segment(raw_video, cursor, duration - cursor, segment)
        segments.append(segment)

    concat_list = segments_dir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{escape_concat_path(segment.resolve())}'\n" for segment in segments),
        encoding="utf-8",
    )
    run_checked(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture=False,
    )
    return output_path


def render_continuous_visual_block(raw_video, timeline, duration, output_path):
    raw_video = Path(raw_video)
    output_path = Path(output_path)
    segments_dir = output_path.parent / f"{output_path.stem}.segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    for old in segments_dir.glob("segment_*.mp4"):
        old.unlink()

    segments = []
    first_start = float(timeline[0]["start_sec"])
    if first_start > 0.25:
        intro = segments_dir / "segment_000_plain.mp4"
        render_plain_segment(raw_video, 0, first_start, intro)
        segments.append(intro)

    block = segments_dir / f"segment_{len(segments):03d}_visuals.mp4"
    render_visual_block_segment(raw_video, timeline, first_start, duration - first_start, block)
    segments.append(block)

    concat_list = segments_dir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{escape_concat_path(segment.resolve())}'\n" for segment in segments),
        encoding="utf-8",
    )
    run_checked(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture=False,
    )
    return output_path


def render_visual_block_segment(raw_video, timeline, start_sec, duration_sec, output_path):
    if duration_sec <= 0.25:
        return

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_sec:.3f}",
        "-t",
        f"{duration_sec:.3f}",
        "-i",
        str(raw_video),
    ]
    image_durations = []
    for index, item in enumerate(timeline):
        item_start = max(float(item["start_sec"]), start_sec)
        if index + 1 < len(timeline):
            item_end = min(float(timeline[index + 1]["start_sec"]), start_sec + duration_sec)
        else:
            item_end = start_sec + duration_sec
        image_duration = max(0.25, item_end - item_start)
        image_durations.append(image_duration)
        cmd.extend(["-loop", "1", "-t", f"{image_duration:.3f}", "-i", str(item["image_path"])])

    filters = []
    card_labels = []
    for index, image_duration in enumerate(image_durations):
        card = f"card{index}"
        filters.append(
            f"[{index + 1}:v]fps=30,scale=1920:1080,setsar=1,"
            f"trim=duration={image_duration:.3f},setpts=PTS-STARTPTS[{card}]"
        )
        card_labels.append(f"[{card}]")
    filters.append(f"{''.join(card_labels)}concat=n={len(card_labels)}:v=1:a=0[card_bg]")
    filters.append("[0:v]fps=30,scale=360:-2,setsar=1,setpts=PTS-STARTPTS[pip]")
    filters.append("[card_bg][pip]overlay=60:H-h-60:eof_action=pass[v]")

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            f"{duration_sec:.3f}",
            str(output_path),
        ]
    )
    run_checked(cmd, capture=False)


def render_video_with_enabled_overlays(raw_video, timeline, output_path):
    raw_video = Path(raw_video)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = ffprobe_duration(raw_video)

    valid_items = []
    for item in sorted(timeline, key=lambda row: row["start_sec"]):
        start = max(0.0, min(float(item["start_sec"]), duration))
        end = max(start, min(float(item["end_sec"]), duration))
        if end - start > 0.25:
            valid_items.append({**item, "start_sec": start, "end_sec": end})

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(raw_video),
    ]
    for item in valid_items:
        cmd.extend(["-loop", "1", "-i", str(item["image_path"])])

    filters = [
        "[0:v]fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,split=2[base0][pip_src]"
    ]
    current_base = "base0"
    for index, item in enumerate(valid_items):
        card = f"card{index}"
        next_base = f"base{index + 1}"
        filters.append(f"[{index + 1}:v]scale=1920:1080,setsar=1[{card}]")
        filters.append(
            f"[{current_base}][{card}]overlay=0:0:"
            f"enable='between(t,{item['start_sec']:.3f},{item['end_sec']:.3f})':"
            f"eof_action=pass[{next_base}]"
        )
        current_base = next_base

    pip_enable = overlay_enable_expression(valid_items, duration)
    filters.append("[pip_src]scale=360:-2,setsar=1[pip]")
    filters.append(f"[{current_base}][pip]overlay=60:H-h-60:enable='{pip_enable}':eof_action=pass[v]")

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            f"{duration:.3f}",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run_checked(
        cmd,
        capture=False,
    )
    return output_path


def render_plain_segment(raw_video, start_sec, duration_sec, output_path):
    run_checked(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_sec:.3f}",
            "-t",
            f"{duration_sec:.3f}",
            "-i",
            str(raw_video),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(output_path),
        ],
        capture=False,
    )


def escape_concat_path(path):
    return str(path).replace("'", "'\\''")


def render_card_segment(raw_video, image_path, start_sec, duration_sec, output_path):
    run_checked(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_sec:.3f}",
            "-t",
            f"{duration_sec:.3f}",
            "-i",
            str(raw_video),
            "-loop",
            "1",
            "-t",
            f"{duration_sec:.3f}",
            "-i",
            str(image_path),
            "-filter_complex",
            "[1:v]fps=30,scale=1920:1080,setsar=1[card];[0:v]fps=30,scale=360:-2,setsar=1[pip];[card][pip]overlay=60:H-h-60[v]",
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ],
        capture=False,
    )


def load_docx_payload(docx_path=None, docx_json_path=None):
    if docx_json_path:
        return json.loads(Path(docx_json_path).read_text(encoding="utf-8"))
    if not docx_path:
        raise RenderVisualsError("DOCX path is required")
    return read_docx_via_tool(docx_path)


def payload_from_transcript(raw_video, transcript):
    text = (transcript.get("text") or "").strip()
    if not text:
        words = [str(word.get("text", "")).strip() for word in transcript.get("words", [])]
        text = " ".join(word for word in words if word)
    if not text:
        raise RenderVisualsError("Transcript does not contain text")
    return {
        "title": Path(raw_video).stem,
        "body_text": text,
        "scheduled_at": None,
        "alias": Path(raw_video).stem,
        "source_path": None,
    }


def write_json(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(
    raw_video,
    docx_path=None,
    docx_json_path=None,
    transcript_json_path=None,
    output_dir=ROOT / ".tmp" / "rendered",
    output_file=None,
    work_root=ROOT / ".tmp" / "visuals",
    dry_run=False,
    force=False,
    use_docx_images=False,
    visual_duration=24,
    visual_duration_mode="fixed",
):
    raw_video = Path(raw_video)
    if not raw_video.exists():
        raise RenderVisualsError(f"Raw video not found: {raw_video}")

    if not docx_path and not docx_json_path and not transcript_json_path:
        docx_path = find_matching_docx(raw_video)

    output_dir = Path(output_dir)
    output_video = Path(output_file) if output_file else output_dir / f"{raw_video.stem}.mp4"
    work_dir = Path(work_root) / output_video.stem
    if output_video.exists() and not force and not dry_run:
        raise RenderVisualsError(f"Output already exists: {output_video}; use --force")

    transcript = None
    transcript_path = None
    if transcript_json_path:
        transcript_path = Path(transcript_json_path)
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    if use_docx_images and docx_json_path:
        raise RenderVisualsError("--use-docx-images requires a real DOCX path, not --docx-json")
    if use_docx_images and not docx_path:
        raise RenderVisualsError("--use-docx-images requires --docx <path>")

    if docx_path or docx_json_path:
        docx_data = load_docx_payload(docx_path, docx_json_path)
    elif transcript is not None:
        docx_data = payload_from_transcript(raw_video, transcript)
    elif dry_run:
        raise RenderVisualsError(f"DOCX not found for {raw_video.name}; pass --docx or --transcript-json")
    else:
        work_dir.mkdir(parents=True, exist_ok=True)
        env = {**parse_env(), **os.environ}
        api_key = env.get("ASSEMBLYAI_API_KEY")
        if is_missing_api_key(api_key):
            raise RenderVisualsError("ASSEMBLYAI_API_KEY is missing in .env or environment")
        audio_path = work_dir / "audio.mp3"
        extract_audio(raw_video, audio_path)
        transcript = transcribe_with_assemblyai(
            audio_path,
            api_key,
            language_code=env.get("ASSEMBLYAI_LANGUAGE_CODE", "ru"),
            base_url=env.get("ASSEMBLYAI_BASE_URL", ASSEMBLYAI_BASE_URL),
        )
        transcript_path = work_dir / "transcript.json"
        write_json(transcript_path, transcript)
        docx_data = payload_from_transcript(raw_video, transcript)

    if use_docx_images:
        slide_plan = generate_docx_image_visual_plan(
            docx_data.get("title", raw_video.stem),
            docx_path,
            work_dir,
            duration_sec=visual_duration,
            footer_title=docx_data.get("alias") or docx_data.get("title", raw_video.stem),
        )
        slide_plan_path = work_dir / "embedded_visual_plan.json"
    else:
        slide_plan = generate_visual_plan(docx_data.get("title", raw_video.stem), docx_data.get("body_text", ""))
        for slide in slide_plan["slides"]:
            slide["image_path"] = str(render_slide_card(slide, work_dir))
        slide_plan_path = work_dir / "slide_plan.json"
    write_json(slide_plan_path, slide_plan)

    if dry_run:
        timeline = build_timeline(
            slide_plan["slides"],
            transcript or {"words": []},
            docx_data.get("body_text", ""),
            video_duration=600,
            duration_mode=visual_duration_mode,
        )
        timeline_path = work_dir / "timeline.json"
        write_json(timeline_path, timeline)
        return {
            "output_video": None,
            "slide_plan": str(slide_plan_path),
            "transcript": str(transcript_path) if transcript_path else None,
            "timeline": str(timeline_path),
            "asr_matches": sum(1 for item in timeline if item["match_method"] == "asr"),
            "fallback_matches": sum(1 for item in timeline if item["match_method"] == "fallback"),
        }

    duration = ffprobe_duration(raw_video)
    if transcript is None:
        audio_path = work_dir / "audio.mp3"
        extract_audio(raw_video, audio_path)
        env = {**parse_env(), **os.environ}
        api_key = env.get("ASSEMBLYAI_API_KEY")
        if is_missing_api_key(api_key):
            raise RenderVisualsError("ASSEMBLYAI_API_KEY is missing in .env or environment")
        transcript = transcribe_with_assemblyai(
            audio_path,
            api_key,
            language_code=env.get("ASSEMBLYAI_LANGUAGE_CODE", "ru"),
            base_url=env.get("ASSEMBLYAI_BASE_URL", ASSEMBLYAI_BASE_URL),
        )
        transcript_path = work_dir / "transcript.json"
        write_json(transcript_path, transcript)

    timeline = build_timeline(
        slide_plan["slides"],
        transcript,
        docx_data.get("body_text", ""),
        duration,
        duration_mode=visual_duration_mode,
    )
    image_by_id = {slide["id"]: slide["image_path"] for slide in slide_plan["slides"]}
    for item in timeline:
        item["image_path"] = image_by_id[item["slide_id"]]
    timeline_path = work_dir / "timeline.json"
    write_json(timeline_path, timeline)

    render_video(
        raw_video,
        timeline,
        output_video,
        continuous_visuals=visual_duration_mode == "until-next",
    )
    return {
        "output_video": str(output_video),
        "slide_plan": str(slide_plan_path),
        "transcript": str(transcript_path) if transcript_path else None,
        "timeline": str(timeline_path),
        "asr_matches": sum(1 for item in timeline if item["match_method"] == "asr"),
        "fallback_matches": sum(1 for item in timeline if item["match_method"] == "fallback"),
    }


def main():
    parser = argparse.ArgumentParser(description="Render visual cards over a raw talking-head video")
    parser.add_argument("raw_mp4", help="Path to raw MP4")
    parser.add_argument("--docx", help="Path to matching DOCX script")
    parser.add_argument("--output", default=str(ROOT / ".tmp" / "rendered"), help="Output directory")
    parser.add_argument("--output-file", help="Exact output MP4 path")
    parser.add_argument("--work-root", default=str(ROOT / ".tmp" / "visuals"), help="Artifacts directory")
    parser.add_argument("--force", action="store_true", help="Overwrite existing rendered MP4")
    parser.add_argument("--dry-run", action="store_true", help="Generate cards/timeline without ASR or FFmpeg render")
    parser.add_argument("--use-docx-images", action="store_true", help="Use embedded DOCX images instead of generated text cards")
    parser.add_argument("--visual-duration", type=int, default=24, help="Seconds to show each visual card")
    parser.add_argument(
        "--visual-duration-mode",
        choices=["fixed", "until-next"],
        default="fixed",
        help="Use fixed visual duration or keep each visual until the next visual starts",
    )
    parser.add_argument("--docx-json", help=argparse.SUPPRESS)
    parser.add_argument("--transcript-json", help="Use existing AssemblyAI transcript JSON instead of calling ASR")
    args = parser.parse_args()

    try:
        result = run_pipeline(
            args.raw_mp4,
            docx_path=args.docx,
            docx_json_path=args.docx_json,
            transcript_json_path=args.transcript_json,
            output_dir=args.output,
            output_file=args.output_file,
            work_root=args.work_root,
            dry_run=args.dry_run,
            force=args.force,
            use_docx_images=args.use_docx_images,
            visual_duration=args.visual_duration,
            visual_duration_mode=args.visual_duration_mode,
        )
    except RenderVisualsError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


class RenderDocxVisualsError(RuntimeError):
    pass


def run_checked(cmd, cwd=ROOT, capture=True):
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture)
    if proc.returncode != 0:
        message = proc.stderr.strip() if capture else ""
        raise RenderDocxVisualsError(message or f"Command failed: {' '.join(map(str, cmd))}")
    return proc.stdout if capture else ""


def count_docx_images(docx_path):
    with zipfile.ZipFile(docx_path) as archive:
        return sum(
            1
            for name in archive.namelist()
            if (
                name.startswith("word/media/")
                and Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
            )
        )


def ffprobe_json(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd.extend(["-select_streams", stream])
    cmd.extend(["-show_entries", entries, "-of", "json", str(path)])
    return json.loads(run_checked(cmd))


def first_stream_duration(path, stream):
    data = ffprobe_json(path, "stream=duration", stream=stream)
    streams = data.get("streams") or []
    if not streams or streams[0].get("duration") is None:
        return None
    return float(streams[0]["duration"])


def validate_output(output_path):
    fmt = ffprobe_json(output_path, "format=duration,size").get("format") or {}
    duration = float(fmt["duration"])
    size = int(fmt["size"])
    video_duration = first_stream_duration(output_path, "v:0")
    audio_duration = first_stream_duration(output_path, "a:0")
    video_stream = (ffprobe_json(
        output_path,
        "stream=codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate",
        stream="v:0",
    ).get("streams") or [{}])[0]

    if video_duration is None:
        raise RenderDocxVisualsError("Output MP4 has no video stream duration")
    if abs(duration - video_duration) > 1.0:
        raise RenderDocxVisualsError(
            f"Video duration mismatch: container={duration:.3f}, video={video_duration:.3f}"
        )
    if audio_duration is not None and abs(duration - audio_duration) > 1.0:
        raise RenderDocxVisualsError(
            f"Audio duration mismatch: container={duration:.3f}, audio={audio_duration:.3f}"
        )

    return {
        "duration_sec": duration,
        "size_bytes": size,
        "video_duration_sec": video_duration,
        "audio_duration_sec": audio_duration,
        "video": video_stream,
    }


def maybe_existing_transcript(raw_mp4, docx_path):
    candidates = [
        ROOT / ".tmp" / "visuals" / raw_mp4.stem / "transcript.json",
        ROOT / ".tmp" / "visuals" / docx_path.stem / "transcript.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def render_command(args, output_path, transcript_json):
    tool = ROOT / "tools" / "render_video_visuals.py"
    base = [sys.executable, str(tool)]
    if shutil.which("uv"):
        base = ["uv", "run", "--with", "pillow", "--with", "python-docx", "python", str(tool)]

    cmd = [
        *base,
        str(args.raw_mp4),
        "--docx",
        str(args.docx),
        "--use-docx-images",
        "--visual-duration-mode",
        "until-next",
        "--output-file",
        str(output_path),
    ]
    if transcript_json:
        cmd.extend(["--transcript-json", str(transcript_json)])
    if args.force:
        cmd.append("--force")
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def main():
    parser = argparse.ArgumentParser(description="Render a raw MP4 with embedded DOCX visuals")
    parser.add_argument("raw_mp4", type=Path, help="Raw talking-head MP4")
    parser.add_argument("--docx", required=True, type=Path, help="DOCX with embedded visuals")
    parser.add_argument("--transcript-json", type=Path, help="Existing AssemblyAI transcript JSON")
    parser.add_argument("--output-file", type=Path, help="Exact output MP4 path")
    parser.add_argument("--force", action="store_true", help="Overwrite existing rendered MP4")
    parser.add_argument("--dry-run", action="store_true", help="Build plan/timeline without final FFmpeg render")
    args = parser.parse_args()

    raw_mp4 = args.raw_mp4 if args.raw_mp4.is_absolute() else ROOT / args.raw_mp4
    docx_path = args.docx if args.docx.is_absolute() else ROOT / args.docx
    args.raw_mp4 = raw_mp4
    args.docx = docx_path

    if not raw_mp4.exists():
        raise RenderDocxVisualsError(f"Raw MP4 not found: {raw_mp4}")
    if not docx_path.exists():
        raise RenderDocxVisualsError(f"DOCX not found: {docx_path}")

    image_count = count_docx_images(docx_path)
    if image_count == 0:
        raise RenderDocxVisualsError(f"DOCX has no embedded images: {docx_path}")

    output_path = args.output_file or ROOT / ".tmp" / "rendered" / f"{docx_path.stem}.mp4"
    output_path = output_path if output_path.is_absolute() else ROOT / output_path
    transcript_json = args.transcript_json or maybe_existing_transcript(raw_mp4, docx_path)
    if transcript_json and not transcript_json.is_absolute():
        transcript_json = ROOT / transcript_json

    cmd = render_command(args, output_path, transcript_json)
    stdout = run_checked(cmd)
    result = json.loads(stdout)

    validation = None
    if not args.dry_run:
        validation = validate_output(output_path)

    print(json.dumps(
        {
            "output_video": str(output_path) if not args.dry_run else None,
            "docx": str(docx_path),
            "raw_mp4": str(raw_mp4),
            "embedded_images": image_count,
            "transcript": str(transcript_json) if transcript_json else result.get("transcript"),
            "slide_plan": result.get("slide_plan"),
            "timeline": result.get("timeline"),
            "asr_matches": result.get("asr_matches"),
            "fallback_matches": result.get("fallback_matches"),
            "validation": validation,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    try:
        main()
    except (RenderDocxVisualsError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

---
name: repurpose-youtube-video
description: Use when repurposing a YouTube video into multi-platform content — user provides a YouTube URL and wants adapted posts published to Telegram channel and personal blog (with RSS syndication to Yandex Zen)
---

# Repurpose YouTube Video

## Overview

Part of the unified content pipeline (n8n + Claude Code):
1. **n8n** (automatic): Google Drive → YouTube upload + AI-thumbnail → Telegram notification with URL
2. **Claude Code** (this skill): YouTube URL → transcript → adapted texts → approval → publish to Telegram channel + blog

Takes a YouTube URL, extracts transcript via `youtube-transcript-api` (Python), adapts text for each platform using a Tone of Voice guide, publishes to Telegram channel and personal blog, and logs results.

**Express mode:** If the user provides a YouTube URL as their first message (no other context), skip the setup questions and go straight to Step 2. Read .env and tone-of-voice.md silently, auto-detect blog category from transcript content.

## Prerequisites

Before first use, the user must configure:

1. **API Keys** in `C:/Sardor/claude_space/superpower/blotato/.env`:
   - `BLOTATO_API_KEY` — from Blotato Settings > API
   - `TELEGRAM_BOT_TOKEN` — from @BotFather
   - `BLOG_API_KEY` — for veselkov.me API

2. **Tone of Voice** in `C:/Sardor/claude_space/superpower/blotato/tone-of-voice.md`:
   - User's system instruction for content style and tone

**NEVER ask the user to share API keys in chat. Always read from .env file.**

## Workflow

### Step 1: Input and Setup

1. Read `.env` from `C:/Sardor/claude_space/superpower/blotato/.env` using Read tool
2. Parse API keys (TELEGRAM_BOT_TOKEN, BLOG_API_KEY)
3. Read `tone-of-voice.md` from same directory
4. **Get YouTube URL:** If user already provided URL in their message, use it. Otherwise ask via AskUserQuestion.
5. **Auto-detect blog category** from transcript content after Step 2:
   - Keywords about strategy, management, operations, TOC → Управление (parent=32)
   - Keywords about marketing, sales, promotion → Маркетинг (parent=29)
   - Keywords about business, entrepreneurship, finance → Бизнес (parent=34)
   - If uncertain, ask the user. Show detected category with option to override.

```
Категории блога:
- Бизнес (parent=34)
- Маркетинг (parent=29)
- Управление (parent=32)
- Свой ID (пользователь указывает)
```

### Step 2: Extract YouTube Transcript

**Extract video ID** from URL (e.g., `dQw4w9WgXcQ` from `https://www.youtube.com/watch?v=dQw4w9WgXcQ`).

**Get transcript via Python (youtube-transcript-api v1.2+):**
```bash
python -c "
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from youtube_transcript_api import YouTubeTranscriptApi
api = YouTubeTranscriptApi()
transcript = api.fetch('VIDEO_ID_HERE', languages=['ru', 'en'])
text = ' '.join([entry.text for entry in transcript])
print(text)
"
```

**Get video title via page scrape:**
```bash
curl -s "https://www.youtube.com/watch?v=VIDEO_ID_HERE" | python -c "
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
html = sys.stdin.read()
match = re.search(r'<title>(.*?)</title>', html)
if match:
    title = match.group(1).replace(' - YouTube', '').strip()
    print(title)
"
```

**IMPORTANT (Windows):** Always set `sys.stdout` to UTF-8 encoding to avoid `cp1251` errors with Cyrillic text.

- If Russian transcript unavailable, try `languages=['en']` and note that translation may be needed
- If no transcript at all: report to user, ask them to provide content manually
- Result: `title` (video title) and `content` (full transcript text)

### Step 3: Visuals (handled by n8n)

**YouTube thumbnail is generated automatically by n8n** when video is uploaded from Google Drive. This skill does NOT generate visuals.

If the user explicitly asks for additional visuals (e.g., blog banner), you can generate them via Blotato API if `BLOTATO_API_KEY` is configured in `.env`. Otherwise, skip this step entirely.

### Step 4: Adapt Content for Each Platform

Using the extracted `title` and `content` from Step 2, and the tone-of-voice.md guidelines, generate:

**Telegram post:**
- Short, engaging, with key takeaways
- Include link to original YouTube video
- Max 1024 characters (sendPhoto caption limit)
- Use HTML formatting (`<b>`, `<i>`, `<a>`)
- If text exceeds 1024 chars, split: send image first, then text via sendMessage (up to 4096 chars)

**Blog article (HTML) — Дзен-совместимый контент:**
- Full-length article with `<h2>` headings
- Intro paragraph, 3-5 key points, conclusion
- **YouTube video as plain link, NOT iframe:** `https://www.youtube.com/watch?v=VIDEO_ID` (Дзен auto-converts to widget)
- **Allowed HTML tags only:** p, a, b, i, u, s, h1-h4, blockquote, ul/li, ol/li, figure, img, br
- **Forbidden tags:** iframe, div, span, table, script, style, form, section, article
- Content must be ≥300 characters of plain text (without tags)
- SEO meta description (150-160 chars) — also used as RSS `description` for Дзен card
- URL alias: transliterate Russian title to latin, lowercase, hyphens, no special chars
- This article syndicates to Yandex Zen via RSS at `/in/feed.xml`

**Show both texts to user for review via AskUserQuestion before publishing.**

**Compact preview for mobile:** When showing texts for approval, use a concise format:
- Telegram: show full text (it's already short)
- Blog: show title + first paragraph + "... (ещё N абзацев)" + category
- One-button approval: "Публикуем оба? [OK / Изменить / Отмена]"

### Step 5: Publish to Telegram

**Send photo with caption:**
```bash
curl -s -X POST "https://api.telegram.org/botTELEGRAM_BOT_TOKEN_VALUE/sendPhoto" \
  -F "chat_id=-1001972632255" \
  -F "photo=IMAGE_URL_HERE" \
  -F "caption=TELEGRAM_TEXT_HERE" \
  -F "parse_mode=HTML"
```

**Fallback if image fails — send text only:**
```bash
curl -s -X POST "https://api.telegram.org/botTELEGRAM_BOT_TOKEN_VALUE/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "-1001972632255",
    "text": "TELEGRAM_TEXT_HERE",
    "parse_mode": "HTML"
  }'
```

Check response for `"ok": true`. Report result to user.

### Step 6: Publish to Blog

```bash
curl -s -X POST "https://veselkov.me/api-publish.html" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: BLOG_API_KEY_VALUE" \
  -d '{
    "pagetitle": "ARTICLE_TITLE",
    "longtitle": "EXTENDED_TITLE",
    "introtext": "ANNOTATION_TEXT",
    "content": "FULL_HTML_ARTICLE_BODY",
    "description": "SEO_META_DESCRIPTION",
    "alias": "url-slug-here",
    "parent": CATEGORY_ID,
    "template": 8,
    "published": 1
  }'
```

- Success (HTTP 201): response contains `url` field with published article URL
- Error: response contains `error` and `details` fields
- `published: 0` creates draft, `1` publishes immediately

**CRITICAL — API behaviour:**
- The API **always creates a new resource** — it does NOT update existing ones. Passing `id` is ignored. Never call this endpoint twice for the same article.
- Resources are created as **msProduct** (miniShop2), not regular MODX documents. If the resource type is wrong, it won't appear on the main page and will show `[msOptions] The resource with id = N is not instance of msProduct` error at the bottom of the post. This is a server-side configuration issue — report to user, do not attempt to re-publish.
- URL pattern for published articles: `https://veselkov.me/in/CATEGORY-ALIAS/ARTICLE-ALIAS.html`

**After blog publish:** Article appears on veselkov.me and becomes available via RSS feed → Yandex Zen picks it up automatically (moderation may apply).

### Step 7: Log Results

Append a row to `publish-log.md` (in the project directory):

```
| YYYY-MM-DD | https://youtube.com/... | ✅ Telegram msg_id | ✅ https://veselkov.me/in/... |
```

Use ✅ for success, ❌ for failure. Include error details if failed.

**Report final summary to user** with links to all published content. Keep it compact:
```
Готово!
📺 YouTube: [url]
💬 Telegram: ✅ msg_id [N]
📝 Блог: [url]
📡 RSS/Дзен: автоматически
```

## API Quick Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `youtube-transcript-api` (Python) | — | Extract YouTube transcript locally |
| `api.telegram.org/bot.../sendPhoto` | POST | Send photo+caption to Telegram |
| `api.telegram.org/bot.../sendMessage` | POST | Send text to Telegram (fallback) |
| `veselkov.me/api-publish.html` | POST | Publish article to blog |

## Error Handling

| Error | Action |
|-------|--------|
| Transcript not available (no subtitles) | Report to user, ask them to provide content manually |
| Visual generation failed | Visuals handled by n8n — skip in this skill |
| Telegram send failed | Show error, ask user to verify bot token and channel permissions |
| Blog publish failed | Show error details, ask user to verify API key and endpoint |
| .env file missing or keys empty | Stop immediately, instruct user to fill in .env |
| tone-of-voice.md empty/default | Warn user, proceed with neutral professional tone |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Telegram caption > 1024 chars | Split into sendPhoto (image) + sendMessage (text) |
| Not escaping HTML in Telegram text | Use only `<b>`, `<i>`, `<a>`, `<code>`, `<pre>` tags |
| Sharing API keys in chat | NEVER. Always read from .env file |
| Shell state assumptions | Each Bash call is independent — re-read credentials every time |
| Calling blog API twice to "update" a resource | API has no update — every POST creates a NEW resource. On error, report to user; never retry with same content. |
| Post not on main page / msOptions error | Resource created as MODX Document instead of msProduct — server config issue, report to user to fix in MODX Admin (Resource type → "Товар магазина") |

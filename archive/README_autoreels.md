# AutoReels

Automated AI marketing reel generator. Creates short-form vertical videos (480×832) with AI-generated video clips, branded text slides, narration, background music, and subtitles — then posts them for review via Discord and publishes to Facebook and Instagram.

## Architecture

```
Theme Selection
      │
      ▼
Groq LLM (Creative Director)
      │  Generates multi-segment storyboard (JSON)
      ▼
Segment Execution
  ├── AI Video Clips  →  Modal H100 GPU (Wan2.1-T2V-14B)
  ├── Text Slides     →  Pillow rendering + Unsplash backgrounds
  ├── Title Cards     →  Branded intro frames
  └── CTA Slides      →  Call-to-action with app branding
      │
      ▼
Compositing & Transitions (crossfade, fade, wipe)
      │
      ▼
Audio Pipeline
  ├── Narration  →  edge-tts (10-voice pool)
  ├── Music      →  Freesound API (mood-based)
  └── Subtitles  →  ASS format, burned in via ffmpeg
      │
      ▼
Discord Bot (review: approve / edit / delete / save clips)
      │
      ▼
Publish → Facebook Pages + Instagram Reels
```

## Prerequisites

- **Python 3.11+**
- **ffmpeg** on PATH (for audio muxing and subtitle burn-in)
- **Modal account** with CLI configured (`modal setup`)
- No local GPU required — video generation runs on Modal's H100 GPUs

## Setup

### 1. Clone and create virtual environment

```bash
git clone <repo-url> && cd autoreels
python -m venv venv
```

Activate the virtual environment:

```powershell
# Windows
.\venv\Scripts\Activate.ps1

# Linux/macOS
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** PyTorch with CUDA is listed separately — follow [pytorch.org](https://pytorch.org/get-started/locally/) for your platform if you need local torch (not required for Modal-only usage).

### 3. Deploy the video generation model to Modal

```bash
modal deploy modal_app.py
```

This builds a container image with Wan2.1-T2V-14B pre-cached and deploys it as a serverless GPU endpoint (H100 80GB).

### 4. Configure environment variables

Create a `.env.local` file in the project root:

```env
# Discord
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_REVIEW_CHANNEL_ID=your_channel_id

# Meta (Facebook + Instagram publishing)
META_PAGE_ACCESS_TOKEN=your_page_access_token
META_PAGE_ID=your_page_id
META_IG_ACCOUNT_ID=your_instagram_account_id

# Groq (LLM creative director)
GROQ_API_KEY=your_groq_api_key

# Audio
FREESOUND_API_KEY=your_freesound_api_key

# Images (Unsplash backgrounds for text slides)
UNSPLASH_ACCESS_KEY=your_unsplash_access_key
```

### 5. Configure settings

Global settings live in `config/settings.yaml`:

| Section | Key Settings |
|---------|-------------|
| `video` | `width: 480`, `height: 832`, `fps: 16`, `num_inference_steps: 35`, `guidance_scale: 7.0` |
| `director` | `reel_duration_min: 15`, `reel_duration_max: 30` (seconds) |
| `model` | `backend: modal` |
| `groq` | `model: llama-3.3-70b-versatile`, `max_tokens: 2048` |
| `audio` | `music_volume_db: -8`, `duck_music_db: -6`, `voice: random` |
| `schedule` | `times: ["08:00", "14:00", "20:00"]`, `timezone: America/New_York` |

## Campaign Configuration

Each campaign is a YAML file in `config/campaigns/`. See `config/campaigns/matra.yaml` for a full example.

A campaign defines:

```yaml
name: "YourApp"
tagline: "Your tagline here"
description: >
  A description of the product for the AI director to reference.

brand:
  colors:
    primary: "#f7f2ea"      # Background color
    secondary: "#1a1a1a"    # Text color
    accent: "#C49A3C"       # Highlight color
  logo: "assets/yourapp/logo.png"
  font: "assets/fonts/YourFont.ttf"

social:
  facebook_page_name: "YourPage"
  instagram_handle: "yourhandle"
  hashtags:
    - "#YourHashtag"

themes:
  - name: "Theme Name"
    mood: "ambient"           # Music mood (ambient, cinematic, upbeat, etc.)
    prompt_template: >
      60-90 word visual description for AI video generation...

text_overlays:
  cta_lines:
    - "Your call to action text"
  hashtag_sets:
    - "#Tag1 #Tag2 #Tag3"

assets:
  chair: "assets/yourapp/chair.png"   # Decorative stickers/overlays
```

### Themes

Themes rotate automatically to avoid repetition. Each theme provides:
- A `mood` for Freesound music selection (ambient, cinematic, upbeat, dramatic, etc.)
- A `prompt_template` — a dense visual description that the AI director adapts into per-segment video prompts

### Assets

Place brand assets under `assets/<campaign>/`. The AI director can reference named assets to overlay decorative PNG stickers on text slides.

## CLI Commands

All commands are run via `python run.py <command>`.

### Generate a single reel

```bash
python run.py generate <campaign>
```

| Flag | Effect |
|------|--------|
| `--no-discord` | Generate without posting to Discord |
| `--no-groq` | Use base theme prompts instead of Groq storyboard |
| `--skip-ai` | Replace AI video with solid-color placeholders (fast testing) |

### Generate a batch

```bash
python run.py batch <campaign> --count 5
```

Same flags as `generate`. Produces multiple reels sequentially.

### Run the Discord review bot

```bash
python run.py bot
```

Starts the Discord bot for reviewing previously generated reels. Each reel is posted with four buttons:

- **✅ Approve** — publishes to Facebook + Instagram with auto-generated caption and hashtags
- **🗑️ Delete** — removes the reel and its media files
- **✏️ Edit** — opens a modal to re-generate a specific segment (video prompt, text, title, or CTA)
- **💾 Save Clips** — saves selected AI video clips to the reusable clip library

### Run scheduler + bot together

```bash
python run.py schedule <campaign>
```

Starts the APScheduler for automatic generation at configured times (e.g., 08:00, 14:00, 20:00) and the Discord bot simultaneously.

### Check today's status

```bash
python run.py status <campaign>
```

Shows each reel's theme, generation status, and attempt count for the current day.

### Browse clip library

```bash
python run.py library [campaign] --search "keyword"
```

Lists saved AI video clips from previous reels. Clips can be reused in future storyboards.

## How It Works

### 1. Storyboard Generation

The Groq LLM (llama-3.3-70b-versatile) acts as a creative director. Given the campaign's brand, themes, and product description, it produces a JSON storyboard with 4–6 segments:

- **`title_card`** — branded intro with title and subtitle
- **`video_clip`** — 5-second AI-generated video from a text prompt
- **`text_slide`** — text overlay with optional Unsplash background image
- **`cta_slide`** — closing call-to-action

Each segment specifies duration, content, narration text, and transition type.

### 2. Video Generation

Video clips are rendered on Modal's H100 GPUs using the Wan2.1-T2V-14B model. The model generates 5-second clips at 480×832 (portrait) from text prompts with 35 inference steps.

Generated frames are cached as `.npz` files so that editing a single segment doesn't require re-generating the others.

### 3. Visual Rendering

Text slides, title cards, and CTAs are rendered locally via Pillow with the campaign's brand palette and fonts. Four visual styles rotate automatically:

| Style | Title Size | Tagline Size |
|-------|-----------|-------------|
| Classic | 64px | 40px |
| Bold | 72px | 38px |
| Minimal | 56px | 38px |
| Cinematic | 68px | 36px |

Text slides can have Unsplash photo backgrounds (with brand-tinted overlay) and decorative PNG asset overlays.

### 4. Audio Pipeline

The audio pipeline runs after compositing:

1. **Narration** — edge-tts generates speech from each segment's narration text, selecting from a pool of 10 voices (randomized per reel)
2. **Music** — Freesound API fetches mood-matched background music, cached locally
3. **Mixing** — pydub handles audio mixing with automatic ducking (music volume drops during narration)
4. **Subtitles** — ASS-format subtitles are generated and burned in via ffmpeg
5. **Muxing** — final ffmpeg pass combines video + mixed audio + subtitles

### 5. Review & Publishing

Generated reels are posted to a Discord channel with a preview video and segment summary. Reviewers can approve (auto-publishes to Facebook + Instagram), edit individual segments, delete, or save clips for reuse.

## Project Structure

```
autoreels/
├── run.py                  # Entry point
├── modal_app.py            # Modal GPU deployment (Wan2.1-T2V-14B)
├── requirements.txt
├── .env.local              # API keys and secrets (gitignored)
│
├── config/
│   ├── settings.yaml       # Global settings
│   └── campaigns/
│       └── matra.yaml      # Campaign config
│
├── src/
│   ├── cli.py              # Click CLI (generate, batch, bot, schedule, status, library)
│   ├── director.py         # Groq storyboard creation + execution engine
│   ├── creative.py         # Pillow-based frame rendering (text slides, titles, CTAs)
│   ├── video_gen.py        # Modal remote video generation client
│   ├── audio.py            # TTS, music, mixing, subtitles, muxing
│   ├── images.py           # Unsplash search + download + caching
│   ├── discord_bot.py      # Discord review bot with interactive buttons/modals
│   ├── campaign.py         # Config loader (YAML + env vars)
│   ├── post_process.py     # Video post-processing
│   ├── tracker.py          # SQLite database for reel tracking
│   ├── scheduler.py        # APScheduler wrapper for daily automation
│   └── prompter.py         # Prompt formatting utilities
│
├── assets/
│   ├── fonts/              # Poppins font family
│   ├── matra/              # Campaign-specific assets (logo, stickers)
│   └── music/              # Local music fallbacks
│
├── cache/                  # Auto-created runtime caches
│   └── images/             # Unsplash image cache
│
└── output/                 # Generated reels (gitignored)
    └── <campaign>/<date>/  # Daily output directories
```

## Quick Start

```bash
# 1. Setup
python -m venv venv && .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
modal deploy modal_app.py

# 2. Configure .env.local with your API keys

# 3. Test with skip-ai mode (no GPU needed)
python run.py generate matra --skip-ai --no-discord

# 4. Generate a real reel
python run.py generate matra

# 5. Run the Discord bot to review
python run.py bot
```

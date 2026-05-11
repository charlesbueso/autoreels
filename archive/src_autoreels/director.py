"""Director — Groq-powered creative director that orchestrates full reels.

Groq receives the campaign theme/brand and returns a JSON storyboard.
The Director executes each segment: AI video clips (via Modal) or
creative-coded segments (text slides, transitions, overlays).
The final reel is 15-30 seconds of professional, composed content.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from .creative import (
    render_text_slide,
    render_title_card,
    render_cta_slide,
    render_placeholder_clip,
    video_to_frames,
    frames_to_video,
    apply_crossfade,
    apply_fade_from_black,
    apply_fade_to_black,
    apply_wipe,
    add_text_overlay_to_frames,
    _darken_hex,
)
from .images import search_and_download, load_image
from .video_gen import generate_clip

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reel style variety — each reel picks a random visual style so reels
# don't all look identical (avoids platform automated-content flags).
# ---------------------------------------------------------------------------

REEL_STYLES = [
    {
        "name": "classic",
        "title_size": 64, "subtitle_size": 36,
        "text_size_large": 68, "text_size_medium": 56,
        "cta_size": 56, "tagline_size": 40,
        "overlay_size": 44,
        "dividers": True,
        "transition_duration": 0.5,
    },
    {
        "name": "bold",
        "title_size": 72, "subtitle_size": 32,
        "text_size_large": 76, "text_size_medium": 60,
        "cta_size": 64, "tagline_size": 38,
        "overlay_size": 48,
        "dividers": True,
        "transition_duration": 0.4,
    },
    {
        "name": "minimal",
        "title_size": 56, "subtitle_size": 34,
        "text_size_large": 60, "text_size_medium": 50,
        "cta_size": 52, "tagline_size": 38,
        "overlay_size": 40,
        "dividers": False,
        "transition_duration": 0.6,
    },
    {
        "name": "cinematic",
        "title_size": 68, "subtitle_size": 30,
        "text_size_large": 64, "text_size_medium": 54,
        "cta_size": 58, "tagline_size": 36,
        "overlay_size": 46,
        "dividers": True,
        "transition_duration": 0.7,
    },
]


def _pick_reel_style() -> dict:
    """Pick a random visual style for this reel."""
    style = random.choice(REEL_STYLES)
    logger.info("Reel visual style: %s", style["name"])
    return style

# ---------------------------------------------------------------------------
# Storyboard schema — what Groq must return
# ---------------------------------------------------------------------------

STORYBOARD_SCHEMA = """\
You must return a JSON object with this exact structure:
{
  "title": "Short reel title for internal tracking",
  "music_mood": "warm" | "melancholic" | "nostalgic" | "hopeful" | "gentle" | "upbeat" | "reflective" | "cinematic",
  "total_duration": <number 20-30>,
  "segments": [
    {
      "type": "title_card" | "video_clip" | "text_slide" | "cta_slide",
      "duration": <seconds, number>,
      "transition_in": "fade" | "crossfade" | "wipe_left" | "wipe_up" | "none",
      ... segment-specific fields below ...
    }
  ]
}

Segment types and their fields:

1. "title_card" — animated branded intro card (duration: 2.5-3s)
   - "title": string (short, punchy, 2-4 words)
   - "subtitle": string (brand tagline or context)
   - "bg_style": "gradient" | "solid"
   - "animation": "slide_up" | "fade_in" | "bounce"
   - "narration": string or null (voiceover text for this segment, or null if none)

2. "video_clip" — AI-generated video via Wan2.1 (duration: exactly 5s)
   - "prompt": string (60-90 words, dense cinematic description — SILENT video only, NEVER mention audio/sound/music/voices)
   - "text_overlay": string or null (short text to overlay on the video)
   - "overlay_animation": "fade_in_out" | "slide_up" | "typewriter" | "word_by_word" | null
   - "overlay_position": "top" | "center" | "bottom" | null
   - "narration": string or null (voiceover text for this segment, or null if none)

3. "text_slide" — animated text on branded background (duration: 3.5-5s)
   - "text": string (the message to display, 5-12 words)
   - "animation": "fade_in_out" | "slide_up" | "slide_left" | "typewriter" | "word_by_word" | "bounce"
   - "bg_style": "gradient" | "solid"
   - "font_size": "large" | "medium" (use large for short text, medium for longer)
   - "position": "center" | "top" | "bottom"
   - "particles": false
   - "bg_image_query": string or null (Unsplash search query for a background photo, e.g. "elderly couple golden hour", "vintage family photo album". Use null for plain branded background)
   - "asset": string or null (name of a decorative asset to place on the slide, e.g. "chair". Use null for no asset)
   - "asset_position": "bottom_right" | "bottom_left" | "bottom_center" | "top_right" | "top_left" | null
   - "narration": string or null (voiceover text for this segment, or null if none)

4. "cta_slide" — call-to-action closing card (duration: 4-5s)
   - "cta_text": string (the CTA message)
   - "tagline": string (brand tagline below CTA)
   - "particles": false
   - "narration": string or null (voiceover text for this segment, or null if none)
"""

DIRECTOR_SYSTEM_PROMPT = """\
You are a creative director for short-form vertical video reels (9:16 aspect ratio).
You produce structured JSON storyboards that will be executed by a production pipeline.

The pipeline has two tools:
1. **Wan2.1 AI Video** — generates 5-second cinematic video clips from text prompts.
   These are photorealistic, cinematic clips. Prompts must be 60-90 words,
   densely packed with visual detail (camera angle, lighting, textures, colors, depth of field).
   NEVER include text, words, logos, UI elements in video prompts — the AI model cannot render text.

2. **Creative Engine** — generates animated text slides, title cards, and CTA screens
   with elegant typography on clean backgrounds.

3. **Unsplash Images** — fetches high-quality photos for text slide backgrounds.
   When you set "bg_image_query" on a text_slide, the pipeline searches Unsplash
   for that query and composites the photo behind the text with a branded tint overlay.
   This makes text slides visually rich instead of plain solid backgrounds.

4. **Decorative Assets** — small PNG stickers/icons that can be placed on text slides.
   Available assets: {available_assets}
   Set "asset" to an asset name and "asset_position" to place it on the slide.
   Great for adding brand personality — e.g. a small chair icon in the corner.

AUDIO RULES (CRITICAL):
- The AI video model generates SILENT video only — NEVER reference audio, sounds, music, voices, or speaking in video_clip prompts.
- Video prompts must describe ONLY visual content: scenes, camera angles, lighting, colors, textures.
- Narration is handled separately by a TTS engine — use the "narration" field for voiceover text.

NARRATION RULES (IMPORTANT — READ CAREFULLY):
- The reel should feel like someone is TELLING A STORY over the visuals, not just adding captions.
- EVERY segment should have narration (non-null) — the voiceover should flow like a continuous story across the entire reel.
- The narration across all segments should form one cohesive mini-narrative, not disconnected sentences.
- Narration should complement (not repeat) the on-screen text. Add depth, context, or emotion that the text alone can't.
- Each segment's narration: 1-2 warm, conversational sentences. Imagine a friend sharing something meaningful.
- For title_card: a short hook or intriguing opening line that draws the viewer in.
- For video_clips: describe what the viewer is seeing emotionally — the FEELING, not the visual.
- For text_slides: expand on the text with personal context or a gentle reflection.
- For cta_slide: a warm, personal closing — like "Try Matra. Your family's stories are worth remembering."
- Vary the narration tone across the reel — don't make every line sound the same.
- Example flow: "What if you forgot?" → "She used to tell this story every Thanksgiving..." → "Now her voice lives in Matra" → "One conversation. That's all it takes."

MUSIC MOOD (REQUIRED):
- Set "music_mood" at the top level of the storyboard JSON — it determines the background music style.
- Choose the mood that best matches the emotional tone of the reel's content.
- Options: "warm", "melancholic", "nostalgic", "hopeful", "gentle", "upbeat", "reflective", "cinematic".
- Family memory themes → "nostalgic" or "warm". Loss/urgency → "melancholic". CTA-heavy → "hopeful" or "upbeat".

REEL BEST PRACTICES (FOLLOW THESE):
- The FIRST 1-2 SECONDS must visually hook the viewer — the title card is the hook
- Keep text BIG and READABLE — viewers watch on phones, use "medium" or "large" font sizes
- Don't cram too many segments — 5-6 segments max for a 20-25s reel
- Let text BREATHE — each text slide needs enough time to read comfortably
- End with a clear, warm call-to-action that tells people what to do
- Pacing: hook fast, slow down for emotion, then close strong

IMAGE RULES (IMPORTANT):
- Use "bg_image_query" on SOME text_slides (not all) to add visual richness. Mix plain and image backgrounds.
- At least ONE text_slide in the reel MUST have a bg_image_query — plain-only reels look empty and repetitive.
- Image queries should be evocative and cinematic — "grandmother hands knitting warm light", not "family".
- Keep queries specific (3-6 words) and visually descriptive. Think like a photographer.
- Use images that match the emotional tone: warm/nostalgic for family moments, gentle/calm for reflective text.
- If the reel has 2+ text_slides, at least one should have an image and at least one should be plain — contrast creates rhythm.
- If the reel has only 1 text_slide, give it a bg_image_query to make it visually interesting.
- Assets (decorative stickers) are optional — use sparingly (0-1 per reel) for brand personality.
- An asset works best on a plain text_slide (no bg_image) to fill visual space.
- If using an asset, place it at "bottom_right" or "bottom_left" to not compete with text.

DURATION RULES (STRICT MINIMUMS):
- title_card: 2.5-3 seconds (must be readable!)
- text_slide: 3.5-5 seconds (people need time to READ)
- video_clip: exactly 5 seconds (fixed by AI video model)
- cta_slide: 4-5 seconds (needs time for CTA + tagline + logo fade-in)
- Total reel: 20-30 seconds

STRUCTURE RULES:
- Every reel MUST start with a title_card and end with a cta_slide
- Use 2-3 video_clips as the visual backbone
- Alternate between video clips and text slides for rhythm and pacing
- Use transitions: "crossfade" between video+text, "fade" for bookends
- Video prompts must NEVER contain text, words, logos, or UI — only visual scenes
- Text messages go in text_slides and overlays, NOT in video prompts
- Return ONLY valid JSON, no explanation or markdown

VARIETY RULES (CRITICAL — each reel must feel unique):
- NEVER use the same segment structure twice in a row. Mix up the order.
- Vary segment counts: some reels with 4 segments, others with 6. Don't default to 5 every time.
- Vary transitions: use a MIX of crossfade, fade, wipe_left, wipe_up, and none. Don't use the same transition for every segment.
- Vary text animations: NEVER use the same animation for all text_slides. Pick different ones (slide_up, typewriter, word_by_word, bounce, slide_left, fade_in_out).
- Vary text positions: use "top" or "bottom" for at least one text_slide — not always "center".
- Vary bg_style: mix "gradient" and "solid" within the same reel.
- Vary font_size: use "large" for punchy lines, "medium" for longer ones — don't default to one.
- Vary title_card animations: alternate between "slide_up", "fade_in", and "bounce".
- Sometimes use text_overlay on video_clips, sometimes don't. Don't always overlay.
- The goal is that every reel feels hand-crafted and different, not templated.

COPY RULES — THIS IS CRITICAL:
- Write text_slide copy like a real human, not a marketer. No generic ad-speak.
- Use conversational, emotionally specific language. Think poet, not copywriter.
- Instead of "Preserve Your Legacy" → "She told me how they met. I almost forgot to ask."
- Instead of "Record Family Stories" → "That recipe she never wrote down? It starts with a story."
- title_card titles should be 2-4 words max. Intriguing, not descriptive.
- text_slide messages should be 5-12 words. Specific, emotional, human.
- CTA text should be warm and personal, not corporate.
- The tagline field MUST always be EXACTLY: "Download Now\nAvailable on Android & iOS"
  This is a fixed two-line tagline — do NOT change or rephrase it. Copy it verbatim.
  The cta_text can be creative and emotional, but the tagline is always that exact string.
- NEVER use: "Preserve", "Legacy", "Heritage", "Unlock", "Discover", "Empower".
- DO use: specific family moments, sensory details, conversational tone, gentle urgency.
- Every line should make someone pause and think about their own family.

{schema}
"""


def _font_size_to_px(size_name: str, style: dict | None = None) -> int:
    if style:
        return {"large": style["text_size_large"], "medium": style["text_size_medium"], "small": 48}.get(size_name, style["text_size_medium"])
    return {"large": 68, "medium": 56, "small": 48}.get(size_name, 56)


_ROOT = Path(__file__).resolve().parent.parent


async def _resolve_bg_image(
    seg: dict,
    settings: dict[str, Any],
    width: int,
    height: int,
):
    """Fetch a background image for a text_slide if bg_image_query is set.

    Returns a PIL Image or None.
    """
    from PIL import Image as PILImage

    query = seg.get("bg_image_query")
    if not query:
        return None
    api_key = settings.get("unsplash", {}).get("access_key", "")
    if not api_key:
        logger.warning("No UNSPLASH_ACCESS_KEY set — skipping bg image for '%s'", query)
        return None
    path = await search_and_download(query, api_key, width=width, height=height)
    if path and path.exists():
        logger.info("Background image loaded for '%s'", query)
        return PILImage.open(path).convert("RGBA")
    return None


def _resolve_asset(
    seg: dict,
    campaign: dict[str, Any],
    max_w: int,
    max_h: int,
):
    """Load an asset image if the segment specifies one.

    Looks up asset name in campaign["assets"] mapping.
    Returns a PIL Image or None.
    """
    asset_name = seg.get("asset")
    if not asset_name:
        return None
    assets_map = campaign.get("assets", {})
    asset_path = assets_map.get(asset_name)
    if not asset_path:
        logger.warning("Asset '%s' not found in campaign config", asset_name)
        return None
    return load_image(asset_path, max_w, max_h)


async def _call_groq(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = "llama-3.3-70b-versatile",
    max_tokens: int = 2048,
) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0.85,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def _parse_storyboard(raw: str) -> dict:
    """Extract JSON from Groq response, handling markdown code fences."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


async def create_storyboard(
    theme: dict,
    campaign: dict[str, Any],
    settings: dict[str, Any],
) -> dict:
    """Ask Groq to create a storyboard for a reel based on a theme."""
    api_key = settings.get("groq", {}).get("api_key", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY required for director mode")

    groq_cfg = settings.get("groq", {})
    brand = campaign.get("brand", {})
    colors = brand.get("colors", {})
    overlays = campaign.get("text_overlays", {})
    cta_lines = overlays.get("cta_lines", [])
    hashtag_sets = overlays.get("hashtag_sets", [])

    # Gather available asset names from campaign config
    asset_names = list(campaign.get("assets", {}).keys())
    assets_str = ", ".join(f'"{a}"' for a in asset_names) if asset_names else "none configured"

    system = DIRECTOR_SYSTEM_PROMPT.format(
        schema=STORYBOARD_SCHEMA,
        available_assets=assets_str,
    )

    # Pick variety hints — tell Groq which animation/transition style to lean toward
    anim_pool = ["fade_in_out", "slide_up", "slide_left", "typewriter", "word_by_word", "bounce"]
    transition_pool = ["crossfade", "fade", "wipe_left", "wipe_up", "none"]
    preferred_anims = random.sample(anim_pool, k=min(3, len(anim_pool)))
    preferred_transitions = random.sample(transition_pool, k=min(3, len(transition_pool)))
    segment_count_hint = random.choice([4, 5, 5, 6])

    user_prompt = (
        f"BRAND: {campaign.get('name', 'Brand')}\n"
        f"TAGLINE: {campaign.get('tagline', '')}\n"
        f"DESCRIPTION: {campaign.get('description', '')}\n"
        f"COLORS: primary={colors.get('primary', '#000')}, "
        f"secondary={colors.get('secondary', '#fff')}, "
        f"accent={colors.get('accent', '#gold')}\n\n"
        f"APP FEATURES (use these as content ideas — mention specific features naturally):\n"
        f"- Record family stories through guided voice interviews with AI prompts\n"
        f"- Auto-generate beautiful Memory Books from recorded stories (printable keepsakes)\n"
        f"- AI-written family Stories — turns raw interviews into polished narratives\n"
        f"- Family Tree Graph — visual interactive family tree built from your stories\n"
        f"- Voice preservation — keep loved ones' voices forever, hear them anytime\n"
        f"- AI-powered question prompts that draw out stories people forgot they had\n"
        f"- Share stories with family members across generations\n"
        f"- Available on Android & iOS\n\n"
        f"THEME: {theme['name']}\n"
        f"MOOD: {theme.get('mood', 'cinematic')}\n"
        f"BASE CONCEPT: {theme['prompt_template'].strip()}\n\n"
        f"SAMPLE CTA LINES (pick or adapt one):\n"
        + "\n".join(f"- {c}" for c in cta_lines[:5])
        + "\n\n"
        f"VARIETY HINTS FOR THIS REEL (follow these for uniqueness):\n"
        f"- Use approximately {segment_count_hint} segments total\n"
        f"- Preferred text animations: {', '.join(preferred_anims)}\n"
        f"- Preferred transitions: {', '.join(preferred_transitions)}\n"
        f"- Title card animation: {random.choice(['slide_up', 'fade_in', 'bounce'])}\n\n"
        f"Create a 22-28 second reel storyboard. "
        f"The title card is the HOOK — make it visually arresting in the first 1-2 seconds. "
        f"Give text slides AT LEAST 3.5 seconds so people can actually read them. "
        f"Write ALL text copy like a thoughtful human — specific, emotional, conversational. "
        f"Avoid generic marketing language. Think of the exact moment someone realizes "
        f"they should have recorded grandma's stories sooner. That feeling — put it in words. "
        f"Naturally weave in 1-2 specific app features (memory books, family tree, voice preservation, etc.) — "
        f"don't list features, make them part of the emotional story. "
        f"Video prompts should be vivid and cinematic. "
        f"Use 'large' font_size for text slides with 5-7 words, 'medium' for 8-12 words. "
        f"Return ONLY the JSON storyboard."
    )

    logger.info("Asking Groq to direct reel for theme: %s", theme["name"])
    start = time.time()
    raw = await _call_groq(
        system, user_prompt, api_key,
        model=groq_cfg.get("model", "llama-3.3-70b-versatile"),
        max_tokens=2048,
    )
    elapsed = time.time() - start
    logger.info("Groq storyboard received in %.1fs", elapsed)

    storyboard = _parse_storyboard(raw)

    # Validate basic structure
    if "segments" not in storyboard:
        raise ValueError("Storyboard missing 'segments' key")
    if not storyboard["segments"]:
        raise ValueError("Storyboard has no segments")

    # Enforce minimum durations so text is always readable
    _MIN_DURATIONS = {
        "title_card": 2.5,
        "text_slide": 3.5,
        "cta_slide": 4.0,
        "video_clip": 5.0,
    }
    for seg in storyboard["segments"]:
        seg_type = seg.get("type", "")
        min_dur = _MIN_DURATIONS.get(seg_type, 2.0)
        if seg.get("duration", 0) < min_dur:
            logger.info(
                "Clamping %s duration from %.1fs to %.1fs",
                seg_type, seg.get("duration", 0), min_dur,
            )
            seg["duration"] = min_dur

    logger.info(
        "Storyboard: %d segments, ~%ds total",
        len(storyboard["segments"]),
        sum(s.get("duration", 0) for s in storyboard["segments"]),
    )
    return storyboard


async def execute_storyboard(
    storyboard: dict,
    output_dir: Path,
    reel_id: str,
    campaign: dict[str, Any],
    settings: dict[str, Any],
    *,
    skip_ai: bool = False,
) -> Path:
    """Execute a storyboard: render each segment, apply transitions, export final MP4.

    If skip_ai=True, video_clip segments are rendered as black placeholders
    showing the prompt text — useful for quickly previewing storyboard flow.
    """
    video_cfg = settings.get("video", {})
    width = video_cfg.get("width", 480)
    height = video_cfg.get("height", 832)
    fps = video_cfg.get("fps", 16)
    crf = video_cfg.get("crf", 23)

    brand = campaign.get("brand", {})
    colors = brand.get("colors", {})
    primary = colors.get("primary", "#f7f2ea")    # cream (backgrounds)
    secondary = colors.get("secondary", "#1a1a1a")  # black (text)
    accent = colors.get("accent", "#C49A3C")       # gold (highlights)
    green = colors.get("green", "#16431c")          # sparingly
    font_path = brand.get("font")
    font_bold_path = brand.get("font_bold")
    logo_path = brand.get("logo")

    # Pick a random visual style for this reel (variety)
    style = _pick_reel_style()
    # Persist style name in storyboard so edits keep the same look
    storyboard["_reel_style"] = style["name"]
    storyboard["_skip_ai"] = skip_ai

    segments = storyboard["segments"]
    rendered_segments: list[list[np.ndarray]] = []

    for i, seg in enumerate(segments):
        seg_type = seg["type"]
        duration = seg.get("duration", 3)
        logger.info("Rendering segment %d/%d: %s (%.1fs)", i + 1, len(segments), seg_type, duration)

        if seg_type == "title_card":
            frames = render_title_card(
                title=seg.get("title", ""),
                subtitle=seg.get("subtitle", ""),
                duration=duration,
                fps=fps,
                width=width,
                height=height,
                title_color=secondary,
                subtitle_color=accent,
                accent_color=accent,
                bg_color=primary,
                bg_color_2=_darken_hex(primary, 0.08),
                font_path=font_path,
                font_bold_path=font_bold_path,
                logo_path=logo_path,
                title_size=style["title_size"],
                subtitle_size=style["subtitle_size"],
                particles=False,
                particle_color=accent,
                show_divider=style["dividers"],
            )
            rendered_segments.append(frames)

        elif seg_type == "text_slide":
            font_size = _font_size_to_px(seg.get("font_size", "medium"), style)
            bg_img = await _resolve_bg_image(seg, settings, width, height)
            asset_img = _resolve_asset(seg, campaign, int(width * 0.25), int(height * 0.15))
            frames = render_text_slide(
                text=seg.get("text", ""),
                duration=duration,
                fps=fps,
                width=width,
                height=height,
                animation=seg.get("animation", "fade_in_out"),
                text_color=secondary,
                bg_color=primary,
                bg_color_2=_darken_hex(primary, 0.08) if seg.get("bg_style") == "gradient" else None,
                bg_style=seg.get("bg_style", "gradient"),
                accent_color=accent,
                font_size=font_size,
                font_path=font_path,
                position=seg.get("position", "center"),
                particles=seg.get("particles", False),
                particle_color=accent,
                show_divider=style["dividers"],
                bg_image=bg_img,
                asset_image=asset_img,
                asset_position=seg.get("asset_position", "bottom_right"),
            )
            rendered_segments.append(frames)

        elif seg_type == "video_clip":
            prompt = seg.get("prompt", "cinematic scene")

            if skip_ai:
                frames = render_placeholder_clip(
                    prompt=prompt,
                    duration=duration,
                    fps=fps,
                    width=width,
                    height=height,
                    label_color=accent,
                    font_path=font_path,
                )
            else:
                clip_path = output_dir / f"{reel_id}_seg{i}.mp4"
                await generate_clip(prompt, clip_path, settings)

                frames = video_to_frames(clip_path, fps)
                if frames and (frames[0].shape[1] != width or frames[0].shape[0] != height):
                    from PIL import Image as PILImage
                    resized = []
                    for f in frames:
                        img = PILImage.fromarray(f).resize((width, height), PILImage.LANCZOS)
                        resized.append(np.array(img))
                    frames = resized

            # Apply text overlay if specified
            overlay_text = seg.get("text_overlay")
            if overlay_text:
                frames = add_text_overlay_to_frames(
                    frames, overlay_text, fps,
                    animation=seg.get("overlay_animation", "fade_in_out"),
                    text_color="#f7f2ea",
                    font_size=style["overlay_size"],
                    font_path=font_path,
                    position=seg.get("overlay_position", "bottom"),
                )
            rendered_segments.append(frames)

        elif seg_type == "cta_slide":
            frames = render_cta_slide(
                cta_text=seg.get("cta_text", ""),
                tagline=seg.get("tagline", ""),
                duration=duration,
                fps=fps,
                width=width,
                height=height,
                cta_color=secondary,
                tagline_color=accent,
                accent_color=accent,
                bg_color=primary,
                bg_color_2=_darken_hex(primary, 0.08),
                font_path=font_path,
                font_bold_path=font_bold_path,
                logo_path=logo_path,
                cta_size=style["cta_size"],
                tagline_size=style["tagline_size"],
                particles=False,
                particle_color=accent,
                show_divider=style["dividers"],
            )
            rendered_segments.append(frames)

        else:
            logger.warning("Unknown segment type: %s — skipping", seg_type)

    # Cache each segment's rendered frames for edit consistency
    for i, seg_frames in enumerate(rendered_segments):
        cache_path = output_dir / f"{reel_id}_seg{i}_frames.npz"
        np.savez_compressed(str(cache_path), frames=np.array(seg_frames))
    logger.info("Cached %d segment frame sets for edit consistency", len(rendered_segments))

    # Apply transitions between segments
    logger.info("Applying transitions between %d segments", len(rendered_segments))
    crossfade_frames = int(fps * style["transition_duration"])

    final_frames = rendered_segments[0] if rendered_segments else []

    for i in range(1, len(rendered_segments)):
        transition = segments[i].get("transition_in", "crossfade")
        next_frames = rendered_segments[i]

        if transition == "crossfade":
            final_frames = apply_crossfade(final_frames, next_frames, crossfade_frames)
        elif transition == "fade":
            final_frames = apply_fade_to_black(final_frames, crossfade_frames)
            next_frames = apply_fade_from_black(next_frames, crossfade_frames)
            final_frames = final_frames + next_frames
        elif transition.startswith("wipe"):
            direction = transition.replace("wipe_", "") or "left"
            final_frames = apply_wipe(final_frames, next_frames, crossfade_frames, direction)
        else:
            final_frames = final_frames + next_frames

    # Fade from black at start only (no fade-out at end)
    fade_edge = int(fps * 0.3)
    final_frames = apply_fade_from_black(final_frames, fade_edge)

    # Export final reel
    final_path = output_dir / f"{reel_id}_final.mp4"
    logger.info("Encoding final reel: %d frames at %d fps (%.1fs)",
                len(final_frames), fps, len(final_frames) / fps)
    frames_to_video(final_frames, final_path, fps, crf)

    file_size = final_path.stat().st_size
    logger.info("Final reel: %s (%.1f MB, %.1fs)",
                final_path, file_size / 1024 / 1024, len(final_frames) / fps)
    return final_path


# ---------------------------------------------------------------------------
# Segment editing — redo a single segment and recomposite
# ---------------------------------------------------------------------------

async def render_single_segment(
    seg: dict,
    seg_index: int,
    output_dir: Path,
    reel_id: str,
    campaign: dict[str, Any],
    settings: dict[str, Any],
    *,
    skip_ai: bool = False,
) -> list[np.ndarray]:
    """Render a single segment and return its frames."""
    video_cfg = settings.get("video", {})
    width = video_cfg.get("width", 480)
    height = video_cfg.get("height", 832)
    fps = video_cfg.get("fps", 16)

    brand = campaign.get("brand", {})
    colors = brand.get("colors", {})
    primary = colors.get("primary", "#f7f2ea")
    secondary = colors.get("secondary", "#1a1a1a")
    accent = colors.get("accent", "#C49A3C")
    font_path = brand.get("font")
    font_bold_path = brand.get("font_bold")
    logo_path = brand.get("logo")

    seg_type = seg["type"]
    duration = seg.get("duration", 3)

    if seg_type == "title_card":
        return render_title_card(
            title=seg.get("title", ""),
            subtitle=seg.get("subtitle", ""),
            duration=duration, fps=fps, width=width, height=height,
            title_color=secondary, subtitle_color=accent, accent_color=accent,
            bg_color=primary, bg_color_2=_darken_hex(primary, 0.08),
            font_path=font_path, font_bold_path=font_bold_path,
            logo_path=logo_path,
            particles=False, particle_color=accent,
        )

    elif seg_type == "text_slide":
        font_size = _font_size_to_px(seg.get("font_size", "medium"))
        return render_text_slide(
            text=seg.get("text", ""), duration=duration, fps=fps,
            width=width, height=height,
            animation=seg.get("animation", "fade_in_out"),
            text_color=secondary, bg_color=primary,
            bg_color_2=_darken_hex(primary, 0.08) if seg.get("bg_style") == "gradient" else None,
            accent_color=accent,
            font_size=font_size, font_path=font_path,
            position=seg.get("position", "center"),
            particles=False, particle_color=accent,
        )

    elif seg_type == "video_clip":
        clip_path = output_dir / f"{reel_id}_seg{seg_index}.mp4"
        prompt = seg.get("prompt", "cinematic scene")

        if skip_ai:
            return render_placeholder_clip(
                prompt=prompt, duration=duration, fps=fps,
                width=width, height=height,
                label_color=accent, font_path=font_path,
            )

        # Check if this should use a saved library clip
        library_clip_id = seg.get("library_clip_id")
        if library_clip_id:
            from .tracker import get_library_clip
            clip = get_library_clip(library_clip_id)
            if clip and Path(clip["file_path"]).exists():
                import shutil
                shutil.copy2(clip["file_path"], clip_path)
                logger.info("Using library clip %s for segment %d", library_clip_id, seg_index)
            else:
                logger.warning("Library clip %s not found, generating new", library_clip_id)
                await generate_clip(prompt, clip_path, settings)
        else:
            await generate_clip(prompt, clip_path, settings)

        frames = video_to_frames(clip_path, fps)
        if frames and (frames[0].shape[1] != width or frames[0].shape[0] != height):
            from PIL import Image as PILImage
            frames = [
                np.array(PILImage.fromarray(f).resize((width, height), PILImage.LANCZOS))
                for f in frames
            ]
        overlay_text = seg.get("text_overlay")
        if overlay_text:
            frames = add_text_overlay_to_frames(
                frames, overlay_text, fps,
                animation=seg.get("overlay_animation", "fade_in_out"),
                text_color="#f7f2ea", font_size=44, font_path=font_path,
                position=seg.get("overlay_position", "bottom"),
            )
        return frames

    elif seg_type == "cta_slide":
        return render_cta_slide(
            cta_text=seg.get("cta_text", ""),
            tagline=seg.get("tagline", ""),
            duration=duration, fps=fps, width=width, height=height,
            cta_color=secondary, tagline_color=accent, accent_color=accent,
            bg_color=primary, bg_color_2=_darken_hex(primary, 0.08),
            font_path=font_path, font_bold_path=font_bold_path,
            logo_path=logo_path,
            particles=False, particle_color=accent,
        )

    else:
        logger.warning("Unknown segment type: %s", seg_type)
        return []


def _get_style_by_name(name: str) -> dict:
    """Look up a reel style by name, falling back to classic."""
    for s in REEL_STYLES:
        if s["name"] == name:
            return s
    return REEL_STYLES[0]


async def edit_and_recomposite(
    reel_id: str,
    storyboard: dict,
    segment_index: int,
    changes: dict,
    output_dir: Path,
    campaign: dict[str, Any],
    settings: dict[str, Any],
) -> tuple[Path, dict]:
    """Edit a single segment in a storyboard and recomposite the full reel.

    Only the edited segment is re-rendered.  All other segments are loaded
    from the cached .npz frame files written during the original render.
    This guarantees visual consistency across edits.

    Returns (new_final_path, updated_storyboard).
    """
    video_cfg = settings.get("video", {})
    fps = video_cfg.get("fps", 16)
    crf = video_cfg.get("crf", 23)
    width = video_cfg.get("width", 480)
    height = video_cfg.get("height", 832)

    # Restore the reel style and skip-ai flag used during original render
    style = _get_style_by_name(storyboard.get("_reel_style", "classic"))
    skip_ai = storyboard.get("_skip_ai", False)
    logger.info("Edit recomposite using style: %s (skip_ai=%s)", style["name"], skip_ai)

    brand = campaign.get("brand", {})
    colors = brand.get("colors", {})
    primary = colors.get("primary", "#f7f2ea")
    secondary = colors.get("secondary", "#1a1a1a")
    accent = colors.get("accent", "#C49A3C")
    font_path = brand.get("font")
    font_bold_path = brand.get("font_bold")
    logo_path = brand.get("logo")

    segments = storyboard["segments"]
    seg = segments[segment_index]

    # Apply changes to the storyboard segment
    for key, value in changes.items():
        if value is not None:
            seg[key] = value

    # Load cached frames for all segments; only re-render the edited one
    rendered_segments: list[list[np.ndarray]] = []
    for i, s in enumerate(segments):
        if i == segment_index:
            # Re-render the edited segment with the same style
            logger.info("Re-rendering edited segment %d/%d: %s", i + 1, len(segments), s["type"])
            frames = await _render_segment_with_style(
                s, i, output_dir, reel_id, campaign, settings, style,
                skip_ai=skip_ai,
            )
            rendered_segments.append(frames)
            # Update frame cache for this segment
            cache_path = output_dir / f"{reel_id}_seg{i}_frames.npz"
            np.savez_compressed(str(cache_path), frames=np.array(frames))
        else:
            # Load from cache
            cache_path = output_dir / f"{reel_id}_seg{i}_frames.npz"
            if cache_path.exists():
                data = np.load(str(cache_path))
                frames = list(data["frames"])
                logger.info("Loaded cached frames for segment %d (%d frames)", i, len(frames))
                rendered_segments.append(frames)
            else:
                # Cache miss — re-render (shouldn't normally happen)
                logger.warning("No cached frames for segment %d — re-rendering", i)
                frames = await _render_segment_with_style(
                    s, i, output_dir, reel_id, campaign, settings, style,
                    skip_ai=skip_ai,
                )
                rendered_segments.append(frames)
                np.savez_compressed(str(cache_path), frames=np.array(frames))

    # Composite with transitions (using the same style's transition duration)
    crossfade_frames = int(fps * style["transition_duration"])
    final_frames = rendered_segments[0] if rendered_segments else []

    for i in range(1, len(rendered_segments)):
        transition = segments[i].get("transition_in", "crossfade")
        next_frames = rendered_segments[i]
        if transition == "crossfade":
            final_frames = apply_crossfade(final_frames, next_frames, crossfade_frames)
        elif transition == "fade":
            final_frames = apply_fade_to_black(final_frames, crossfade_frames)
            next_frames = apply_fade_from_black(next_frames, crossfade_frames)
            final_frames = final_frames + next_frames
        elif transition.startswith("wipe"):
            direction = transition.replace("wipe_", "") or "left"
            final_frames = apply_wipe(final_frames, next_frames, crossfade_frames, direction)
        else:
            final_frames = final_frames + next_frames

    # Fade from black at start only (matching execute_storyboard)
    fade_edge = int(fps * 0.3)
    final_frames = apply_fade_from_black(final_frames, fade_edge)

    final_path = output_dir / f"{reel_id}_final.mp4"
    logger.info("Recompositing reel: %d frames at %d fps (%.1fs)",
                len(final_frames), fps, len(final_frames) / fps)
    frames_to_video(final_frames, final_path, fps, crf)

    return final_path, storyboard


async def _render_segment_with_style(
    seg: dict,
    seg_index: int,
    output_dir: Path,
    reel_id: str,
    campaign: dict[str, Any],
    settings: dict[str, Any],
    style: dict,
    skip_ai: bool = False,
) -> list[np.ndarray]:
    """Render a single segment using a specific reel style (for edit consistency)."""
    video_cfg = settings.get("video", {})
    width = video_cfg.get("width", 480)
    height = video_cfg.get("height", 832)
    fps = video_cfg.get("fps", 16)

    brand = campaign.get("brand", {})
    colors = brand.get("colors", {})
    primary = colors.get("primary", "#f7f2ea")
    secondary = colors.get("secondary", "#1a1a1a")
    accent = colors.get("accent", "#C49A3C")
    font_path = brand.get("font")
    font_bold_path = brand.get("font_bold")
    logo_path = brand.get("logo")

    seg_type = seg["type"]
    duration = seg.get("duration", 3)

    if seg_type == "title_card":
        return render_title_card(
            title=seg.get("title", ""),
            subtitle=seg.get("subtitle", ""),
            duration=duration, fps=fps, width=width, height=height,
            title_color=secondary, subtitle_color=accent, accent_color=accent,
            bg_color=primary, bg_color_2=_darken_hex(primary, 0.08),
            font_path=font_path, font_bold_path=font_bold_path,
            logo_path=logo_path,
            title_size=style["title_size"], subtitle_size=style["subtitle_size"],
            particles=False, particle_color=accent,
            show_divider=style["dividers"],
        )

    elif seg_type == "text_slide":
        font_size = _font_size_to_px(seg.get("font_size", "medium"), style)
        bg_img = await _resolve_bg_image(seg, settings, width, height)
        asset_img = _resolve_asset(seg, campaign, int(width * 0.25), int(height * 0.15))
        return render_text_slide(
            text=seg.get("text", ""), duration=duration, fps=fps,
            width=width, height=height,
            animation=seg.get("animation", "fade_in_out"),
            text_color=secondary, bg_color=primary,
            bg_color_2=_darken_hex(primary, 0.08) if seg.get("bg_style") == "gradient" else None,
            accent_color=accent,
            font_size=font_size, font_path=font_path,
            position=seg.get("position", "center"),
            particles=False, particle_color=accent,
            show_divider=style["dividers"],
            bg_image=bg_img,
            asset_image=asset_img,
            asset_position=seg.get("asset_position", "bottom_right"),
        )

    elif seg_type == "video_clip":
        clip_path = output_dir / f"{reel_id}_seg{seg_index}.mp4"
        prompt = seg.get("prompt", "cinematic scene")

        if skip_ai:
            frames = render_placeholder_clip(
                prompt=prompt, duration=duration, fps=fps,
                width=width, height=height,
                label_color=accent, font_path=font_path,
            )
        elif not clip_path.exists():
            await generate_clip(prompt, clip_path, settings)
            frames = video_to_frames(clip_path, fps)
        else:
            frames = video_to_frames(clip_path, fps)
        if frames and (frames[0].shape[1] != width or frames[0].shape[0] != height):
            from PIL import Image as PILImage
            frames = [
                np.array(PILImage.fromarray(f).resize((width, height), PILImage.LANCZOS))
                for f in frames
            ]
        overlay_text = seg.get("text_overlay")
        if overlay_text:
            frames = add_text_overlay_to_frames(
                frames, overlay_text, fps,
                animation=seg.get("overlay_animation", "fade_in_out"),
                text_color="#f7f2ea",
                font_size=style["overlay_size"],
                font_path=font_path,
                position=seg.get("overlay_position", "bottom"),
            )
        return frames

    elif seg_type == "cta_slide":
        return render_cta_slide(
            cta_text=seg.get("cta_text", ""),
            tagline=seg.get("tagline", ""),
            duration=duration, fps=fps, width=width, height=height,
            cta_color=secondary, tagline_color=accent, accent_color=accent,
            bg_color=primary, bg_color_2=_darken_hex(primary, 0.08),
            font_path=font_path, font_bold_path=font_bold_path,
            logo_path=logo_path,
            cta_size=style["cta_size"], tagline_size=style["tagline_size"],
            particles=False, particle_color=accent,
            show_divider=style["dividers"],
        )

    else:
        logger.warning("Unknown segment type: %s", seg_type)
        return []

"""Audio pipeline — TTS narration + mood-based background music for reels.

Uses edge-tts (free Microsoft TTS) for narration and pydub for mixing.
Freesound.org API fetches royalty-free music by mood (free API key required).
FFmpeg (bundled via imageio-ffmpeg) handles final muxing onto the video.
"""

from __future__ import annotations

import asyncio
import logging
import random
import subprocess
from pathlib import Path
from typing import Any

import edge_tts
import httpx
from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Use ffmpeg bundled with imageio-ffmpeg
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG = "ffmpeg"

# Mood → Freesound search queries (tuned for background music results)
MOOD_SEARCH_QUERIES = {
    "warm": "warm gentle acoustic background music",
    "melancholic": "melancholic sad piano ambient music",
    "nostalgic": "nostalgic emotional piano music",
    "hopeful": "hopeful uplifting inspirational background music",
    "gentle": "gentle soft calm ambient music",
    "upbeat": "upbeat happy positive background music",
    "reflective": "reflective contemplative ambient piano music",
    "cinematic": "cinematic emotional orchestral background music",
}


# Pool of warm, natural English voices for variety
TTS_VOICES = [
    "en-US-AriaNeural",          # warm female (default)
    "en-US-AvaNeural",           # natural female
    "en-US-EmmaNeural",          # friendly female
    "en-US-AnaNeural",           # young female
    "en-US-BrianNeural",         # warm male
    "en-US-AndrewNeural",        # calm male
    "en-US-ChristopherNeural",   # mature male
    "en-GB-SoniaNeural",         # British female
    "en-GB-RyanNeural",          # British male
    "en-AU-NatashaNeural",       # Australian female
]


def _get_audio_config(settings: dict[str, Any]) -> dict[str, Any]:
    """Extract audio config from settings with defaults."""
    cfg = settings.get("audio", {})
    return {
        "enabled": cfg.get("enabled", True),
        "voice": cfg.get("voice", "random"),
        "narration_enabled": cfg.get("narration_enabled", True),
        "music_enabled": cfg.get("music_enabled", True),
        "music_volume_db": cfg.get("music_volume_db", -8),
        "narration_volume_db": cfg.get("narration_volume_db", 0),
        "music_dir": cfg.get("music_dir", "assets/music"),
        "duck_music_db": cfg.get("duck_music_db", -6),
        "freesound_api_key": cfg.get("freesound_api_key", ""),
    }


def _pick_voice(voice_setting: str) -> str:
    """Pick a TTS voice — random from pool, or the specific one configured."""
    if voice_setting == "random":
        chosen = random.choice(TTS_VOICES)
        logger.info("Selected random TTS voice: %s", chosen)
        return chosen
    return voice_setting


async def generate_narration(
    segments: list[dict],
    output_dir: Path,
    voice: str = "random",
    fps: int = 16,
) -> Path | None:
    """Generate a single narration audio track timed to the storyboard.

    Produces one continuous audio file where each segment's narration
    is placed at the correct timestamp using silence padding.
    """
    # Collect narration entries with their start times
    narrations = []
    current_time_ms = 0

    for seg in segments:
        duration_ms = int(seg.get("duration", 3) * 1000)
        narration_text = seg.get("narration")
        if narration_text and narration_text.strip():
            narrations.append({
                "text": narration_text.strip(),
                "start_ms": current_time_ms,
                "duration_ms": duration_ms,
            })
        current_time_ms += duration_ms

    if not narrations:
        logger.info("No narration text in storyboard — skipping TTS")
        return None

    total_duration_ms = current_time_ms
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pick a single voice for the entire reel (consistency)
    actual_voice = _pick_voice(voice)

    # Generate TTS for each narration chunk
    tts_clips: list[tuple[int, int, AudioSegment]] = []  # (start_ms, max_duration_ms, clip)

    for i, entry in enumerate(narrations):
        tts_path = output_dir / f"_tts_chunk_{i}.mp3"
        communicate = edge_tts.Communicate(entry["text"], actual_voice)
        await communicate.save(str(tts_path))

        clip = AudioSegment.from_file(str(tts_path))
        tts_clips.append((entry["start_ms"], entry["duration_ms"], clip))

        # Clean up temp file
        tts_path.unlink(missing_ok=True)

    # Truncate each clip so it never bleeds into the next segment's slot
    trimmed_clips: list[tuple[int, AudioSegment]] = []
    for i, (start_ms, max_dur_ms, clip) in enumerate(tts_clips):
        if len(clip) > max_dur_ms:
            logger.info(
                "Trimming TTS chunk %d from %.1fs to %.1fs to prevent overlap",
                i, len(clip) / 1000, max_dur_ms / 1000,
            )
            clip = clip[:max_dur_ms]
        trimmed_clips.append((start_ms, clip))

    # Build the full narration track — size it to fit the longest TTS clip
    # so overlay() never truncates the last segment's narration
    max_end_ms = total_duration_ms
    for start_ms, clip in trimmed_clips:
        clip_end = start_ms + len(clip)
        if clip_end > max_end_ms:
            max_end_ms = clip_end
    # Extra safety margin so rounding never clips the tail
    narration_track = AudioSegment.silent(duration=max_end_ms + 500)
    for start_ms, clip in trimmed_clips:
        narration_track = narration_track.overlay(clip, position=start_ms)

    narration_path = output_dir / "_narration.wav"
    narration_track.export(str(narration_path), format="wav")
    logger.info("Narration track generated: %.1fs", len(narration_track) / 1000)

    return narration_path


async def extend_segments_for_narration(
    segments: list[dict],
    output_dir: Path,
    voice: str = "random",
) -> str:
    """Pre-generate TTS to measure durations, then extend non-AI segments to fit.

    video_clip segments are fixed at 5s (AI model constraint) so their narration
    may be trimmed. All other segment types get extended to fit the full narration.
    Modifies segments in-place.  Returns the chosen voice name so the same
    voice can be reused for final narration generation.
    """
    actual_voice = _pick_voice(voice)
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, seg in enumerate(segments):
        narration_text = seg.get("narration")
        if not narration_text or not narration_text.strip():
            continue

        seg_type = seg.get("type", "")
        current_duration = seg.get("duration", 3)

        # Generate TTS to measure its length
        tts_path = output_dir / f"_tts_measure_{i}.mp3"
        try:
            communicate = edge_tts.Communicate(narration_text.strip(), actual_voice)
            await communicate.save(str(tts_path))
            clip = AudioSegment.from_file(str(tts_path))
            tts_duration_s = len(clip) / 1000.0 + 0.3  # 300ms padding
        finally:
            tts_path.unlink(missing_ok=True)

        # Only extend non-AI segments (video_clip is fixed by the model)
        if seg_type != "video_clip" and tts_duration_s > current_duration:
            logger.info(
                "Extending %s segment %d from %.1fs to %.1fs to fit narration",
                seg_type, i, current_duration, tts_duration_s,
            )
            seg["duration"] = round(tts_duration_s, 1)

    return actual_voice


async def pick_background_music(
    music_dir: str | Path,
    duration_ms: int,
    mood: str | None = None,
    freesound_api_key: str = "",
) -> AudioSegment | None:
    """Get background music: try Freesound by mood first, then local files."""
    music_path = Path(music_dir)
    music_path.mkdir(parents=True, exist_ok=True)

    # Step 1: Try to fetch by mood from Freesound (with local caching)
    if mood and freesound_api_key:
        cached = _get_cached_music(music_path, mood)
        if cached:
            logger.info("Using cached %s music: %s", mood, cached.name)
            return _prepare_track(AudioSegment.from_file(str(cached)), duration_ms)

        # Fetch from Freesound
        fetched = await _fetch_from_freesound(mood, freesound_api_key, music_path)
        if fetched:
            return _prepare_track(AudioSegment.from_file(str(fetched)), duration_ms)

    # Step 2: Try local mood folder
    if mood:
        mood_dir = music_path / mood
        if mood_dir.exists():
            tracks = _list_tracks(mood_dir)
            if tracks:
                chosen = random.choice(tracks)
                logger.info("Using local %s music: %s", mood, chosen.name)
                return _prepare_track(AudioSegment.from_file(str(chosen)), duration_ms)

    # Step 3: Fall back to any local track
    tracks = _list_tracks(music_path)
    if tracks:
        chosen = random.choice(tracks)
        logger.info("Using local music (no mood match): %s", chosen.name)
        return _prepare_track(AudioSegment.from_file(str(chosen)), duration_ms)

    logger.info("No music available (no tracks found or fetch failed)")
    return None


def _list_tracks(directory: Path) -> list[Path]:
    """List audio files in a directory (non-recursive, skip temp files)."""
    tracks = []
    for ext in ("*.mp3", "*.wav", "*.ogg"):
        tracks.extend(
            p for p in directory.glob(ext) if not p.name.startswith("_")
        )
    return tracks


def _get_cached_music(music_dir: Path, mood: str) -> Path | None:
    """Check for a previously fetched track in the cache folder."""
    cache_dir = music_dir / "cache" / mood
    if not cache_dir.exists():
        return None
    tracks = _list_tracks(cache_dir)
    return random.choice(tracks) if tracks else None


async def _fetch_from_freesound(
    mood: str,
    api_key: str,
    music_dir: Path,
) -> Path | None:
    """Search Freesound.org for a mood-matched track, download preview, cache it."""
    query = MOOD_SEARCH_QUERIES.get(mood, f"{mood} background music")
    cache_dir = music_dir / "cache" / mood
    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Search for tracks 20-120 seconds long, sorted by rating
            resp = await client.get(
                "https://freesound.org/apiv2/search/text/",
                params={
                    "query": query,
                    "filter": "duration:[20 TO 120]",
                    "sort": "rating_desc",
                    "fields": "id,name,previews,duration,avg_rating",
                    "page_size": 10,
                    "token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            logger.warning("Freesound: no results for mood '%s'", mood)
            return None

        # Pick from top results randomly for variety
        pick = random.choice(results[:min(5, len(results))])
        preview_url = pick.get("previews", {}).get("preview-hq-mp3")
        if not preview_url:
            logger.warning("Freesound: no preview URL for sound %s", pick.get("id"))
            return None

        # Download the preview
        async with httpx.AsyncClient(timeout=60) as client:
            audio_resp = await client.get(preview_url)
            audio_resp.raise_for_status()

        # Save to cache with a stable filename
        safe_name = f"{pick['id']}_{mood}.mp3"
        cached_path = cache_dir / safe_name
        cached_path.write_bytes(audio_resp.content)

        logger.info(
            "Freesound: downloaded '%s' (%.0fs, rating %.1f) for mood '%s'",
            pick.get("name", "?"), pick.get("duration", 0),
            pick.get("avg_rating", 0), mood,
        )
        return cached_path

    except Exception:
        logger.warning("Freesound fetch failed for mood '%s'", mood, exc_info=True)
        return None


def _prepare_track(music: AudioSegment, duration_ms: int) -> AudioSegment:
    """Loop/trim a music track to fit the target duration, with fade-out."""
    if len(music) < duration_ms:
        repeats = (duration_ms // len(music)) + 1
        music = music * repeats

    music = music[:duration_ms]
    music = music.fade_out(min(3000, duration_ms // 4))
    return music


def mix_audio(
    narration: AudioSegment | None,
    music: AudioSegment | None,
    *,
    music_volume_db: int = -18,
    narration_volume_db: int = 0,
    duck_music_db: int = -6,
) -> AudioSegment | None:
    """Mix narration and music into a single audio track.

    Music is lowered to music_volume_db. When narration is playing,
    music is ducked by an additional duck_music_db.
    """
    if narration is None and music is None:
        return None

    if narration is not None and music is None:
        return narration + narration_volume_db

    if narration is None and music is not None:
        return music + music_volume_db

    # Both present — overlay with music ducking
    # Adjust volumes
    narration = narration + narration_volume_db
    music = music + music_volume_db

    # Ensure same length
    target_len = max(len(narration), len(music))
    if len(narration) < target_len:
        narration = narration + AudioSegment.silent(duration=target_len - len(narration))
    if len(music) < target_len:
        music = music + AudioSegment.silent(duration=target_len - len(music))

    # Simple ducking: lower music volume where narration has audio
    # For simplicity, overlay narration on the already-lowered music
    # The music_volume_db already makes it quiet enough as background
    mixed = music.overlay(narration)

    return mixed


def _format_ass_time(ms: int) -> str:
    """Format milliseconds as ASS timestamp H:MM:SS.cc"""
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    cs = (ms % 1000) // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_subtitles(
    segments: list[dict],
    output_path: Path,
    video_width: int = 480,
    video_height: int = 832,
    font_path: str | None = None,
) -> Path | None:
    """Generate an ASS subtitle file from storyboard narration fields."""
    events = []
    current_ms = 0
    num_segments = len(segments)

    for seg_idx, seg in enumerate(segments):
        duration_ms = int(seg.get("duration", 3) * 1000)
        narration = seg.get("narration")
        if narration and narration.strip():
            events.append({
                "start": current_ms,
                "end": current_ms + duration_ms,
                "text": narration.strip(),
                "is_last": seg_idx == num_segments - 1,
            })
        current_ms += duration_ms

    if not events:
        return None

    # Resolve font name from path
    font_name = "Poppins Medium"
    if font_path:
        p = Path(font_path)
        # Extract font family from filename (e.g. Poppins-Medium.ttf -> Poppins Medium)
        font_name = p.stem.replace("-", " ")

    # ASS header — white text with black outline
    font_size = max(18, video_width // 22)
    margin_bottom = int(video_height * 0.18)
    margin_top = int(video_height * 0.06)
    ass_content = f"""[Script Info]
Title: AutoReels Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,20,20,{margin_bottom},1
Style: Top,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,8,20,20,{margin_top},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    for ev in events:
        start = _format_ass_time(ev["start"])
        end = _format_ass_time(ev["end"])
        # Replace newlines with ASS line breaks
        text = ev["text"].replace("\n", "\\N")
        style = "Top" if ev["is_last"] else "Default"
        ass_content += f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ass_content, encoding="utf-8")
    logger.info("Subtitles generated: %d events", len(events))
    return output_path


def mux_audio_to_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    subtitle_path: Path | None = None,
) -> Path:
    """Mux audio track onto a video file using ffmpeg.

    If subtitle_path is provided, burns subtitles into the video.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if subtitle_path and subtitle_path.exists():
        # Re-encode video to burn in subtitles + add audio
        # Use forward slashes and escape colons for ffmpeg filter on Windows
        sub_escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
        cmd = [
            FFMPEG,
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex",
            f"[0:v]ass='{sub_escaped}'[v]",
            "-map", "[v]",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            str(output_path),
        ]
    else:
        cmd = [
            FFMPEG,
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            str(output_path),
        ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        logger.error("ffmpeg mux failed: %s", result.stderr[-500:] if result.stderr else "")
        raise RuntimeError(f"ffmpeg mux failed (code {result.returncode})")

    logger.info("Audio muxed onto video: %s (%.1f MB)",
                output_path, output_path.stat().st_size / 1024 / 1024)
    return output_path


async def add_audio_to_reel(
    video_path: Path,
    storyboard: dict,
    output_dir: Path,
    settings: dict[str, Any],
    campaign: dict[str, Any] | None = None,    narration_voice: str | None = None,) -> Path:
    """Full audio pipeline: generate narration → pick music → mix → subtitles → mux.

    Returns path to the final video with audio (or the original video
    if audio is disabled or no audio content was generated).
    """
    cfg = _get_audio_config(settings)

    if not cfg["enabled"]:
        logger.info("Audio disabled in settings — returning silent video")
        return video_path

    segments = storyboard.get("segments", [])
    video_cfg = settings.get("video", {})
    fps = video_cfg.get("fps", 16)

    # Total video duration in ms
    total_duration_ms = int(sum(s.get("duration", 3) for s in segments) * 1000)

    # Step 1: Generate narration (if any segments have narration text)
    narration = None
    if cfg["narration_enabled"]:
        narration_path = await generate_narration(
            segments, output_dir,
            voice=narration_voice or cfg["voice"],
            fps=fps,
        )
        if narration_path and narration_path.exists():
            narration = AudioSegment.from_file(str(narration_path))
            narration_path.unlink(missing_ok=True)

    # Step 2: Pick background music (mood-aware)
    music = None
    if cfg["music_enabled"]:
        from .campaign import ROOT_DIR
        music_dir = ROOT_DIR / cfg["music_dir"]
        music_mood = storyboard.get("music_mood")
        freesound_key = cfg.get("freesound_api_key", "")
        music = await pick_background_music(
            music_dir, total_duration_ms,
            mood=music_mood,
            freesound_api_key=freesound_key,
        )

    # Step 3: Mix narration + music
    mixed = mix_audio(
        narration, music,
        music_volume_db=cfg["music_volume_db"],
        narration_volume_db=cfg["narration_volume_db"],
        duck_music_db=cfg["duck_music_db"],
    )

    if mixed is None:
        logger.info("No audio content generated — returning silent video")
        return video_path

    # Export mixed audio to temp file
    mixed_path = output_dir / "_mixed_audio.wav"
    mixed.export(str(mixed_path), format="wav")

    # Step 4: Generate subtitles
    subtitle_path = None
    video_cfg_w = video_cfg.get("width", 480)
    video_cfg_h = video_cfg.get("height", 832)
    font_path = None
    if campaign:
        font_path = campaign.get("brand", {}).get("font")
    subtitle_path = generate_subtitles(
        segments, output_dir / "_subtitles.ass",
        video_width=video_cfg_w,
        video_height=video_cfg_h,
        font_path=font_path,
    )

    # Step 5: Mux onto video (with subtitles burned in)
    final_with_audio = video_path.parent / video_path.name.replace("_final.mp4", "_final_audio.mp4")
    mux_audio_to_video(video_path, mixed_path, final_with_audio, subtitle_path=subtitle_path)

    # Clean up temp files
    mixed_path.unlink(missing_ok=True)
    if subtitle_path:
        subtitle_path.unlink(missing_ok=True)

    # Replace the original silent video with the audio version
    video_path.unlink(missing_ok=True)
    final_with_audio.rename(video_path)

    logger.info("Final reel with audio: %s", video_path)
    return video_path

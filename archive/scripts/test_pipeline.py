"""Quick smoke test — creates a dummy reel (colored bars) and pushes it
through the full pipeline (post-process → tracker → Discord bot picks it up).
Skips the actual LTX-Video generation so no GPU is needed."""

import asyncio
import uuid
import sys
from pathlib import Path
from datetime import date

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from moviepy import VideoClip

from src.campaign import load_settings, load_campaign, get_output_dir, ROOT_DIR
from src.prompter import pick_theme, pick_overlay_text
from src.post_process import process_reel
from src.tracker import init_db, create_reel


def make_test_clip(output_path: Path, duration: float = 3.0, fps: int = 24):
    """Generate a simple animated test clip with brand colors."""
    w, h = 512, 768
    green = np.array([22, 67, 28], dtype=np.uint8)    # #16431c
    cream = np.array([247, 242, 234], dtype=np.uint8)  # #f7f2ea
    gold  = np.array([196, 154, 60], dtype=np.uint8)   # #C49A3C

    def make_frame(t):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        # Animated vertical bars
        offset = int((t / duration) * w) % w
        for x in range(w):
            pos = (x + offset) % w
            if pos < w // 3:
                frame[:, x] = green
            elif pos < 2 * w // 3:
                frame[:, x] = cream
            else:
                frame[:, x] = gold
        return frame

    clip = VideoClip(make_frame, duration=duration).with_fps(fps)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clip.write_videofile(str(output_path), codec="libx264", audio=False, logger=None)
    clip.close()
    print(f"  Test clip: {output_path}")


def main():
    init_db()
    settings = load_settings()
    campaign = load_campaign("matra")
    output_dir = get_output_dir(settings, "matra")

    theme = pick_theme(campaign)
    overlay = pick_overlay_text(campaign)
    reel_id = f"matra_test_{uuid.uuid4().hex[:6]}"

    print(f"Theme: {theme['name']}")
    print(f"CTA: {overlay['cta']}")
    print(f"Reel ID: {reel_id}")

    # Generate 2 test clips
    clip_paths = []
    for i in range(2):
        p = output_dir / f"{reel_id}_clip{i}.mp4"
        make_test_clip(p)
        clip_paths.append(p)

    # Post-process (upscale, overlay, encode)
    final_path = output_dir / f"{reel_id}_final.mp4"
    process_reel(clip_paths, final_path, campaign, settings, cta_text=overlay["cta"])

    # Track in DB as pending — the running bot will pick it up
    create_reel(
        reel_id=reel_id,
        campaign="matra",
        theme=theme["name"],
        prompt="[test clip — animated brand color bars]",
        cta_text=overlay["cta"],
        file_path=str(final_path),
    )

    size_mb = final_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ Reel ready: {final_path} ({size_mb:.1f} MB)")
    print("   Status: pending — the Discord bot will post it for review.")


if __name__ == "__main__":
    main()

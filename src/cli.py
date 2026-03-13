"""CLI entry point for AutoReels."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import uuid
from pathlib import Path

import click

from .campaign import load_settings, load_campaign, get_output_dir, ROOT_DIR
from .prompter import pick_theme, expand_prompt_with_groq, pick_overlay_text, build_base_prompt
from .video_gen import generate_clip, unload_model
from .post_process import process_reel
from .tracker import (
    init_db, create_reel, update_reel_status, get_today_reels,
    get_reel, get_reel_storyboard, update_reel_storyboard, delete_reel,
    save_clip_to_library, get_library_clips, search_library_clips,
)
from .social.facebook import upload_video_to_page
from .social.instagram import upload_reel_from_local
from .director import create_storyboard, execute_storyboard, edit_and_recomposite
from .audio import add_audio_to_reel, extend_segments_for_narration


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _on_approve(reel_id: str, reel_path: Path, campaign_name: str) -> None:
    """Called when a reel is approved in Discord — upload to FB + IG."""
    settings = load_settings()
    campaign = load_campaign(campaign_name)
    meta = settings["meta"]

    # Build caption
    overlay = pick_overlay_text(campaign)
    hashtags = campaign.get("social", {}).get("hashtags", [])
    caption = f"{overlay['cta']}\n\n{' '.join(hashtags)}"

    # Facebook Page
    if meta["page_id"] and meta["page_access_token"]:
        try:
            fb_result = await upload_video_to_page(
                reel_path,
                meta["page_id"],
                meta["page_access_token"],
                description=caption,
            )
            update_reel_status(reel_id, "approved", fb_video_id=str(fb_result.get("video_id", "")))
            logger.info("Facebook upload complete for %s", reel_id)
        except Exception:
            logger.exception("Facebook upload failed for %s", reel_id)

    # Instagram Reels
    if meta["ig_account_id"] and meta["page_access_token"]:
        try:
            ig_result = await upload_reel_from_local(
                reel_path,
                meta["ig_account_id"],
                meta["page_id"],
                meta["page_access_token"],
                caption=caption,
            )
            update_reel_status(reel_id, "approved", ig_media_id=str(ig_result.get("id", "")))
            logger.info("Instagram upload complete for %s", reel_id)
        except Exception:
            logger.exception("Instagram upload failed for %s", reel_id)

    # If no social tokens configured, just mark approved locally
    if not (meta["page_id"] and meta["page_access_token"]):
        update_reel_status(reel_id, "approved_local")
        logger.info("Reel %s approved locally (no Meta API tokens configured)", reel_id)


async def _on_delete(reel_id: str) -> None:
    """Called when a reel is deleted — remove all generated media and DB record."""
    logger.info("Deleting reel %s and all media", reel_id)
    delete_reel(reel_id)


async def _on_edit_segment(
    reel_id: str,
    reel_path: Path,
    campaign_name: str,
    segment_index: int,
    changes: dict,
    interaction=None,
) -> None:
    """Called when user edits a segment — re-render and recomposite."""
    settings = load_settings()
    campaign = load_campaign(campaign_name)
    output_dir = reel_path.parent

    storyboard = get_reel_storyboard(reel_id)
    if not storyboard:
        logger.error("No storyboard for reel %s — cannot edit", reel_id)
        if interaction:
            await interaction.followup.send(
                f"❌ No storyboard data for `{reel_id}`. Cannot edit.", ephemeral=True,
            )
        return

    try:
        new_path, updated_sb = await edit_and_recomposite(
            reel_id, storyboard, segment_index, changes,
            output_dir, campaign, settings,
        )

        # Re-mux audio (narration + music + subtitles) onto the recomposited video
        new_path = await add_audio_to_reel(
            new_path, updated_sb, output_dir, settings, campaign,
        )

        update_reel_storyboard(reel_id, updated_sb)
        update_reel_status(reel_id, "pending", file_path=str(new_path))

        logger.info("Reel %s edited (segment %d) and recomposited with audio", reel_id, segment_index)
        return new_path, updated_sb
    except Exception as e:
        logger.exception("Edit failed for reel %s segment %d", reel_id, segment_index)
        if interaction:
            await interaction.followup.send(
                f"❌ Edit failed: {e}", ephemeral=True,
            )
        return None


async def _on_save_clips(
    reel_id: str,
    campaign_name: str,
    segment_indices: list[int],
) -> list[str]:
    """Save specific AI video clips from a reel to the clip library."""
    reel = get_reel(reel_id)
    if not reel:
        return []

    storyboard = get_reel_storyboard(reel_id)
    if not storyboard:
        return []

    reel_path = Path(reel["file_path"])
    output_dir = reel_path.parent
    library_dir = ROOT_DIR / "library" / campaign_name
    library_dir.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    video_cfg = settings.get("video", {})

    saved_ids = []
    for idx in segment_indices:
        seg = storyboard["segments"][idx]
        if seg.get("type") != "video_clip":
            continue

        # Find the source segment file
        src_path = output_dir / f"{reel_id}_seg{idx}.mp4"
        if not src_path.exists():
            logger.warning("Segment file not found: %s", src_path)
            continue

        clip_id = f"clip_{uuid.uuid4().hex[:8]}"
        dest_path = library_dir / f"{clip_id}.mp4"
        shutil.copy2(str(src_path), str(dest_path))

        save_clip_to_library(
            clip_id=clip_id,
            campaign=campaign_name,
            prompt=seg.get("prompt", ""),
            file_path=str(dest_path),
            theme=reel.get("theme", ""),
            source_reel_id=reel_id,
            source_segment_index=idx,
            width=video_cfg.get("width", 480),
            height=video_cfg.get("height", 832),
            duration_sec=seg.get("duration", 5),
            fps=video_cfg.get("fps", 16),
        )
        saved_ids.append(clip_id)
        logger.info("Saved clip %s from reel %s segment %d", clip_id, reel_id, idx)

    return saved_ids





async def generate_one_reel(
    campaign_name: str,
    *,
    exclude_reel_id: str | None = None,
    post_to_discord: bool = True,
    use_groq: bool = True,
    skip_ai: bool = False,
) -> Path:
    """Generate a single reel end-to-end using the Groq Director.

    Flow: pick theme → Groq creates storyboard → execute segments
    (AI video clips + creative-coded slides/transitions) → composite → Discord.
    """
    settings = load_settings()
    campaign = load_campaign(campaign_name)
    output_dir = get_output_dir(settings, campaign_name)

    # Pick theme (avoid recently used if we have today's reels)
    today_reels = get_today_reels(campaign_name)
    used_themes = [r["theme"] for r in today_reels]
    theme = pick_theme(campaign, exclude=used_themes)

    reel_id = f"{campaign_name}_{uuid.uuid4().hex[:8]}"
    overlay = pick_overlay_text(campaign)

    if use_groq:
        # Director mode — Groq creates a multi-segment storyboard
        storyboard = await create_storyboard(theme, campaign, settings)

        # Pre-generate TTS to measure durations, extend segments to fit narration
        audio_cfg = settings.get("audio", {})
        narration_voice = None
        if audio_cfg.get("enabled", True) and audio_cfg.get("narration_enabled", True):
            narration_voice = await extend_segments_for_narration(
                storyboard["segments"], output_dir,
                voice=audio_cfg.get("voice", "random"),
            )

        final_path = await execute_storyboard(
            storyboard, output_dir, reel_id, campaign, settings,
            skip_ai=skip_ai,
        )
        # Add audio (narration + background music) to the silent video
        final_path = await add_audio_to_reel(
            final_path, storyboard, output_dir, settings, campaign,
            narration_voice=narration_voice,
        )
        # Build a summary prompt from all video_clip prompts for tracking
        video_prompts = [
            s.get("prompt", "") for s in storyboard.get("segments", [])
            if s.get("type") == "video_clip"
        ]
        prompt_summary = " | ".join(video_prompts) if video_prompts else theme["name"]
    else:
        # Legacy mode — single clip with post-processing
        storyboard = None
        prompt = build_base_prompt(theme)
        clip_path = output_dir / f"{reel_id}_clip0.mp4"
        await generate_clip(prompt, clip_path, settings)
        final_path = output_dir / f"{reel_id}_final.mp4"
        process_reel([clip_path], final_path, campaign, settings, cta_text=overlay["cta"])
        prompt_summary = prompt

    # Track in DB (with full storyboard for edit support)
    create_reel(
        reel_id=reel_id,
        campaign=campaign_name,
        theme=theme["name"],
        prompt=prompt_summary,
        cta_text=overlay["cta"],
        file_path=str(final_path),
        storyboard=storyboard,
    )

    if post_to_discord:
        logger.info(
            "Reel %s saved as pending — the Discord bot will post it for review",
            reel_id,
        )
    else:
        logger.info("Reel %s saved locally (Discord posting skipped)", reel_id)

    return final_path


# ─── CLI Commands ────────────────────────────────────────────────────────────


@click.group()
def cli():
    """AutoReels — AI marketing reel generator."""
    init_db()


@cli.command()
@click.argument("campaign_name")
@click.option("--no-discord", is_flag=True, help="Skip Discord posting")
@click.option("--no-groq", is_flag=True, help="Use base prompts instead of Groq")
@click.option("--skip-ai", is_flag=True, help="Replace AI video with placeholders (fast test mode)")
def generate(campaign_name: str, no_discord: bool, no_groq: bool, skip_ai: bool):
    """Generate a single reel for a campaign."""
    path = asyncio.run(
        generate_one_reel(
            campaign_name,
            post_to_discord=not no_discord,
            use_groq=not no_groq,
            skip_ai=skip_ai,
        )
    )
    click.echo(f"✅ Reel saved: {path}")


@cli.command()
@click.argument("campaign_name")
@click.option("--count", default=3, help="Number of reels to generate")
@click.option("--no-discord", is_flag=True)
@click.option("--no-groq", is_flag=True)
@click.option("--skip-ai", is_flag=True, help="Replace AI video with placeholders (fast test mode)")
def batch(campaign_name: str, count: int, no_discord: bool, no_groq: bool, skip_ai: bool):
    """Generate a batch of reels for a campaign."""

    async def _batch():
        paths = []
        for i in range(count):
            logger.info("=" * 50)
            logger.info("Generating reel %d/%d", i + 1, count)
            logger.info("=" * 50)
            try:
                p = await generate_one_reel(
                    campaign_name,
                    post_to_discord=not no_discord,
                    use_groq=not no_groq,
                    skip_ai=skip_ai,
                )
                paths.append(p)
                logger.info("Reel %d/%d complete: %s", i + 1, count, p)
            except Exception:
                logger.exception("Reel %d/%d failed — skipping", i + 1, count)
                # Clean up VRAM so next reel has a fresh start
                import torch, gc
                torch.cuda.empty_cache()
                gc.collect()
        return paths

    paths = asyncio.run(_batch())
    for p in paths:
        click.echo(f"✅ {p}")
    click.echo(f"\n{len(paths)} reels generated.")


@cli.command()
@click.argument("campaign_name")
def schedule(campaign_name: str):
    """Start the scheduler daemon for automatic reel generation."""
    from .scheduler import start_scheduler

    settings = load_settings()
    campaign = load_campaign(campaign_name)

    async def _run():
        from .discord_bot import ReelBot

        bot_token = settings["discord"]["bot_token"]
        channel_id = settings["discord"]["review_channel_id"]

        bot = ReelBot(channel_id, _on_approve, _on_delete, _on_edit_segment, _on_save_clips)

        async def gen_job(name):
            await generate_one_reel(name, post_to_discord=True, use_groq=True)

        start_scheduler(campaign_name, settings, campaign, gen_job)

        # Run the Discord bot (blocks forever, scheduler runs in background)
        click.echo("🤖 AutoReels scheduler + Discord bot running. Ctrl+C to stop.")
        await bot.start(bot_token)

    asyncio.run(_run())


@cli.command()
@click.argument("campaign_name")
def status(campaign_name: str):
    """Show today's reel status for a campaign."""
    reels = get_today_reels(campaign_name)
    if not reels:
        click.echo("No reels generated today.")
        return
    for r in reels:
        click.echo(
            f"  {r['reel_id']}  |  {r['status']:15s}  |  {r['theme']}  |  attempt {r['attempt']}"
        )


@cli.command()
def bot():
    """Run just the Discord bot (for reviewing pending reels)."""
    settings = load_settings()
    bot_token = settings["discord"]["bot_token"]
    channel_id = settings["discord"]["review_channel_id"]

    if not bot_token:
        click.echo("❌ DISCORD_BOT_TOKEN not set in .env.local")
        sys.exit(1)

    from .discord_bot import ReelBot

    reel_bot = ReelBot(channel_id, _on_approve, _on_delete, _on_edit_segment, _on_save_clips)
    click.echo("🤖 Discord bot running. Ctrl+C to stop.")
    asyncio.run(reel_bot.start(bot_token))


@cli.command()
@click.argument("campaign_name", required=False)
@click.option("--search", "-s", default=None, help="Search clips by keyword")
def library(campaign_name: str | None, search: str | None):
    """Browse the saved clip library."""
    if search:
        clips = search_library_clips(search)
    elif campaign_name:
        clips = get_library_clips(campaign=campaign_name)
    else:
        clips = get_library_clips()

    if not clips:
        click.echo("No clips in library." + (" Try a different search." if search else ""))
        return

    click.echo(f"\n📚 Clip Library ({len(clips)} clips)\n")
    click.echo(f"{'ID':<10} {'Campaign':<12} {'Theme':<20} {'Prompt':<40} {'Tags'}")
    click.echo("─" * 100)
    for c in clips:
        prompt_short = (c["prompt"][:37] + "...") if len(c["prompt"]) > 40 else c["prompt"]
        tags = c["tags"] or ""
        click.echo(f"{c['clip_id']:<10} {c['campaign']:<12} {c['theme']:<20} {prompt_short:<40} {tags}")

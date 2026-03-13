"""Discord bot — posts reels for review with full editing workflow.

Actions per reel:
  ✅ Approve    — mark for upload (auto-uploads if Meta API configured)
  🗑️ Delete     — discard reel and all generated media
  ✏️ Edit       — regenerate specific segments; opens an interactive edit flow
  💾 Save Clips — save individual AI video clips to the reusable clip library
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

import discord
from discord import Interaction, SelectOption
from discord.ui import View, Button, Select, Modal as DiscordModal, TextInput

from .tracker import get_reel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: build a readable storyboard summary for Discord
# ---------------------------------------------------------------------------

def _storyboard_summary(storyboard: dict) -> str:
    """Return a numbered segment list for the Discord message."""
    if not storyboard or "segments" not in storyboard:
        return "_No storyboard data_"
    lines = []
    for i, seg in enumerate(storyboard["segments"]):
        st = seg["type"]
        dur = seg.get("duration", "?")
        if st == "video_clip":
            prompt = seg.get("prompt", "")[:80]
            overlay = seg.get("text_overlay", "")
            desc = f"🎥 AI Video — _{prompt}…_"
            if overlay:
                desc += f' + overlay: "{overlay}"'
        elif st == "title_card":
            desc = f'🏷️ Title — "{seg.get("title", "")}"'
        elif st == "text_slide":
            desc = f'📝 Text — "{seg.get("text", "")}"'
        elif st == "cta_slide":
            desc = f'📣 CTA — "{seg.get("cta_text", "")}"'
        else:
            desc = f"❓ {st}"
        lines.append(f"**{i + 1}.** {desc}  `({dur}s)`")
    return "\n".join(lines)


def _get_video_segments(storyboard: dict) -> list[tuple[int, dict]]:
    """Return list of (index, segment) for video_clip segments."""
    if not storyboard or "segments" not in storyboard:
        return []
    return [
        (i, seg) for i, seg in enumerate(storyboard["segments"])
        if seg.get("type") == "video_clip"
    ]


# ---------------------------------------------------------------------------
# Helper: post the edited reel back to Discord
# ---------------------------------------------------------------------------

async def _post_edit_result(
    interaction: Interaction,
    result: tuple[Path, dict] | None,
    reel_id: str,
    campaign_name: str,
):
    """After an edit callback, re-post the updated reel to Discord."""
    if result is None:
        # Error already reported by the callback via interaction.followup
        return

    new_path, updated_sb = result
    reel = get_reel(reel_id)
    theme_name = reel["theme"] if reel else "unknown"

    bot = interaction.client
    if hasattr(bot, "update_reel_message"):
        await bot.update_reel_message(
            reel_id=reel_id,
            reel_path=new_path,
            storyboard=updated_sb,
            campaign_name=campaign_name,
            theme_name=theme_name,
        )
        await interaction.followup.send(
            f"✅ Segment updated! Recomposited reel posted below.", ephemeral=True,
        )
    else:
        await interaction.followup.send(
            f"✅ Segment updated, but couldn't re-post (bot method missing).", ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class ReelReviewView(View):
    """Main review view — Approve / Delete / Edit / Save Clips."""

    def __init__(
        self,
        reel_id: str,
        reel_path: Path,
        campaign_name: str,
        storyboard: dict | None,
        on_approve: Callable,
        on_delete: Callable,
        on_edit_segment: Callable,
        on_save_clips: Callable,
    ):
        super().__init__(timeout=None)
        self.reel_id = reel_id
        self.reel_path = reel_path
        self.campaign_name = campaign_name
        self.storyboard = storyboard or {}
        self._on_approve = on_approve
        self._on_delete = on_delete
        self._on_edit_segment = on_edit_segment
        self._on_save_clips = on_save_clips

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="✅", row=0)
    async def approve(self, interaction: Interaction, button: Button):
        await interaction.response.edit_message(
            content=f"✅ **Approved** — `{self.reel_id}`\nQueued for upload…",
            view=None,
        )
        try:
            await self._on_approve(self.reel_id, self.reel_path, self.campaign_name)
            await interaction.followup.send(f"🚀 `{self.reel_id}` published!")
        except Exception as e:
            logger.exception("Upload failed for %s", self.reel_id)
            await interaction.followup.send(f"⚠️ Upload failed: {e}")

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.red, emoji="🗑️", row=0)
    async def delete(self, interaction: Interaction, button: Button):
        await interaction.response.edit_message(
            content=f"🗑️ **Deleted** — `{self.reel_id}` and all media discarded.",
            view=None,
        )
        await self._on_delete(self.reel_id)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.blurple, emoji="✏️", row=0)
    async def edit(self, interaction: Interaction, button: Button):
        if not self.storyboard or "segments" not in self.storyboard:
            await interaction.response.send_message(
                "❌ No storyboard data — this reel can't be edited.", ephemeral=True,
            )
            return

        segments = self.storyboard["segments"]
        options = []
        for i, seg in enumerate(segments):
            label = f"Seg {i+1}: {seg['type']}"
            if seg["type"] == "video_clip":
                desc = (seg.get("prompt", "")[:95] + "…") if len(seg.get("prompt", "")) > 95 else seg.get("prompt", "")
            elif seg["type"] == "title_card":
                desc = seg.get("title", "")
            elif seg["type"] == "text_slide":
                desc = seg.get("text", "")
            elif seg["type"] == "cta_slide":
                desc = seg.get("cta_text", "")
            else:
                desc = seg["type"]
            options.append(SelectOption(
                label=label[:100], description=desc[:100], value=str(i),
            ))

        view = EditSegmentSelectView(
            reel_id=self.reel_id,
            reel_path=self.reel_path,
            campaign_name=self.campaign_name,
            storyboard=self.storyboard,
            on_edit_segment=self._on_edit_segment,
            segment_options=options,
        )
        await interaction.response.send_message(
            f"✏️ **Edit `{self.reel_id}`** — Select the segment to redo:",
            view=view, ephemeral=True,
        )

    @discord.ui.button(label="Save Clips", style=discord.ButtonStyle.grey, emoji="💾", row=0)
    async def save_clips(self, interaction: Interaction, button: Button):
        video_segs = _get_video_segments(self.storyboard)
        if not video_segs:
            await interaction.response.send_message(
                "❌ No AI video clips found in this reel.", ephemeral=True,
            )
            return

        options = []
        for idx, seg in video_segs:
            prompt = seg.get("prompt", "")
            label = f"Seg {idx+1}: AI Video"
            desc = (prompt[:95] + "…") if len(prompt) > 95 else prompt
            options.append(SelectOption(
                label=label[:100], description=desc[:100], value=str(idx),
            ))

        view = SaveClipSelectView(
            reel_id=self.reel_id,
            campaign_name=self.campaign_name,
            storyboard=self.storyboard,
            on_save_clips=self._on_save_clips,
            clip_options=options,
        )
        await interaction.response.send_message(
            f"💾 **Save clips from `{self.reel_id}`** — Select clips to save to library:",
            view=view, ephemeral=True,
        )


class EditSegmentSelectView(View):
    """Dropdown to pick which segment to redo."""

    def __init__(
        self,
        reel_id: str,
        reel_path: Path,
        campaign_name: str,
        storyboard: dict,
        on_edit_segment: Callable,
        segment_options: list[SelectOption],
    ):
        super().__init__(timeout=120)
        self.reel_id = reel_id
        self.reel_path = reel_path
        self.campaign_name = campaign_name
        self.storyboard = storyboard
        self._on_edit_segment = on_edit_segment

        self.select = Select(
            placeholder="Choose a segment to redo…",
            options=segment_options,
            min_values=1,
            max_values=1,
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: Interaction):
        seg_idx = int(self.select.values[0])
        seg = self.storyboard["segments"][seg_idx]

        if seg["type"] == "video_clip":
            # Show modal for new prompt or let auto-generate
            modal = EditVideoPromptModal(
                reel_id=self.reel_id,
                reel_path=self.reel_path,
                campaign_name=self.campaign_name,
                segment_index=seg_idx,
                current_prompt=seg.get("prompt", ""),
                on_edit_segment=self._on_edit_segment,
            )
            await interaction.response.send_modal(modal)
        elif seg["type"] == "text_slide":
            modal = EditTextSlideModal(
                reel_id=self.reel_id,
                reel_path=self.reel_path,
                campaign_name=self.campaign_name,
                segment_index=seg_idx,
                current_text=seg.get("text", ""),
                on_edit_segment=self._on_edit_segment,
            )
            await interaction.response.send_modal(modal)
        elif seg["type"] == "title_card":
            modal = EditTitleCardModal(
                reel_id=self.reel_id,
                reel_path=self.reel_path,
                campaign_name=self.campaign_name,
                segment_index=seg_idx,
                current_title=seg.get("title", ""),
                current_subtitle=seg.get("subtitle", ""),
                on_edit_segment=self._on_edit_segment,
            )
            await interaction.response.send_modal(modal)
        elif seg["type"] == "cta_slide":
            modal = EditCTAModal(
                reel_id=self.reel_id,
                reel_path=self.reel_path,
                campaign_name=self.campaign_name,
                segment_index=seg_idx,
                current_cta=seg.get("cta_text", ""),
                current_tagline=seg.get("tagline", ""),
                on_edit_segment=self._on_edit_segment,
            )
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message(
                f"❌ Can't edit segment type: {seg['type']}", ephemeral=True,
            )


# ---------------------------------------------------------------------------
# Edit modals — one per segment type
# ---------------------------------------------------------------------------

class EditVideoPromptModal(DiscordModal, title="Edit AI Video Segment"):
    new_prompt = TextInput(
        label="New Video Prompt",
        style=discord.TextStyle.paragraph,
        placeholder="Leave empty to auto-generate a new variation…",
        required=False,
        max_length=500,
    )

    def __init__(self, reel_id, reel_path, campaign_name, segment_index,
                 current_prompt, on_edit_segment):
        super().__init__()
        self.reel_id = reel_id
        self.reel_path = reel_path
        self.campaign_name = campaign_name
        self.segment_index = segment_index
        self.current_prompt = current_prompt
        self._on_edit_segment = on_edit_segment
        self.new_prompt.default = current_prompt[:4000]

    async def on_submit(self, interaction: Interaction):
        prompt = self.new_prompt.value.strip() or None
        await interaction.response.send_message(
            f"⏳ Re-generating segment {self.segment_index + 1} for `{self.reel_id}`…\n"
            f"This will regenerate the AI video clip and recomposite the reel.",
            ephemeral=True,
        )
        result = await self._on_edit_segment(
            self.reel_id, self.reel_path, self.campaign_name,
            self.segment_index, {"prompt": prompt}, interaction,
        )
        await _post_edit_result(interaction, result, self.reel_id, self.campaign_name)


class EditTextSlideModal(DiscordModal, title="Edit Text Slide"):
    new_text = TextInput(
        label="New Text",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=200,
    )

    def __init__(self, reel_id, reel_path, campaign_name, segment_index,
                 current_text, on_edit_segment):
        super().__init__()
        self.reel_id = reel_id
        self.reel_path = reel_path
        self.campaign_name = campaign_name
        self.segment_index = segment_index
        self._on_edit_segment = on_edit_segment
        self.new_text.default = current_text

    async def on_submit(self, interaction: Interaction):
        await interaction.response.send_message(
            f"⏳ Updating text slide {self.segment_index + 1}…", ephemeral=True,
        )
        result = await self._on_edit_segment(
            self.reel_id, self.reel_path, self.campaign_name,
            self.segment_index, {"text": self.new_text.value.strip()}, interaction,
        )
        await _post_edit_result(interaction, result, self.reel_id, self.campaign_name)


class EditTitleCardModal(DiscordModal, title="Edit Title Card"):
    new_title = TextInput(label="Title", required=True, max_length=100)
    new_subtitle = TextInput(label="Subtitle", required=False, max_length=200)

    def __init__(self, reel_id, reel_path, campaign_name, segment_index,
                 current_title, current_subtitle, on_edit_segment):
        super().__init__()
        self.reel_id = reel_id
        self.reel_path = reel_path
        self.campaign_name = campaign_name
        self.segment_index = segment_index
        self._on_edit_segment = on_edit_segment
        self.new_title.default = current_title
        self.new_subtitle.default = current_subtitle

    async def on_submit(self, interaction: Interaction):
        await interaction.response.send_message(
            f"⏳ Updating title card {self.segment_index + 1}…", ephemeral=True,
        )
        changes = {"title": self.new_title.value.strip()}
        if self.new_subtitle.value.strip():
            changes["subtitle"] = self.new_subtitle.value.strip()
        result = await self._on_edit_segment(
            self.reel_id, self.reel_path, self.campaign_name,
            self.segment_index, changes, interaction,
        )
        await _post_edit_result(interaction, result, self.reel_id, self.campaign_name)


class EditCTAModal(DiscordModal, title="Edit CTA Slide"):
    new_cta = TextInput(label="CTA Text", required=True, max_length=200)
    new_tagline = TextInput(label="Tagline", required=False, max_length=200)

    def __init__(self, reel_id, reel_path, campaign_name, segment_index,
                 current_cta, current_tagline, on_edit_segment):
        super().__init__()
        self.reel_id = reel_id
        self.reel_path = reel_path
        self.campaign_name = campaign_name
        self.segment_index = segment_index
        self._on_edit_segment = on_edit_segment
        self.new_cta.default = current_cta
        self.new_tagline.default = current_tagline

    async def on_submit(self, interaction: Interaction):
        await interaction.response.send_message(
            f"⏳ Updating CTA slide {self.segment_index + 1}…", ephemeral=True,
        )
        changes = {"cta_text": self.new_cta.value.strip()}
        if self.new_tagline.value.strip():
            changes["tagline"] = self.new_tagline.value.strip()
        result = await self._on_edit_segment(
            self.reel_id, self.reel_path, self.campaign_name,
            self.segment_index, changes, interaction,
        )
        await _post_edit_result(interaction, result, self.reel_id, self.campaign_name)


# ---------------------------------------------------------------------------
# Save clips view
# ---------------------------------------------------------------------------

class SaveClipSelectView(View):
    """Multi-select dropdown to pick AI clips to save to library."""

    def __init__(
        self,
        reel_id: str,
        campaign_name: str,
        storyboard: dict,
        on_save_clips: Callable,
        clip_options: list[SelectOption],
    ):
        super().__init__(timeout=120)
        self.reel_id = reel_id
        self.campaign_name = campaign_name
        self.storyboard = storyboard
        self._on_save_clips = on_save_clips

        max_sel = min(len(clip_options), 25)
        self.select = Select(
            placeholder="Select clips to save…",
            options=clip_options,
            min_values=1,
            max_values=max_sel,
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: Interaction):
        indices = [int(v) for v in self.select.values]
        await interaction.response.send_message(
            f"💾 Saving {len(indices)} clip(s) to library…", ephemeral=True,
        )
        saved = await self._on_save_clips(self.reel_id, self.campaign_name, indices)
        if saved:
            clip_list = "\n".join(f"  • `{c}`" for c in saved)
            await interaction.followup.send(
                f"✅ Saved to clip library:\n{clip_list}", ephemeral=True,
            )


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class ReelBot(discord.Client):
    """Discord bot for the reel review/edit/save workflow.

    Polls tracker DB for pending reels. Posts them with full storyboard
    breakdown and interactive buttons for approve/delete/edit/save.
    """

    def __init__(
        self,
        review_channel_id: int,
        on_approve: Callable,
        on_delete: Callable,
        on_edit_segment: Callable,
        on_save_clips: Callable,
        poll_interval: int = 10,
    ):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.review_channel_id = review_channel_id
        self._on_approve = on_approve
        self._on_delete = on_delete
        self._on_edit_segment = on_edit_segment
        self._on_save_clips = on_save_clips
        self._poll_interval = poll_interval
        self._ready_event = asyncio.Event()
        self._posted_reels: set[str] = set()
        # Map reel_id → discord message for edit updates
        self._reel_messages: dict[str, discord.Message] = {}

    async def on_ready(self):
        logger.info("Discord bot logged in as %s", self.user)
        self._ready_event.set()
        self.loop.create_task(self._poll_pending_reels())

    async def wait_until_really_ready(self):
        await self._ready_event.wait()

    async def _poll_pending_reels(self):
        from .tracker import get_all_pending_reels, update_reel_status, get_reel_storyboard

        await self.wait_until_really_ready()
        logger.info("Started polling for pending reels (every %ds)", self._poll_interval)

        while not self.is_closed():
            try:
                pending = get_all_pending_reels()
                for reel in pending:
                    reel_id = reel["reel_id"]
                    if reel_id in self._posted_reels:
                        continue

                    reel_path = Path(reel["file_path"])
                    if not reel_path.exists():
                        continue

                    storyboard = get_reel_storyboard(reel_id)
                    msg = await self.post_reel_for_review(
                        reel_id=reel_id,
                        reel_path=reel_path,
                        campaign_name=reel["campaign"],
                        theme_name=reel["theme"],
                        prompt=reel["prompt"],
                        storyboard=storyboard,
                    )
                    self._reel_messages[reel_id] = msg
                    update_reel_status(reel_id, "in_review")
                    self._posted_reels.add(reel_id)
            except Exception:
                logger.exception("Error polling pending reels")

            await asyncio.sleep(self._poll_interval)

    async def post_reel_for_review(
        self,
        reel_id: str,
        reel_path: Path,
        campaign_name: str,
        theme_name: str,
        prompt: str,
        storyboard: dict | None = None,
    ) -> discord.Message:
        await self.wait_until_really_ready()
        channel = self.get_channel(self.review_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.review_channel_id)

        view = ReelReviewView(
            reel_id=reel_id,
            reel_path=reel_path,
            campaign_name=campaign_name,
            storyboard=storyboard,
            on_approve=self._on_approve,
            on_delete=self._on_delete,
            on_edit_segment=self._on_edit_segment,
            on_save_clips=self._on_save_clips,
        )

        file_size_mb = reel_path.stat().st_size / (1024 * 1024)

        # Build rich message with storyboard breakdown
        sb_summary = _storyboard_summary(storyboard) if storyboard else "_Legacy single-clip reel_"
        seg_count = len(storyboard.get("segments", [])) if storyboard else 1
        video_count = len(_get_video_segments(storyboard)) if storyboard else 1

        content = (
            f"🎬 **New Reel — {campaign_name}**\n"
            f"**ID:** `{reel_id}`\n"
            f"**Theme:** {theme_name}\n"
            f"**Size:** {file_size_mb:.1f} MB  •  "
            f"**Segments:** {seg_count}  •  **AI Clips:** {video_count}\n\n"
            f"**Storyboard:**\n{sb_summary}\n"
        )

        # Discord has a 2000 char limit — truncate if needed
        if len(content) > 1900:
            content = content[:1900] + "\n…_(truncated)_"

        msg = await channel.send(
            content=content,
            file=discord.File(str(reel_path)),
            view=view,
        )
        logger.info("Posted reel %s to Discord for review (%d segments)", reel_id, seg_count)
        return msg

    async def update_reel_message(
        self, reel_id: str, reel_path: Path, storyboard: dict | None,
        campaign_name: str, theme_name: str,
    ):
        """Re-upload the reel after an edit and update the Discord message."""
        msg = self._reel_messages.get(reel_id)
        channel = self.get_channel(self.review_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.review_channel_id)

        view = ReelReviewView(
            reel_id=reel_id,
            reel_path=reel_path,
            campaign_name=campaign_name,
            storyboard=storyboard,
            on_approve=self._on_approve,
            on_delete=self._on_delete,
            on_edit_segment=self._on_edit_segment,
            on_save_clips=self._on_save_clips,
        )

        file_size_mb = reel_path.stat().st_size / (1024 * 1024)
        sb_summary = _storyboard_summary(storyboard) if storyboard else ""
        seg_count = len(storyboard.get("segments", [])) if storyboard else 1

        content = (
            f"🎬 **Reel Updated — {campaign_name}** _(edited)_\n"
            f"**ID:** `{reel_id}`\n"
            f"**Theme:** {theme_name}\n"
            f"**Size:** {file_size_mb:.1f} MB  •  **Segments:** {seg_count}\n\n"
            f"**Storyboard:**\n{sb_summary}\n"
        )
        if len(content) > 1900:
            content = content[:1900] + "\n…_(truncated)_"

        new_msg = await channel.send(
            content=content,
            file=discord.File(str(reel_path)),
            view=view,
        )
        self._reel_messages[reel_id] = new_msg

        # Try to delete or update old message
        if msg:
            try:
                await msg.edit(content=f"♻️ _Reel `{reel_id}` was edited — see updated version below._", view=None)
            except Exception:
                pass

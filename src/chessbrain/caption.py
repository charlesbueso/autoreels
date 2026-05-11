"""Per-platform caption generation via Groq."""
from __future__ import annotations

from pydantic import BaseModel, Field

from chessbrain.brain import memory
from chessbrain.content_types.base import PostPlan
from chessbrain.content_types.planner import build_user_prompt, plan_with_retry, voice_block
from chessbrain.settings import get_settings


class CaptionSet(BaseModel):
    instagram: str = Field(..., description="120-220 chars; includes 5-10 hashtags at end")
    tiktok: str = Field(..., description="≤150 chars; 3-5 hashtags inline")
    x: str = Field(..., description="≤270 chars; 1-3 hashtags")
    reddit_title: str = Field(..., description="≤90 chars; no hashtags; sentence-case")
    reddit_body: str = Field(..., description="80-300 words; conversational; no marketing")
    youtube_shorts: str = Field(..., description="title (≤60 chars) + 2 lines description, separated by '|||'")
    facebook: str = Field(..., description="100-180 chars")


SYSTEM = voice_block() + "\n\nWrite platform-tailored captions for the post described."


def generate(plan: PostPlan) -> CaptionSet:
    s = get_settings()
    hashtags = " ".join(s.brand["hashtags"]["default"])
    user = build_user_prompt(
        task=(
            f"Post hook: \"{plan.hook}\"\n"
            f"Summary: {plan.summary}\n"
            f"Content type: {plan.content_type}\n"
            f"CTA URL: {s.brand['cta_short']}\n"
            f"Default hashtags: {hashtags}\n\n"
            "Tailor the caption to each platform's culture. Reddit body must read like a "
            "human enthusiast wrote it, not marketing. Avoid emoji unless the post is a meme."
        ),
        forbidden_kinds=("caption",),
        extra_instructions="Do not include the URL in TikTok or Reddit body (Reddit removes them anyway).",
    )
    captions = plan_with_retry(system=SYSTEM, user=user, schema=CaptionSet)
    # Log the captions to the brain memory so future posts don't paraphrase.
    for v in [captions.instagram, captions.tiktok, captions.x, captions.reddit_title, captions.facebook]:
        memory.log_idea("caption", v, post_slug=plan.slug, content_type=plan.content_type)
    return captions

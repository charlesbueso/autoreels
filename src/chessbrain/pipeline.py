"""End-to-end orchestration for a single post.

generate_one_post(slot):
    plan -> AI images (per slide) -> render slides -> caption -> save -> log to brain.
"""
from __future__ import annotations

from datetime import date as _date
from pathlib import Path

from PIL import Image

from chessbrain import caption as caption_mod
from chessbrain import director
from chessbrain.brain import calendar as cal_mod
from chessbrain.brain import memory
from chessbrain.brain.calendar import CalendarSlot
from chessbrain.content_types.base import PostPlan, SlideSpec
from chessbrain.imagegen import client as imagegen_client
from chessbrain.imagegen.base import RenderRequest
from chessbrain.publish import local as publish_local
from chessbrain.publish import manifest
from chessbrain.settings import get_settings


def _resolve_image(slide: SlideSpec, post_slug: str) -> Path | None:
    """If the slide needs an AI image, render or fetch it from cache."""
    if slide.preset_image_path:
        p = Path(slide.preset_image_path)
        return p if p.exists() else None
    if not slide.image_prompt:
        return None
    s = get_settings()
    refs: list[Path] = []
    if slide.use_mascot_ref:
        mascot = s.assets_dir / "mascot" / "base.png"
        if mascot.exists():
            refs.append(mascot)
    model = slide.image_model or s.runtime["imagegen"]["default_model"]
    req = RenderRequest(
        prompt=slide.image_prompt,
        aspect=slide.aspect or "4:5",
        model=model,
        reference_images=refs,
        seed=slide.seed,
        extra=slide.extra or {},
    )
    result = imagegen_client.render(req, post_slug=post_slug)
    return result.path


def generate_one_post(slot: CalendarSlot) -> Path:
    """Generate, render, and save the post for a single calendar slot.

    Returns the output directory path.
    """
    module = director.dispatch(slot)

    # 1. Plan (LLM, with novelty gate inside the content type).
    plan: PostPlan = module.plan(slot)
    plan.series = slot.series
    plan.series_param = slot.series_param

    # 2. Image generation per slide.
    ai_images: list[Path | None] = [_resolve_image(s, plan.slug) for s in plan.slides]

    # 3. Render slides.
    rendered: list[Image.Image] = []
    total = len(plan.slides)
    for i, (spec, img_path) in enumerate(zip(plan.slides, ai_images)):
        canvas = module.render_slide(plan, spec, i, total, ai_image=img_path)
        rendered.append(canvas)

    # 4. Captions.
    captions = caption_mod.generate(plan)

    # 5. Save to disk.
    today = _date.fromisoformat(slot.date)
    out_dir = publish_local.save_post(d=today, plan=plan, slides=rendered, captions=captions)

    # 6. Log all generated text to the marketing brain so future posts dodge it.
    pairs: list[tuple[str, str]] = [("hook", plan.hook), ("summary", plan.summary)]
    for spec in plan.slides:
        if spec.image_prompt:
            pairs.append(("image_prompt", spec.image_prompt))
        if spec.text:
            for v in spec.text.values():
                if isinstance(v, str) and len(v) > 8:
                    pairs.append(("slide_line", v))
    memory.log_many(pairs, post_slug=plan.slug, content_type=plan.content_type)

    # 7. Update calendar status.
    cal_mod.update_status(slot.id, status="ready", post_slug=plan.slug)

    # 8. Refresh today's manifest.
    try:
        manifest.render_day(today)
    except Exception:
        pass

    return out_dir

# Chess Brain – daily content engine

Generates 1–3 social posts per day promoting [Chess Brain](https://chessbrain.coach),
the Lichess AI coach Discord bot.

Posts are carousels, single-image memes, puzzle walkthroughs, opening traps,
endgame lessons, GM quotes, mascot scenes, and Discord product demos — all with
consistent brand styling and an anti-repetition memory so nothing ever feels recycled.

## How it works

1. **Calendar planner** (`config/calendar.yaml` + `config/series.yaml`) assigns a
   `content_type` and optional series parameter to every (date, slot 0–2) cell.
2. **Content-type modules** (`src/chessbrain/content_types/`) call Groq
   (`llama-3.3-70b-versatile`) in JSON mode and return a `PostPlan` with `SlideSpec`s.
   Chess facts (opening traps, endgame positions) are read from hand-verified
   catalogs in `config/knowledge/` — the LLM only writes marketing copy.
3. **Anti-repetition brain** (`data/brain.sqlite`, table `idea_log`) stores an
   embedding for every hook, slide line, image prompt, and caption ever produced.
   A cosine-similarity gate (threshold 0.85) blocks near-repeats.
4. **Image generation** via fal.ai, routed per task:
   | model key | fal slug | use |
   |---|---|---|
   | `nano_banana` | `fal-ai/nano-banana/edit` | mascot-consistent edits |
   | `flux_dev` | `fal-ai/flux/dev` | fast variations |
   | `flux_pro` | `fal-ai/flux-pro/v1.1` | covers & hero shots |
   | `ideogram` | `fal-ai/ideogram/v2` | text-in-image |
5. **Render** stack (Pillow) composes 1080×1350 carousel slides with brand
   colours, Poppins typography, pagination dots, and a watermark.
6. **Captions** are written per platform (IG / TikTok / X / Reddit / FB / YouTube Shorts)
   and saved alongside the images.
7. **Output** lands in `output/YYYY-MM-DD/{slug}/` with `01.png`…`0N.png`,
   `caption.md`, and `meta.json`. A per-day `manifest.html` previews everything.
   The `output/` folder is **git-ignored** — generated assets stay local only.

## Project layout

```
config/
  brand.yaml                 brand colours, fonts, CTA url
  calendar.yaml              date → (slot, content_type, series_param) grid
  series.yaml                recurring series definitions & rotations
  visual_style.yaml          mascot style lock, layout tokens
  content_types/             per-type YAML configs (tone, hooks, etc.)
  knowledge/
    opening_traps.yaml       9 verified traps (PGN validated)
    endgame_concepts.yaml    9 endgame concepts (FEN validated)
scripts/
  verify_opening_traps.py    validates every PGN move in the catalog
  verify_endgame_concepts.py validates every FEN in the catalog
  seed_idea_pools.py         warm-starts the similarity gate
  download_lichess_puzzles.py
src/chessbrain/
  content_types/             one module per content type
  render/                    Pillow layout engine
  imagegen/                  fal.ai client wrapper
  brain/                     SQLite memory, calendar, series, Reddit inspo
```

## Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env    # then fill in your API keys
chessbrain init
python scripts/download_lichess_puzzles.py
chessbrain plan-month --days 30
chessbrain calendar list --days 7
```

### Required environment variables (`.env`)

```
GROQ_API_KEY=...
FAL_KEY=...
OPENAI_API_KEY=...        # for embeddings
```

## Daily workflow

```powershell
chessbrain generate                        # next planned slot today
chessbrain generate --slot 2026-05-12:0   # specific date:slot
chessbrain regenerate <slug>               # redo an existing post
chessbrain today                           # open today's manifest in browser
chessbrain week                            # weekly overview
chessbrain schedule                        # run forever (3×/day daemon)
```

## Brain / memory inspection

```powershell
chessbrain brain stats
chessbrain brain forbid --kind hook --value "level up your chess"
chessbrain imagegen cost --days 30
```

## Verified knowledge catalogs

Chess-factual content uses hand-curated YAML catalogs to prevent LLM hallucination.
Run the validators after adding or editing entries:

```powershell
python scripts/verify_opening_traps.py     # must show N/N verified
python scripts/verify_endgame_concepts.py  # must show 27/27 positions verified
```

## Seeding the brain (optional but recommended)

To make the similarity gate effective from day one, seed ~80 hooks per content type:

```powershell
python scripts/seed_idea_pools.py --per-type 80
```

## Mascot

The Chess Brain mascot is a **pink brain with cerebral folds**, big round black eyes,
wide smile, rosy cheeks, short pink limbs, and a black chess king balanced on its head.
Reference image: `assets/mascot/base.png`.
Generate the 12 standard poses from `scripts/mascot_pose_prompts.md` once and save
them to `assets/mascot/poses/` — they will be picked up automatically.

## Cost estimate

At 1–3 posts/day using `nano_banana` for most slides:
- ~$0.04 × 4 slides × 1–3 posts ≈ $0.15–$0.50/day (~$5–$15/month)
- Monthly fal budget cap: `config/settings.yaml` → `imagegen.monthly_budget_usd`
- Groq + OpenAI embeddings: pennies/day


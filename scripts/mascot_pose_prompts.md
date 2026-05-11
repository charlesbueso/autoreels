# Mascot pose prompts (Flux Kontext / Nano Banana, image-to-image)

Use `assets/mascot/base.png` as the reference image. Save outputs to
`assets/mascot/poses/{tag}.png` at 1024x1024.

Style suffix to append to every prompt:
> flat vector illustration, soft cream background #F7F2EA, bold clean line art,
> gentle pastel palette with deep navy #1F2A44 accents and warm gold #C49A3C
> highlights, single subject, centered

| tag                | prompt                                                                 |
|--------------------|------------------------------------------------------------------------|
| thumbs_up          | the chess-piece mascot giving a confident thumbs up, smiling           |
| thinking           | the chess-piece mascot stroking its chin, looking pensive              |
| shocked            | the chess-piece mascot wide-eyed, mouth open in surprise               |
| magnifying_glass   | the chess-piece mascot peering through a magnifying glass              |
| pointing_up        | the chess-piece mascot raising a finger, like making a point           |
| sleeping           | the chess-piece mascot snoring with a 'Z' floating, leaning on a clock |
| trophy             | the chess-piece mascot lifting a small trophy overhead                 |
| fist_pump          | the chess-piece mascot with one fist raised in celebration             |
| shrug              | the chess-piece mascot shrugging, palms up                             |
| lecturing          | the chess-piece mascot at a chalkboard, holding a piece of chalk       |
| sweating           | the chess-piece mascot sweating, eyes nervously sliding sideways       |
| zen                | the chess-piece mascot meditating cross-legged with a halo glow        |

For each, set: model=`fal-ai/gemini-flash-edit` (Nano Banana), reference image
= `assets/mascot/base.png`, output aspect = 1:1, seed = stable per pose so we
can re-render consistently.

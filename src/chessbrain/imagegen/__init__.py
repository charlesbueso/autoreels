"""fal.ai image generation — multi-provider gateway.

Models:
  - nano_banana   (Gemini 2.5 Flash Image)  ~ $0.039/img — default, mascot-consistent
  - flux_dev      (Flux dev)                ~ $0.025/img — fast non-mascot scenes
  - flux_pro      (Flux 1.1 [pro] Ultra)    ~ $0.06/img  — hero/cover
  - ideogram_v3   (Ideogram 3)              ~ $0.06/img  — text-in-image

All providers share a SHA-keyed PNG cache in ``data/image_cache/`` so
re-generating with identical prompt+seed+model is free.
"""

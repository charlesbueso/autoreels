"""Modal serverless inference — Wan2.1-T2V-14B on H100 GPU.

Deploy:   modal deploy modal_app.py
Test:     modal run modal_app.py
"""

import io
import modal

# --- Modal app definition ---
app = modal.App("autoreels-wan14b")

MODEL_ID = "Wan-AI/Wan2.1-T2V-14B-Diffusers"
MODEL_CACHE_DIR = "/cache/wan14b"


def download_model():
    """Download model weights at image build time (not at container start)."""
    from diffusers import AutoencoderKLWan, WanPipeline
    import torch

    print(f"Downloading {MODEL_ID}...")
    AutoencoderKLWan.from_pretrained(
        MODEL_ID, subfolder="vae", torch_dtype=torch.float32,
        cache_dir=MODEL_CACHE_DIR,
    )
    WanPipeline.from_pretrained(
        MODEL_ID, torch_dtype=torch.bfloat16,
        cache_dir=MODEL_CACHE_DIR,
    )
    print("Download complete ✓")


# Build the image with model weights baked in.
# The HF_TOKEN secret is available during build for authenticated downloads.
wan_image = (
    modal.Image.debian_slim(python_version="3.11")
    .env({"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
    .pip_install(
        "torch>=2.5",
        "diffusers>=0.37",
        "transformers>=4.40",
        "accelerate>=0.30",
        "sentencepiece",
        "imageio[ffmpeg]",
        "imageio-ffmpeg",
    )
    .run_function(
        download_model,
        secrets=[modal.Secret.from_name("huggingface-token")],
    )
)


@app.cls(
    image=wan_image,
    gpu="H100",
    timeout=900,
    scaledown_window=120,
)
class WanGenerator:
    """Serverless Wan2.1-14B text-to-video generator."""

    @modal.enter()
    def load_model(self):
        """Load from pre-cached weights (downloaded at image build time)."""
        import torch
        torch.set_float32_matmul_precision("high")
        from diffusers import AutoencoderKLWan, WanPipeline
        from diffusers.schedulers.scheduling_unipc_multistep import (
            UniPCMultistepScheduler,
        )

        print(f"Loading {MODEL_ID} from image cache…")

        vae = AutoencoderKLWan.from_pretrained(
            MODEL_ID,
            subfolder="vae",
            torch_dtype=torch.float32,
            cache_dir=MODEL_CACHE_DIR,
        )

        self.pipe = WanPipeline.from_pretrained(
            MODEL_ID,
            vae=vae,
            torch_dtype=torch.bfloat16,
            cache_dir=MODEL_CACHE_DIR,
        )

        # flow_shift=5.0 for 720P, 3.0 for 480P
        self.pipe.scheduler = UniPCMultistepScheduler.from_config(
            self.pipe.scheduler.config, flow_shift=3.0
        )

        self.pipe.to("cuda")

        # VAE tiling for faster decode with many frames
        self.pipe.vae.enable_tiling()

        print("Wan2.1-14B loaded on H100 ✓")

    @modal.method()
    def generate(
        self,
        prompt: str,
        negative_prompt: str = "worst quality, blurry, jittery, distorted, watermark",
        width: int = 832,
        height: int = 480,
        num_frames: int = 49,
        num_inference_steps: int = 35,
        guidance_scale: float = 7.0,
        fps: int = 16,
        seed: int = 42,
    ) -> bytes:
        """Generate a video and return raw MP4 bytes."""
        import torch
        import imageio
        import numpy as np

        generator = torch.Generator(device="cuda").manual_seed(seed)

        print(
            f"Generating: {width}x{height}, {num_frames} frames, "
            f"{num_inference_steps} steps, seed={seed}"
        )

        output = self.pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            height=height,
            width=width,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=generator,
            output_type="np",
        )

        frames = output.frames[0]
        if isinstance(frames, np.ndarray):
            if frames.max() <= 1.0:
                video_np = (frames * 255).astype(np.uint8)
            else:
                video_np = frames.astype(np.uint8)
        else:
            video_np = np.stack([np.array(f) for f in frames])

        # Encode to MP4 in memory
        buf = io.BytesIO()
        with imageio.get_writer(buf, format="mp4", fps=fps) as writer:
            for frame in video_np:
                writer.append_data(frame)
        buf.seek(0)
        print(f"Done — {len(buf.getvalue()) / 1024:.0f} KB MP4")
        return buf.getvalue()


# Quick test entrypoint: `modal run modal_app.py`
@app.local_entrypoint()
def main():
    gen = WanGenerator()
    mp4_bytes = gen.generate.remote(
        prompt="A golden sunrise over misty mountains, cinematic slow pan, 4K quality",
        num_frames=49,
        num_inference_steps=30,
        seed=12345,
    )
    with open("test_modal_output.mp4", "wb") as f:
        f.write(mp4_bytes)
    print(f"Saved test_modal_output.mp4 ({len(mp4_bytes) / 1024:.0f} KB)")

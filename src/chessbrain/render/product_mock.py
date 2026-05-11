"""Procedurally-rendered Discord channel mockup as a slide."""
from __future__ import annotations

from PIL import Image, ImageDraw

from chessbrain import chessboard
from chessbrain.render import canvas as canvas_mod
from chessbrain.render import effects, layouts, typography
from chessbrain.settings import get_settings

# Discord-ish dark palette
DISCORD_BG = "#313338"
DISCORD_PANEL = "#2B2D31"
DISCORD_TEXT = "#DBDEE1"
DISCORD_MUTED = "#949BA4"
DISCORD_ROLE_GOLD = "#F0B232"
DISCORD_LINK = "#00A8FC"
DISCORD_EMBED = "#2B2D31"
DISCORD_EMBED_BORDER_GOLD = "#C49A3C"


def render_discord_mock(
    *,
    title: str,
    messages: list[dict],          # [{author, role_color, time, text, embed?}]
    channel_name: str = "chess",
    ctx: layouts.SlideContext,
) -> Image.Image:
    s = get_settings()
    palette = s.brand["palette"]
    img = canvas_mod.carousel_canvas()
    margin = s.runtime["canvas"]["safe_margin"]

    # Title strip
    typography.draw_block(
        img,
        title,
        role="display",
        xy=(margin, margin + 80),
        box=(img.width - margin * 2, 200),
        fill=palette["ink"],
        align="left",
        max_size=72,
        min_size=40,
        line_spacing=1.06,
    )

    # Discord panel
    panel_w = img.width - margin * 2
    panel_h = img.height - margin - 320 - 40
    panel = Image.new("RGB", (panel_w, panel_h), DISCORD_BG)
    pd = ImageDraw.Draw(panel)

    # Channel header
    header_h = 70
    pd.rectangle((0, 0, panel_w, header_h), fill=DISCORD_PANEL)
    ft_chan = typography.font("display_alt", 32)
    pd.text((28, 18), f"#  {channel_name}", font=ft_chan, fill=DISCORD_TEXT)

    # Messages
    y = header_h + 30
    ft_author = typography.font("display_alt", 28)
    ft_time = typography.font("body_light", 22)
    ft_msg = typography.font("body", 28)
    for msg in messages:
        if y > panel_h - 60:
            break
        avatar_d = 56
        pd.ellipse((28, y, 28 + avatar_d, y + avatar_d), fill="#5865F2")
        pd.text((40, y + 12), msg.get("author", "?")[:1].upper(), font=ft_author, fill="white")
        ax = 28 + avatar_d + 18
        author = msg.get("author", "ChessBrain")
        role_color = msg.get("role_color", DISCORD_ROLE_GOLD)
        pd.text((ax, y + 4), author, font=ft_author, fill=role_color)
        aw = ft_author.getbbox(author)[2]
        time_str = msg.get("time", "Today at 12:34 PM")
        pd.text((ax + aw + 14, y + 12), time_str, font=ft_time, fill=DISCORD_MUTED)
        text_y = y + 44
        text = msg.get("text", "")
        ft, lines, _ = typography.auto_fit_font(
            text,
            "body",
            max_width=panel_w - ax - 40,
            max_height=400,
            max_size=28,
            min_size=22,
            line_spacing=1.22,
        )
        for line in lines:
            pd.text((ax, text_y), line, font=ft, fill=DISCORD_TEXT)
            text_y += int((ft.getbbox("Ag")[3] - ft.getbbox("Ag")[1]) * 1.22)
        embed = msg.get("embed")
        if embed:
            ew = panel_w - ax - 40
            board_fen = embed.get("board_fen")
            board_arrow = embed.get("board_arrow")  # ("e2","e4","green") optional
            board_last = embed.get("board_last")    # "e2e4" optional
            # Embed shape: gold border on left, dark fill, title, desc, optional board image.
            ft_et = typography.font("display_alt", 28)
            desc_text = embed.get("description", "")
            ft_e, e_lines, _ = typography.auto_fit_font(
                desc_text,
                "body",
                max_width=ew - 48,
                max_height=240,
                max_size=24,
                min_size=18,
                line_spacing=1.22,
            )
            line_h = int((ft_e.getbbox("Ag")[3] - ft_e.getbbox("Ag")[1]) * 1.22)
            desc_h = line_h * min(len(e_lines), 4)
            board_img = None
            board_size = 0
            if board_fen:
                try:
                    arrows = [board_arrow] if board_arrow else None
                    board_path = chessboard.render_board(
                        fen=board_fen,
                        last_move=board_last,
                        arrows=arrows,
                        size=512,
                    )
                    board_size = min(360, ew - 48)
                    board_img = Image.open(board_path).convert("RGB").resize(
                        (board_size, board_size), Image.LANCZOS
                    )
                except Exception:
                    board_img = None
            board_block_h = (board_size + 16) if board_img else 0
            eh = 24 + 32 + 12 + desc_h + board_block_h + 24  # padding+title+gap+desc+board+pad
            eh = max(eh, 140)
            pd.rectangle((ax, text_y + 8, ax + ew, text_y + 8 + eh), fill=DISCORD_EMBED)
            pd.rectangle((ax, text_y + 8, ax + 6, text_y + 8 + eh), fill=DISCORD_EMBED_BORDER_GOLD)
            pd.text((ax + 24, text_y + 24), embed.get("title", ""), font=ft_et, fill=DISCORD_TEXT)
            ey = text_y + 64
            for line in e_lines[:4]:
                pd.text((ax + 24, ey), line, font=ft_e, fill=DISCORD_MUTED)
                ey += line_h
            if board_img:
                bx = ax + 24
                by = ey + 12
                # Outer subtle frame
                pd.rectangle((bx - 2, by - 2, bx + board_size + 2, by + board_size + 2), fill="#1F2A44")
                panel.paste(board_img, (bx, by))
            text_y += eh + 8
        y = text_y + 28

    # Round corners + shadow + paste onto canvas
    panel = effects.round_corners(panel, radius=28)
    img_rgba = img.convert("RGBA")
    sh = effects.drop_shadow(panel.convert("RGBA"), blur=30, opacity=0.18)
    img_rgba.alpha_composite(sh, (margin - (sh.width - panel_w) // 2, margin + 280 - (sh.height - panel_h) // 2))
    img = img_rgba.convert("RGB")
    return layouts.finalize(img, ctx)

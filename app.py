import asyncio
import concurrent.futures
import json
import os
import re
import subprocess
import tempfile
import textwrap
from io import BytesIO

import edge_tts
import imageio_ffmpeg
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop Edition",
    page_icon="🎬",
    layout="centered",
)

if "duration" not in st.session_state:
    st.session_state.duration = "20 giây"

def run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)

async def generate_tts_mp3(text: str, voice: str, out_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)

def get_unicode_font(size: int):
    candidate_fonts = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidate_fonts:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()

def generate_script_with_gemini(
    api_key: str,
    product_input: str,
    product_note: str,
    duration_str: str,
    reviewer_style: str,
):
    seconds = int(duration_str.split()[0])
    num_scenes = max(2, min(6, seconds // 5))
    target_words = int(seconds * 2.6)

    if not api_key.strip():
        return [
            {
                "caption": "Đừng lướt qua nếu bạn đang tìm món này!",
                "voiceover": "Khoan đã! Nếu bạn đang tìm một sản phẩm vừa chất lượng vừa tiết kiệm thì xem hết clip này nha.",
            },
            {
                "caption": "Thiết kế gọn đẹp, dùng cực kỳ tiện",
                "voiceover": f"Đây là em {product_note or 'sản phẩm hot trend'} đang làm mưa làm gió trên TikTok Shop mấy hôm nay.",
            },
            {
                "caption": "Nhấn giỏ hàng góc trái chốt đơn ngay!",
                "voiceover": "Hiện tại đang có mã giảm giá cực hời trong giỏ hàng góc trái, bấm mua ngay kẻo hết nha!",
            },
        ][:num_scenes]

    prompt = f"""
Bạn là chuyên gia viết kịch bản video bán hàng TikTok Shop triệu view bằng tiếng Việt.
Hãy viết 1 kịch bản video ngắn khoảng {seconds} giây (tổng cộng khoảng {target_words} từ tiếng Việt tự nhiên).

Thông tin đầu vào:
- Link / Sản phẩm: {product_input}
- Mô tả: {product_note if product_note else "Sản phẩm tiện ích hot trên TikTok Shop"}
- Phong cách: {reviewer_style}

Yêu cầu chia đúng {num_scenes} cảnh liên tiếp: Hook -> Nỗi đau -> Giải pháp -> Kêu gọi mua hàng.
Trả về ĐÚNG định dạng JSON là một danh sách các object, mỗi object gồm 2 khóa:
- "caption": chữ hiển thị ngắn gọn trên màn hình (tối đa 10 chữ)
- "voiceover": lời thoại đọc thành tiếng (tự nhiên, không dùng emoji)
"""
    client = genai.Client(api_key=api_key.strip())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )
    raw = response.text.strip()
    raw = re.sub(r"^```json\s*|\s*```$", "", raw, flags=re.MULTILINE)
    return json.loads(raw)

def render_vertical_frame(
    bg_image: Image.Image | None,
    title_text: str,
    caption_text: str,
    reviewer_badge: str,
    out_png_path: str,
):
    W, H = 1080, 1920
    if bg_image is not None:
        img = ImageOps.exif_transpose(bg_image).convert("RGB")
        bg = ImageOps.fit(img, (W, H), method=Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
        overlay = Image.new("RGBA", (W, H), (10, 15, 30, 110))
        canvas = Image.alpha_composite(bg.convert("RGBA"), overlay)

        fg = img.copy()
        fg.thumbnail((960, 1120), Image.Resampling.LANCZOS)
        fw, fh = fg.size
        canvas.paste(fg, ((W - fw) // 2, (H - fh) // 2 - 40))
    else:
        canvas = Image.new("RGBA", (W, H), (15, 23, 42, 255))

    draw = ImageDraw.Draw(canvas)
    font_badge = get_unicode_font(34)
    draw.rounded_rectangle([(60, 110), (W - 60, 195)], radius=28, fill=(15, 23, 42, 200))
    draw.text((W // 2, 152), f"TIKTOK SHOP REVIEW  •  {reviewer_badge}", font=font_badge, fill=(52, 211, 153, 255), anchor="mm")

    font_sub = get_unicode_font(52)
    wrapped_caption = textwrap.fill(caption_text, width=24)
    bbox = draw.multiline_textbbox((0, 0), wrapped_caption, font=font_sub, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    
    box_y_center = 1480
    draw.rounded_rectangle([max(50, (W - tw)//2 - 48), box_y_center - th//2 - 32, min(W - 50, (W + tw)//2 + 48), box_y_center + th//2 + 32], radius=30, fill=(0, 0, 0, 195))
    draw.multiline_text((W // 2, box_y_center), wrapped_caption, font=font_sub, fill=(255, 255, 255, 255), anchor="mm", align="center")
    canvas.convert("RGB").save(out_png_path, format="PNG")

def build_tiktok_video(scenes, voice_id, reviewer_badge, product_title, images):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmpdir:
        segment_paths = []
        for idx, scene in enumerate(scenes):
            voice_text = scene.get("voiceover", "").strip()
            caption_text = scene.get("caption", voice_text).strip()
            if not voice_text:
                continue

            mp3_path = os.path.join(tmpdir, f"audio_{idx}.mp3")
            png_path = os.path.join(tmpdir, f"frame_{idx}.png")
            seg_path = os.path.join(tmpdir, f"seg_{idx}.mp4")

            run_async(generate_tts_mp3(voice_text, voice_id, mp3_path))
            img_for_scene = images[idx % len(images)] if images else None
            render_vertical_frame(img_for_scene, product_title, caption_text, reviewer_badge, png_path)

            cmd_seg = [
                ffmpeg_exe, "-y", "-loop", "1", "-i", png_path, "-i", mp3_path,
                "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
                "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k",
                "-shortest", seg_path
            ]
            subprocess.run(cmd_seg, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segment_paths.append(seg_path)

        concat_txt = os.path.join(tmpdir, "segments.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in segment_paths:
                f.write(f"file '{p.replace(os.sep, '/')}'\n")

        final_mp4 = os.path.join(tmpdir, "final_tiktok_9_16.mp4")
        subprocess.run([ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", final_mp4], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(final_mp4, "rb") as f:
            return f.read()

# GIAO DIỆN
st.title("🎬 BẮP AI VIDEO - TIKTOK SHOP")

product_links = st.text_area("Link sản phẩm TikTok Shop", placeholder="Dán link sản phẩm tại đây...")
duration_str = st.selectbox("Thời lượng video", ["10 giây", "20 giây", "30 giây", "40 giây"])
st.session_state.duration = duration_str

col1, col2 = st.columns(2)
with col1:
    select_female = st.checkbox("Chọn Nữ Reviewer (Hoài My)", value=True)
with col2:
    select_

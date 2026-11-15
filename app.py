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
from PIL import Image, ImageDraw, ImageFilter

st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop Editor",
    page_icon="🎬",
    layout="centered",
)

# -------------------------------------------------------------
# HÀM HỖ TRỢ XỬ LÝ TTS & VIDEO
# -------------------------------------------------------------
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def generate_tts_mp3(text: str, voice: str, out_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)

def render_vertical_frame(
    bg_image: Image.Image,
    title_text: str,
    caption_text: str,
    reviewer_badge: str,
    out_png_path: str,
):
    target_w, target_h = 1080, 1920
    base = bg_image.convert("RGB").resize((target_w, target_h), Image.Resampling.LANCZOS)
    base = base.filter(ImageFilter.GaussianBlur(radius=20))
    
    # Đắp lớp phủ tối cho dễ nhìn chữ
    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 140))
    base.paste(Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB"))
    
    base.save(out_png_path, format="PNG")

def build_tiktok_video(
    scenes: list[dict],
    audio_id: str,
    reviewer_badge: str,
    product_title: str,
    images: list[Image.Image],
) -> bytes:
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
            
            # 1. Tạo giọng đọc
            run_async(generate_tts_mp3(voice_text, audio_id, mp3_path))
            
            # 2. Tạo khung hình
            img_for_scene = images[idx % len(images)] if images else Image.new("RGB", (540, 960), (30, 30, 30))
            render_vertical_frame(
                bg_image=img_for_scene,
                title_text=product_title,
                caption_text=caption_text,
                reviewer_badge=reviewer_badge,
                out_png_path=png_path,
            )
            
            # 3. Ghép ảnh và audio thành video segment
            cmd_seg = [
                ffmpeg_exe,
                "-y",
                "-loop", "1",
                "-i", png_path,
                "-i", mp3_path,
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                seg_path
            ]
            subprocess.run(cmd_seg, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            segment_paths.append(seg_path)
        
        if not segment_paths:
            raise ValueError("Không có phân cảnh nào được tạo thành công.")
            
        list_txt_path = os.path.join(tmpdir, "list.txt")
        with open(list_txt_path, "w", encoding="utf-8") as f:
            for sp in segment_paths:
                f.write(f"file '{sp}'\n")
                
        final_mp4_path = os.path.join(tmpdir, "final.mp4")
        cmd_concat = [
            ffmpeg_exe,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_txt_path,
            "-c", "copy",
            final_mp4_path
        ]
        subprocess.run(cmd_concat, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        with open(final_mp4_path, "rb") as f:
            return f.read()

# -------------------------------------------------------------
# GIAO DIỆN CHÍNH STREAMLIT
# -------------------------------------------------------------
st.markdown("<h2 style='text-align: center; color: #ff4b4b;'>🎬 BẮP AI VIDEO</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: gray;'>Trợ lý tự động hóa sản xuất video TikTok Shop</p>", unsafe_allow_html=True)

product_links = st.text_area("Link sản phẩm", placeholder="Dán link sản phẩm Shopee/TikTok vào đây...", height=85)
reviewer_badge = st.text_input("Huy hiệu Reviewer", value="🌟 Bắp Review Chính Hãng")
product_title = st.text_input("Tiêu đề video hiển thị", value="Sản phẩm hot nhất hôm nay")

uploaded_files = st.file_uploader("Tải lên ảnh sản phẩm (chọn nhiều ảnh)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

if st.button("🚀 BẮT ĐẦU TẠO VIDEO", type="primary", use_container_width=True):
    if not product_links:
        st.warning("Vui lòng nhập link sản phẩm trước khi tạo video!")
    else:
        st.info("Hệ thống đang khởi tạo các bước xử lý nội dung...")
        # Giao diện mẫu xử lý cơ bản
        st.success("Đã sẵn sàng kết nối AI cấu hình video!")

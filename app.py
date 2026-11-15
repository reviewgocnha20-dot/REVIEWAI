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

# ==========================================
# CẤU HÌNH TRANG & GIAO DIỆN MOBILE-FIRST
# ==========================================
st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop Edition",
    page_icon="🎬",
    layout="centered",
)

if "duration" not in st.session_state:
    st.session_state.duration = "20 giây"

st.markdown("""
    <style>
    .stApp {
        background-color: #f1f5f9;
        color: #0f172a;
    }
    .header-card {
        background: linear-gradient(135deg, #162033 0%, #0f172a 100%);
        padding: 22px 20px;
        border-radius: 20px;
        margin-bottom: 20px;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.15);
    }
    .section-label {
        color: #475569;
        font-weight: 700;
        font-size: 12px;
        letter-spacing: 0.5px;
        margin-bottom: 8px;
        margin-top: 14px;
    }
    .stTextArea textarea, .stTextInput input {
        background-color: #ffffff !important;
        color: #0f172a !important;
        border-radius: 14px !important;
        border: 1px solid #e2e8f0 !important;
    }
    div[data-testid="column"] button {
        width: 100%;
        border-radius: 12px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        padding: 10px 4px !important;
    }
    .generate-btn button {
        width: 100%;
        background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
        color: #ffffff !important;
        border-radius: 16px !important;
        font-weight: 700 !important;
        font-size: 15px !important;
        padding: 14px !important;
        border: none !important;
        box-shadow: 0 6px 16px rgba(37, 99, 235, 0.3) !important;
    }
    .avatar-box {
        background-color: #ffffff;
        border-radius: 16px;
        padding: 12px;
        border: 1px solid #e2e8f0;
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)


# ==========================================
# CÁC HÀM XỬ LÝ AI, GIỌNG ĐỌC & DỰNG VIDEO
# ==========================================
def run_async(coro):
    """Chạy hàm async an toàn bên trong Streamlit."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


async def generate_tts_mp3(text: str, voice: str, out_path: str):
    """Tạo file giọng đọc tiếng Việt miễn phí qua Edge-TTS."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


def get_unicode_font(size: int):
    """Tìm font hỗ trợ tiếng Việt có dấu trên Windows / macOS / Linux."""
    candidate_fonts = [
        # Windows
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        # Linux / Streamlit Cloud
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
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
    """Gọi Gemini API (Free Tier) tạo kịch bản chia từng cảnh."""
    seconds = int(duration_str.split()[0])
    num_scenes = max(2, min(6, seconds // 5))
    target_words = int(seconds * 2.6)

    # Nếu chưa nhập API Key -> trả về kịch bản mẫu để chạy thử được ngay
    if not api_key.strip():
        sample = [
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
        ]
        return sample[:num_scenes]

    prompt = f"""
Bạn là chuyên gia viết kịch bản video bán hàng TikTok Shop triệu view bằng tiếng Việt.
Hãy viết 1 kịch bản video ngắn khoảng {seconds} giây (tổng cộng khoảng {target_words} từ tiếng Việt tự nhiên, dễ đọc thành tiếng).

Thông tin đầu vào:
- Link / Mã sản phẩm: {product_input}
- Mô tả thêm của người bán: {product_note if product_note else "Sản phẩm tiện ích đang hot trên TikTok Shop"}
- Phong cách nhân vật: {reviewer_style}

Yêu cầu chia đúng {num_scenes} cảnh liên tiếp theo mạch: Hook gây chú ý -> Nỗi đau/Nhu cầu -> Giải pháp/Công dụng -> Kêu gọi bấm giỏ hàng góc trái.
Trả về ĐÚNG định dạng JSON là một danh sách các object, mỗi object gồm 2 khóa:
- "caption": chữ hiển thị ngắn gọn trên màn hình (tối đa 10 chữ)
- "voiceover": lời thoại đọc thành tiếng (tự nhiên, không dùng emoji, không ghi chú trong ngoặc)
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
    scenes = json.loads(raw)
    return  scenes


def render_vertical_frame(
    bg_image: Image.Image | None,
    title_text: str,
    caption_text: str,
    reviewer_badge: str,
    out_png_path: str,
):
    """Tạo khung hình 1080x1920 (9:16) có nền mờ, ảnh sản phẩm ở giữa và phụ đề TikTok."""
    W, H = 1080, 1920

    if bg_image is not None:
        img = ImageOps.exif_transpose(bg_image).convert("RGB")
        # Nền mờ tràn khung 9:16
        bg = ImageOps.fit(img, (W, H), method=Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
        # Làm tối nhẹ nền để nổi bật sản phẩm & chữ
        overlay = Image.new("RGBA", (W, H), (10, 15, 30, 110))
        canvas = Image.alpha_composite(bg.convert("RGBA"), overlay)

        # Ảnh sản phẩm sắc nét đặt ở giữa
        fg = img.copy()
        fg.thumbnail((960, 1120), Image.Resampling.LANCZOS)
        fw, fh = fg.size
        fx = (W - fw) // 2
        fy = (H - fh) // 2 - 40
        canvas.paste(fg, (fx, fy))
    else:
        # Nếu không tải ảnh -> tạo nền gradient tối sang trọng
        canvas = Image.new("RGBA", (W, H), (15, 23, 42, 255))
        draw_bg = ImageDraw.Draw(canvas)
        draw_bg.rounded_rectangle(
            [(90, 420), (W - 90, 1320)],
            radius=48,
            fill=(30, 41, 59, 255),
            outline=(59, 130, 246, 200),
            width=4,
        )
        font_center = get_unicode_font(46)
        wrapped_prod = textwrap.fill(title_text, width=22)
        draw_bg.multiline_text(
            (W // 2, 870),
            wrapped_prod,
            font=font_center,
            fill=(255, 255, 255, 255),
            anchor="mm",
            align="center",
        )

    draw = ImageDraw.Draw(canvas)

    # Thanh badge phía trên cùng
    font_badge = get_unicode_font(34)
    draw.rounded_rectangle([(60, 110), (W - 60, 195)], radius=28, fill=(15, 23, 42, 200))
    draw.text(
        (W // 2, 152),
        f"TIKTOK SHOP REVIEW  •  {reviewer_badge}",
        font=font_badge,
        fill=(52, 211, 153, 255),
        anchor="mm",
    )

    # Hộp phụ đề nổi bật ở phần dưới (tránh vùng chữ mặc định của TikTok)
    font_sub = get_unicode_font(52)
    wrapped_caption = textwrap.fill(caption_text, width=24)
    bbox = draw.multiline_textbbox((0, 0), wrapped_caption, font=font_sub, align="center")
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad_x, pad_y = 48, 32
    box_y_center = 1480
    x1 = max(50, (W - tw) // 2 - pad_x)
    x2 = min(W - 50, (W + tw) // 2 + pad_x)
    y1 = box_y_center - th // 2 - pad_y
    y2 = box_y_center + th // 2 + pad_y

    draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=30, fill=(0, 0, 0, 195))
    draw.multiline_text(
        (W // 2, box_y_center),
        wrapped_caption,
        font=font_sub,
        fill=(255, 255, 255, 255),
        anchor="mm",
        align="center",
    )

    canvas.convert("RGB").save(out_png_path, format="PNG")


def build_tiktok_video(
    scenes: list[dict],
    voice_id: str,
    reviewer_badge: str,
    product_title: str,
    images: list[Image.Image],
) -> bytes:
    """Ghép Edge-TTS + khung hình Pillow thành file MP4 chuẩn 9:16 bằng FFmpeg."""
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

            # 1. Tạo giọng đọc cho từng cảnh
            run_async(generate_tts_mp3(voice_text, voice_id, mp3_path))

            # 2. Tạo ảnh khung hình 9:16 kèm phụ đề của cảnh đó
            img_for_scene = images[idx % len(images)] if images else None
            render_vertical_frame(
                bg_image=img_for_scene,
                title_text=product_title,
                caption_text=caption_text,
                reviewer_badge=reviewer_badge,
                out_png_path=png_path,
            )

            # 3. Ghép ảnh + audio thành 1 đoạn MP4 khớp thời lượng chính xác
            cmd_seg = [
                ffmpeg_exe,
                "-y",
                "-loop", "1",
                "-i", png_path,
                "-i", mp3_path,
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-preset", "veryfast",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
                "-shortest",
                seg_path,
            ]
            subprocess.run(cmd_seg, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segment_paths.append(seg_path)

        # 4. Nối tất cả các đoạn thành video hoàn chỉnh chuẩn iPhone / TikTok
        concat_txt = os.path.join(tmpdir, "segments.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in segment_paths:
                safe_p = p.replace("\\", "/")
                f.write(f"file '{safe_p}'\n")

        final_mp4 = os.path.join(tmpdir, "final_tiktok_9_16.mp4")
        cmd_concat = [
            ffmpeg_exe,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_txt,
            "-c", "copy",
            "-movflags", "+faststart",
            final_mp4,
        ]
        subprocess.run(cmd_concat, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        with open(final_mp4, "rb") as f:
            return f.read()


# ==========================================
# GIAO DIỆN NGƯỜI DÙNG
# ==========================================
st.markdown("""
    <div class="header-card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <h3 style="margin:0; color:#ffffff; font-weight:800; font-size:22px;">BẮP AI VIDEO</h3>
                <p style="margin:2px 0 10px 0; color:#94a3b8; font-size:12px; font-weight:600;">TIKTOK SHOP EDITION</p>
            </div>
            <div style="font-size:28px;">🎬</div>
        </div>
        <span style="background-color:#064e3b; color:#34d399; padding:4px 10px; border-radius:8px; font-size:11px; font-weight:700;">
            FREE-FIRST SYSTEM
        </span>
        <h2 style="margin:14px 0 6px 0; font-size:18px; color:#ffffff; font-weight:700;">
            Từ link sản phẩm đến video quảng cáo
        </h2>
        <p style="margin:0; color:#cbd5e1; font-size:12px; line-height:1.4;">
            Tạo kịch bản · Giọng Việt Edge-TTS · Phụ đề tự động · Video 9:16
        </p>
    </div>
""", unsafe_allow_html=True)

st.markdown("<h4 style='margin-bottom:6px; color:#0f172a;'>Giao diện thao tác trên iPhone</h4>", unsafe_allow_html=True)

# 1. Link sản phẩm
st.markdown("<div class='section-label'>LINK SẢN PHẨM TIKTOK SHOP (Mỗi dòng = 1 video)</div>", unsafe_allow_html=True)
product_links = st.text_area(
    "Link sản phẩm",
    placeholder="🔗 Dán 1 hoặc nhiều link sản phẩm tại đây (mỗi dòng 1 link)...",
    height=85,
    label_visibility="collapsed",
)

# 2. Thời lượng
st.markdown("<div class='section-label'>THỜI LƯỢNG</div>", unsafe_allow_html=True)
durations = ["10 giây", "20 giây", "30 giây", "40 giây"]
cols = st.columns(4)
for idx, d in enumerate(durations):
    with cols[idx]:
        btn_type = "primary" if st.session_state.duration == d else "secondary"
        if st.button(d, key=f"dur_{d}", type=btn_type, use_container_width=True):
            st.session_state.duration = d
            st.rerun()


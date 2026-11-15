
import asyncio
import concurrent.futures
import json
import os
import re
import subprocess
import tempfile
import textwrap
from io import BytesIO

import streamlit as st

st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop",
    page_icon="🎬",
    layout="centered"
)

# Thư viện được cài ở môi trường ứng dụng, KHÔNG pip install khi đang chạy.
try:
    import edge_tts
    import imageio_ffmpeg
    from PIL import (
        Image, ImageDraw, ImageFilter,
        ImageFont, ImageOps
    )
except ModuleNotFoundError as e:
    st.error(
        f"Máy chủ đang thiếu thư viện: {e.name}. "
        "Ứng dụng cần được cài thư viện trong môi trường khởi động."
    )
    st.stop()

# Gemini là tùy chọn, không có vẫn chạy bằng kịch bản mẫu.
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ModuleNotFoundError:
    GEMINI_AVAILABLE = False


# ---------------- CẤU HÌNH ----------------

st.title("🎬 BẮP AI VIDEO")
st.caption("Tạo video review sản phẩm TikTok Shop • Khung dọc 9:16")

st.info(
    "Dán link sản phẩm, nhập mô tả và tải ảnh sản phẩm lên. "
    "Ứng dụng dựng video từ ảnh bạn cung cấp."
)


# ---------------- HÀM HỖ TRỢ ----------------

def run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def make_voice(text, voice, output):
    tts = edge_tts.Communicate(text=text, voice=voice)
    await tts.save(output)


def get_font(size, bold=False):
    paths = []

    if bold:
        paths.append(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        )

    paths.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
    ])

    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass

    return ImageFont.load_default()


def make_script(api_key, product_name, description, duration, style):
    seconds = int(duration.split()[0])
    count = max(2, min(6, seconds // 5))

    # Không có API key thì sử dụng kịch bản mẫu.
    if not api_key.strip():
        name = product_name.strip() or "sản phẩm này"

        templates = [
            {
                "caption": "Khoan lướt qua nhé!",
                "voiceover": (
                    f"Khoan lướt qua nha! Hôm nay mình giới thiệu "
                    f"{name} đến mọi người."
                )
            },
            {
                "caption": "Cùng xem sản phẩm",
                "voiceover": (
                    "Đầu tiên mình cùng xem thiết kế và những "
                    "điểm đáng chú ý của sản phẩm này nhé."
                )
            },
            {
                "caption": "Trải nghiệm tiện lợi",
                "voiceover": (
                    "Bạn có thể tham khảo hình ảnh và thông tin "
                    "sản phẩm để xem có phù hợp với nhu cầu không nha."
                )
            },
            {
                "caption": "Tham khảo ngay",
                "voiceover": (
                    "Nhớ kiểm tra phân loại, kích thước và thông tin "
                    "trước khi chọn mua nhé."
                )
            },
            {
                "caption": "Xem tại giỏ hàng",
                "voiceover": (
                    "Nếu thấy phù hợp, bạn có thể nhấn vào giỏ hàng "
                    "để xem thông tin sản phẩm nha."
                )
            },
            {
                "caption": "Cảm ơn bạn",
                "voiceover": "Cảm ơn mọi người đã xem video nhé!"
            }
        ]

        return templates[:count]

    if not GEMINI_AVAILABLE:
        raise RuntimeError(
            "Chưa có thư viện Google Gemini. "
            "Hãy để trống API key để dùng kịch bản mẫu."
        )

    client = genai.Client(api_key=api_key.strip())

    prompt = f"""
Bạn là chuyên gia viết kịch bản video TikTok Shop tiếng Việt.

Thời lượng: {seconds} giây.
Số cảnh: {count}.
Tên sản phẩm: {product_name}
Mô tả: {description}
Phong cách: {style}

Viết lời thoại tự nhiên, thu hút.
Không tự bịa giá, thông số hoặc khuyến mãi.
Chia cảnh theo trình tự: mở đầu, giới thiệu,
trải nghiệm, lời kêu gọi xem sản phẩm.

Chỉ trả về JSON dạng danh sách:
[
  {{"caption":"Tiêu đề ngắn","voiceover":"Lời thoại"}}
]
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7
        )
    )

    raw = (response.text or "").strip()
    raw = re.sub(
        r"^\s*```(?:json)?\s*|\s*```\s*$",
        "",
        raw,
        flags=re.IGNORECASE
    )

    data = json.loads(raw)

    if isinstance(data, dict):
        data = data.get("scenes") or data.get("script") or []

    if not isinstance(data, list):
        raise ValueError("Kịch bản AI không đúng định dạng.")

    scenes = []

    for item in data:
        if not isinstance(item, dict):
            continue

        voiceover = str(item.get("voiceover", "")).strip()
        caption = str(item.get("caption", "")).strip()

        if voiceover:
            scenes.append({
                "caption": caption or voiceover[:60],
                "voiceover": voiceover
            })

    if not scenes:
        raise ValueError("AI chưa tạo được lời thoại.")

    return scenes


# ---------------- TẠO ẢNH CHO VIDEO ----------------

def make_frame(image, caption, reviewer, output):
    width, height = 1080, 1920

    original = ImageOps.exif_transpose(image).convert("RGB")

    background = ImageOps.fit(
        original,
        (width, height),
        method=Image.Resampling.LANCZOS
    )

    background = background.filter(
        ImageFilter.GaussianBlur(25)
    )

    overlay = Image.new(
        "RGBA",
        (width, height),
        (8, 12, 24, 115)
    )

    canvas = Image.alpha_composite(
        background.convert("RGBA"),
        overlay
    )

    foreground = original.copy()
    foreground.thumbnail((940, 1120), Image.Resampling.LANCZOS)

    x = (width - foreground.width) // 2
    y = (height - foreground.height) // 2 - 50

    canvas.paste(foreground, (x, y))

    draw = ImageDraw.Draw(canvas)

    top_font = get_font(30, True)
    caption_font = get_font(54, True)

    draw.rounded_rectangle(
        (55, 85, width - 55, 175),
        radius=28,
        fill=(10, 18, 32, 220)
    )

    draw.text(
        (width // 2, 130),
        f"BẮP AI VIDEO • {reviewer}",
        font=top_font,
        fill="white",
        anchor="mm"
    )

    caption = textwrap.fill(caption.strip(), width=23)

    bbox = draw.multiline_textbbox(
        (0, 0),
        caption,
        font=caption_font,
        align="center"
    )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    center_y = 1510

    draw.rounded_rectangle(
        (
            max(40, (width - text_width) // 2 - 45),
            center_y - text_height // 2 - 35,
            min(width - 40, (width + text_width) // 2 + 45),
            center_y + text_height // 2 + 35
        ),
        radius=30,
        fill=(0, 0, 0, 205)
    )

    draw.multiline_text(
        (width // 2, center_y),
        caption,
        font=caption_font,
        fill="white",
        anchor="mm",
        align="center",
        spacing=12
    )

    canvas.convert("RGB").save(output, "PNG")


# ---------------- DỰNG VIDEO MP4 ----------------

def build_video(scenes, voice, reviewer, images):
    if not images:
        raise ValueError("Bạn chưa tải ảnh sản phẩm.")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    with tempfile.TemporaryDirectory() as folder:
        segments = []

        for i, scene in enumerate(scenes):
            audio = os.path.join(folder, f"audio_{i}.mp3")
            frame = os.path.join(folder, f"frame_{i}.png")
            video = os.path.join(folder, f"segment_{i}.mp4")

            voice_text = scene["voiceover"].strip()
            caption = scene["caption"].strip() or voice_text

            if not voice_text:
                continue

            run_async(make_voice(voice_text, voice, audio))

            image = images[i % len(images)]

            make_frame(
                image,
                caption,
                reviewer,
                frame
            )

            command = [
                ffmpeg, "-y",
                "-loop", "1",
                "-i", frame,
                "-i", audio,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-tune", "stillimage",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                video
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise RuntimeError(
                    "Lỗi dựng cảnh video: " + result.stderr[-1200:]
                )

            segments.append(video)

        if not segments:
            raise ValueError("Không có cảnh video hợp lệ.")

        concat_file = os.path.join(folder, "segments.txt")

        with open(concat_file, "w", encoding="utf-8") as f:
            for path in segments:
                safe_path = path.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        final_file = os.path.join(folder, "BAP_AI_VIDEO.mp4")

        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                final_file
            ],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Lỗi ghép video: " + result.stderr[-1500:]
            )

        with open(final_file, "rb") as f:
            return f.read()


# ---------------- GIAO DIỆN ----------------

product_link = st.text_area(
    "🔗 Link sản phẩm TikTok Shop",
    placeholder="Dán link sản phẩm tại đây..."
)

product_name = st.text_input(
    "📦 Tên sản phẩm",
    placeholder="Ví dụ: Khăn giấy rút..."
)

description = st.text_area(
    "📝 Mô tả sản phẩm",
    placeholder="Màu sắc, kích thước, chất liệu, công dụng..."
)

duration = st.selectbox(
    "⏱ Thời lượng video",
    ["10 giây", "20 giây", "30 giây", "40 giây"],
    index=1
)

reviewer = st.radio(
    "🎤 Người review",
    ["Nữ Reviewer - Hoài My", "Nam Reviewer - Nam Minh"],
    horizontal=True
)

if reviewer.startswith("Nữ"):
    voice = "vi-VN-HoaiMyNeural"
    reviewer_name = "HOÀI MY"
    style = "Nữ reviewer thân thiện, tự nhiên"
else:
    voice = "vi-VN-NamMinhNeural"
    reviewer_name = "NAM MINH"
    style = "Nam reviewer gần gũi, rõ ràng"

uploaded_files = st.file_uploader(
    "🖼 Tải ảnh sản phẩm",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True
)

if uploaded_files:
    st.caption(f"Đã chọn {len(uploaded_files)} ảnh.")
    columns = st.columns(min(3, len(uploaded_files)))

    for i, file in enumerate(uploaded_files):
        file.seek(0)
        with columns[i % len(columns)]:
            st.image(
                file,
                caption=file.name,
                use_container_width=True
            )

api_key = st.text_input(
    "🔑 Gemini API Key (không bắt buộc)",
    type="password",
    placeholder="Để trống dùng kịch bản mẫu"
)

st.caption(
    "Lưu ý: Link TikTok Shop hiện dùng làm thông tin tham khảo. "
    "Ứng dụng chưa tự tải ảnh hoặc đọc dữ liệu từ link."
)

# ---------------- NÚT TẠO VIDEO ----------------

if st.button(
    "🚀 BẮT ĐẦU TẠO VIDEO MP4",
    type="primary",
    use_container_width=True
):
    if not product_link.strip():
        st.warning("Vui lòng nhập link sản phẩm.")
    elif not uploaded_files:
        st.warning("Vui lòng tải ít nhất một ảnh sản phẩm.")
    else:
        try:
            with st.status(
                "🎬 Đang tạo video...",
                expanded=True
            ) as status:

                st.write("1. Đang tạo kịch bản...")
                scenes = make_script(
                    api_key,
                    product_name,
                    description,
                    duration,
                    style
                )

                st.write("2. Đang xử lý ảnh...")
                images = []

                for file in uploaded_files:
                    file.seek(0)

                    with Image.open(file) as image:
                        clean_image = ImageOps.exif_transpose(
                            image
                        ).convert("RGB").copy()

                        images.append(clean_image)

                st.write("3. Đang tạo giọng đọc tiếng Việt...")
                st.write("4. Đang dựng và ghép video MP4...")

                video_bytes = build_video(
                    scenes,
                    voice,
                    reviewer_name,
                    images
                )

                status.update(
                    label="🎉 Đã tạo video thành công!",
                    state="complete",
                    expanded=False
                )

            st.success("Video của bạn đã sẵn sàng!")
            st.video(video_bytes)

            st.download_button(
                "📥 TẢI VIDEO MP4",
                data=video_bytes,
                file_name="BAP_AI_VIDEO.mp4",
                mime="video/mp4",
                use_container_width=True
            )

            with st.expander("📄 Xem kịch bản video"):
                for i, scene in enumerate(scenes, 1):
                    st.markdown(
                        f"**Cảnh {i}: {scene['caption']}**"
                    )
                    st.write(scene["voiceover"])

        except Exception as error:
            st.error(f"Không tạo được video: {error}")

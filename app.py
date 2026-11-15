
import asyncio
import concurrent.futures
import json
import os
import re
import subprocess
import tempfile
import textwrap
from typing import Optional

import streamlit as st

st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop Edition",
    page_icon="🎬",
    layout="centered",
)

try:
    import edge_tts
    import imageio_ffmpeg
    from google import genai
    from google.genai import types
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except ModuleNotFoundError as error:
    st.error(
        f"Thiếu thư viện: {error.name}. "
        "Kiểm tra requirements.txt nằm cùng thư mục với app.py "
        "trên GitHub rồi khởi động lại Streamlit."
    )
    st.stop()


st.title("🎬 BẮP AI VIDEO - TIKTOK SHOP")
st.caption("Tạo video review sản phẩm dọc 9:16")
st.success("Bộ dựng video MP4 đã được tích hợp.")


def run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def make_voice(text, voice, output):
    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(output)


def get_font(size, bold=False):
    fonts = []
    if bold:
        fonts.append(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        )
    fonts.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ])

    for path in fonts:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass

    return ImageFont.load_default()


def clean_scenes(data):
    if isinstance(data, dict):
        data = data.get("scenes") or data.get("script") or []

    if not isinstance(data, list):
        raise ValueError("Kịch bản AI không đúng định dạng.")

    scenes = []
    for item in data:
        if not isinstance(item, dict):
            continue

        caption = str(item.get("caption", "")).strip()
        voiceover = str(item.get("voiceover", "")).strip()

        if voiceover:
            scenes.append({
                "caption": caption or voiceover[:60],
                "voiceover": voiceover
            })

    if not scenes:
        raise ValueError("Không tạo được lời thoại.")

    return scenes


def create_script(api_key, link, description, duration, style):
    seconds = int(duration.split()[0])
    count = max(2, min(6, seconds // 5))

    if not api_key.strip():
        name = description.strip() or "sản phẩm này"

        templates = [
            {
                "caption": "Khoan lướt qua nhé!",
                "voiceover": f"Khoan lướt qua nha! Hôm nay mình giới thiệu {name}."
            },
            {
                "caption": "Cùng xem sản phẩm",
                "voiceover": "Mình cùng xem thiết kế và những điểm đáng chú ý của sản phẩm này nhé."
            },
            {
                "caption": "Tham khảo trước khi mua",
                "voiceover": "Bạn nhớ xem kỹ hình ảnh, kích thước và thông tin sản phẩm trước khi chọn mua nha."
            },
            {
                "caption": "Xem tại giỏ hàng",
                "voiceover": "Nếu thấy phù hợp, bạn có thể nhấn vào giỏ hàng để kiểm tra giá hiện tại nhé."
            },
            {
                "caption": "Chọn theo nhu cầu",
                "voiceover": "Hãy chọn phân loại phù hợp với nhu cầu sử dụng của mình nha."
            },
            {
                "caption": "Hẹn gặp lại",
                "voiceover": "Cảm ơn bạn đã xem video. Hẹn gặp lại trong video tiếp theo nhé."
            }
        ]

        return templates[:count]

    client = genai.Client(api_key=api_key.strip())

    prompt = f"""
Bạn là chuyên gia viết kịch bản TikTok Shop tiếng Việt.

Thời lượng: {seconds} giây.
Số cảnh: {count}.
Link tham khảo: {link}
Mô tả sản phẩm: {description or "Chưa có mô tả"}
Phong cách: {style}

Viết tự nhiên, hấp dẫn, không tự bịa thông số,
giá bán, công dụng hoặc khuyến mãi.

Trả về JSON dạng danh sách:
[
  {{"caption":"Tiêu đề ngắn","voiceover":"Lời thoại tiếng Việt"}}
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

    return clean_scenes(json.loads(raw))


def make_frame(image, caption, reviewer, output):
    W, H = 1080, 1920

    original = ImageOps.exif_transpose(image).convert("RGB")

    background = ImageOps.fit(
        original,
        (W, H),
        method=Image.Resampling.LANCZOS
    )

    background = background.filter(
        ImageFilter.GaussianBlur(25)
    )

    overlay = Image.new(
        "RGBA",
        (W, H),
        (8, 12, 24, 120)
    )

    canvas = Image.alpha_composite(
        background.convert("RGBA"),
        overlay
    )

    foreground = original.copy()
    foreground.thumbnail((940, 1120))

    x = (W - foreground.width) // 2
    y = (H - foreground.height) // 2 - 50
    canvas.paste(foreground, (x, y))

    draw = ImageDraw.Draw(canvas)

    font_top = get_font(30, True)
    font_caption = get_font(54, True)

    draw.rounded_rectangle(
        (55, 85, W - 55, 175),
        radius=28,
        fill=(10, 18, 32, 220)
    )

    draw.text(
        (W // 2, 130),
        f"BẮP AI VIDEO • {reviewer}",
        font=font_top,
        fill="white",
        anchor="mm"
    )

    caption = textwrap.fill(caption.strip(), width=23)

    bbox = draw.multiline_textbbox(
        (0, 0),
        caption,
        font=font_caption,
        align="center"
    )

    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    cy = 1510

    draw.rounded_rectangle(
        (
            max(40, (W - tw) // 2 - 45),
            cy - th // 2 - 35,
            min(W - 40, (W + tw) // 2 + 45),
            cy + th // 2 + 35
        ),
        radius=30,
        fill=(0, 0, 0, 205)
    )

    draw.multiline_text(
        (W // 2, cy),
        caption,
        font=font_caption,
        fill="white",
        anchor="mm",
        align="center",
        spacing=12
    )

    canvas.convert("RGB").save(output, "PNG")


def build_video(scenes, voice, reviewer, images):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    with tempfile.TemporaryDirectory() as folder:
        segments = []

        for i, scene in enumerate(scenes):
            audio = os.path.join(folder, f"audio_{i}.mp3")
            frame = os.path.join(folder, f"frame_{i}.png")
            video = os.path.join(folder, f"segment_{i}.mp4")

            voice_text = scene["voiceover"].strip()
            caption = scene["caption"].strip() or voice_text

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
                video
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr[-1200:])

            segments.append(video)

        concat_file = os.path.join(folder, "segments.txt")

        with open(concat_file, "w", encoding="utf-8") as f:
            for path in segments:
                f.write(f"file '{path}'\n")

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
            raise RuntimeError(result.stderr[-1500:])

        with open(final_file, "rb") as f:
            return f.read()


# ---------------- GIAO DIỆN ----------------

product_link = st.text_area(
    "🔗 Link sản phẩm TikTok Shop",
    placeholder="Dán link sản phẩm tại đây..."
)

description = st.text_area(
    "📝 Mô tả sản phẩm",
    placeholder="Tên, màu sắc, kích thước, chất liệu, công dụng..."
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
    cols = st.columns(min(3, len(uploaded_files)))

    for i, file in enumerate(uploaded_files):
        file.seek(0)
        with cols[i % len(cols)]:
            st.image(
                file,
                caption=file.name,
                use_container_width=True
            )

api_key = st.text_input(
    "Gemini API Key (không bắt buộc)",
    type="password",
    placeholder="Để trống dùng kịch bản mẫu"
)

st.info(
    "Ứng dụng hiện dựng video từ ảnh bạn tải lên. "
    "Link TikTok Shop chưa tự trích xuất ảnh và thông tin sản phẩm."
)

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
            with st.status("Đang tạo video...", expanded=True) as status:
                st.write("1. Đang tạo kịch bản...")

                scenes = create_script(
                    api_key,
                    product_link,
                    description,
                    duration,
                    style
                )

                st.write("2. Đang xử lý ảnh...")
                images = []

                for file in uploaded_files:
                    file.seek(0)
                    with Image.open(file) as im:
                        images.append(
                            ImageOps.exif_transpose(im).convert("RGB").copy()
                        )

                st.write("3. Đang tạo giọng đọc và dựng MP4...")

                video_bytes = build_video(
                    scenes,
                    voice,
                    reviewer_name,
                    images
                )

                status.update(
                    label="Đã tạo video thành công!",
                    state="complete",
                    expanded=False
                )

            st.success("🎉 Video đã sẵn sàng!")
            st.video(video_bytes)

            st.download_button(
                "📥 TẢI VIDEO MP4",
                data=video_bytes,
                file_name="BAP_AI_VIDEO.mp4",
                mime="video/mp4",
                use_container_width=True
            )

            with st.expander("Xem kịch bản"):
                for i, scene in enumerate(scenes, 1):
                    st.markdown(f"**Cảnh {i}: {scene['caption']}**")
                    st.write(scene["voiceover"])

        except Exception as error:
            st.error(f"Không tạo được video: {error}")

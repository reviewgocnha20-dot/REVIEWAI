
import os
import sys
import json
import re
import asyncio
import subprocess
import tempfile
import textwrap
import importlib.util
from pathlib import Path

import streamlit as st

# =====================================================
# 1. CẤU HÌNH VÀ TỰ KIỂM TRA THƯ VIỆN
# =====================================================

st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop",
    page_icon="🎬",
    layout="centered"
)

@st.cache_resource
def install_missing_packages():
    packages = {
        "edge_tts": "edge-tts",
        "imageio_ffmpeg": "imageio-ffmpeg",
        "PIL": "Pillow"
    }

    missing = []

    for module, package in packages.items():
        if importlib.util.find_spec(module) is None:
            missing.append(package)

    if missing:
        results = []

        for package in missing:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pip",
                    "install", "--disable-pip-version-check",
                    "--no-cache-dir", package
                ],
                capture_output=True,
                text=True,
                timeout=240
            )

            if result.returncode != 0:
                results.append(
                    f"Cài {package} thất bại:\n"
                    + (result.stderr or result.stdout)[-2500:]
                )

        if results:
            raise RuntimeError("\n\n".join(results))

    return True


try:
    install_missing_packages()

    import edge_tts
    import imageio_ffmpeg

    from PIL import (
        Image,
        ImageDraw,
        ImageFont,
        ImageFilter,
        ImageOps
    )

except Exception as error:
    st.error("KHÔNG THỂ KHỞI ĐỘNG BẮP AI VIDEO")
    st.code(str(error))
    st.info(
        "Máy chủ chưa cài được thư viện cần thiết. "
        "Kiểm tra nhật ký ứng dụng Streamlit để xem lỗi cài đặt."
    )
    st.stop()


# =====================================================
# 2. GIAO DIỆN
# =====================================================

st.title("🎬 BẮP AI VIDEO")
st.caption("TikTok Shop Edition • Video dọc 9:16")

st.markdown("""
Ứng dụng tạo video review sản phẩm từ ảnh, lời thoại,
giọng đọc tiếng Việt và phụ đề.
""")

if "video_result" not in st.session_state:
    st.session_state.video_result = None

if "script_result" not in st.session_state:
    st.session_state.script_result = None

product_links = st.text_area(
    "🔗 Link sản phẩm TikTok Shop",
    placeholder="Dán một hoặc nhiều link sản phẩm, mỗi link một dòng...",
    height=100
)

product_description = st.text_area(
    "📝 Mô tả sản phẩm",
    placeholder="Tên sản phẩm, màu sắc, chất liệu, kích thước, công dụng...",
    height=110
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
    voice_id = "vi-VN-HoaiMyNeural"
    reviewer_name = "HOÀI MY"
    reviewer_style = "Nữ reviewer thân thiện, tự nhiên"
else:
    voice_id = "vi-VN-NamMinhNeural"
    reviewer_name = "NAM MINH"
    reviewer_style = "Nam reviewer gần gũi, rõ ràng"

uploaded_files = st.file_uploader(
    "🖼 Tải ảnh sản phẩm",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True
)

if uploaded_files:
    st.caption(f"Đã chọn {len(uploaded_files)} ảnh sản phẩm.")

    columns = st.columns(min(3, len(uploaded_files)))

    for index, file in enumerate(uploaded_files):
        with columns[index % len(columns)]:
            st.image(
                file,
                caption=file.name,
                use_container_width=True
            )

gemini_key = st.text_input(
    "Gemini API Key (tùy chọn)",
    type="password",
    placeholder="Để trống nếu dùng kịch bản mẫu"
)

st.info(
    "Để hình ảnh đúng sản phẩm, hãy tải ảnh sản phẩm lên. "
    "Hiện tại link TikTok Shop được lưu làm thông tin tham khảo, "
    "chưa tự động tải ảnh và dữ liệu từ link."
)


# =====================================================
# 3. TẠO KỊCH BẢN
# =====================================================

def create_script(api_key, link, description, duration_text, style):
    seconds = int(duration_text.split()[0])
    count = max(2, min(6, seconds // 5))

    if api_key.strip():
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key.strip())

            prompt = f"""
Bạn là chuyên gia viết kịch bản video TikTok Shop tiếng Việt.

Thời lượng: {seconds} giây.
Số cảnh: {count}.
Link sản phẩm: {link}
Mô tả sản phẩm: {description}
Phong cách: {style}

Viết lời thoại tự nhiên, hấp dẫn.
Không bịa giá bán, thông số, công dụng hoặc khuyến mãi.
Chỉ dùng thông tin được cung cấp.

Trả về JSON:
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
                r"^```(?:json)?\s*|\s*```$",
                "",
                raw,
                flags=re.IGNORECASE
            )

            data = json.loads(raw)

            if isinstance(data, dict):
                data = data.get("scenes", [])

            scenes = []

            for item in data:
                if not isinstance(item, dict):
                    continue

                voiceover = str(
                    item.get("voiceover", "")
                ).strip()

                if voiceover:
                    scenes.append({
                        "caption": str(
                            item.get("caption", "")
                        ).strip() or voiceover[:50],
                        "voiceover": voiceover
                    })

            if scenes:
                return scenes[:count]

        except Exception as error:
            st.warning(
                "Gemini không khả dụng, ứng dụng chuyển sang "
                f"kịch bản mẫu. Chi tiết: {error}"
            )

    name = description.strip() or "sản phẩm này"

    templates = [
        {
            "caption": "Khoan lướt qua nhé!",
            "voiceover": (
                f"Khoan lướt qua nha! Hôm nay mình giới thiệu "
                f"đến bạn {name}."
            )
        },
        {
            "caption": "Cùng xem sản phẩm",
            "voiceover": (
                "Mình cùng xem kỹ hơn thiết kế và những điểm "
                "đáng chú ý của sản phẩm này nhé."
            )
        },
        {
            "caption": "Tham khảo trước khi mua",
            "voiceover": (
                "Bạn nhớ xem kỹ hình ảnh, kích thước và thông tin "
                "sản phẩm trước khi chọn mua nha."
            )
        },
        {
            "caption": "Xem tại giỏ hàng",
            "voiceover": (
                "Nếu thấy phù hợp, bạn có thể nhấn vào giỏ hàng "
                "để kiểm tra giá hiện tại nhé."
            )
        },
        {
            "caption": "Chọn theo nhu cầu",
            "voiceover": (
                "Hãy lựa chọn sản phẩm phù hợp với nhu cầu "
                "sử dụng của mình nha."
            )
        },
        {
            "caption": "Hẹn gặp lại",
            "voiceover": (
                "Cảm ơn bạn đã xem video. Hẹn gặp lại "
                "trong video tiếp theo nhé."
            )
        }
    ]

    return templates[:count]


# =====================================================
# 4. TẠO GIỌNG ĐỌC
# =====================================================

async def generate_voice(text, voice, output_path):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice
    )
    await communicate.save(output_path)


def run_voice(text, voice, output_path):
    asyncio.run(
        generate_voice(text, voice, output_path)
    )


# =====================================================
# 5. FONT CHỮ
# =====================================================

def get_font(size, bold=False):
    candidates = []

    if bold:
        candidates.append(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        )

    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
    ])

    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass

    return ImageFont.load_default()


# =====================================================
# 6. TẠO KHUNG HÌNH VIDEO 9:16
# =====================================================

def make_frame(image, caption, reviewer_text, output_path):
    width, height = 1080, 1920

    original = ImageOps.exif_transpose(
        image
    ).convert("RGB")

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
    foreground.thumbnail((940, 1120))

    x = (width - foreground.width) // 2
    y = (height - foreground.height) // 2 - 50

    canvas.paste(foreground, (x, y))

    draw = ImageDraw.Draw(canvas)

    top_font = get_font(30, True)
    caption_font = get_font(54, True)

    draw.rounded_rectangle(
        (55, 85, width - 55, 175),
        radius=28,
        fill=(10, 18, 32, 225)
    )

    draw.text(
        (width // 2, 130),
        f"BẮP AI VIDEO • {reviewer_text}",
        font=top_font,
        fill="white",
        anchor="mm"
    )

    caption = textwrap.fill(
        caption.strip(),
        width=23
    )

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
        fill=(0, 0, 0, 210)
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

    canvas.convert("RGB").save(
        output_path,
        format="PNG"
    )


# =====================================================
# 7. DỰNG VIDEO MP4
# =====================================================

def build_video(scenes, voice, reviewer_text, images):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    with tempfile.TemporaryDirectory() as folder:
        segments = []

        for index, scene in enumerate(scenes):
            audio_path = os.path.join(
                folder, f"audio_{index}.mp3"
            )

            frame_path = os.path.join(
                folder, f"frame_{index}.png"
            )

            video_path = os.path.join(
                folder, f"segment_{index}.mp4"
            )

            voice_text = scene["voiceover"].strip()
            caption = scene["caption"].strip() or voice_text

            run_voice(
                voice_text,
                voice,
                audio_path
            )

            selected_image = images[
                index % len(images)
            ]

            make_frame(
                selected_image,
                caption,
                reviewer_text,
                frame_path
            )

            command = [
                ffmpeg,
                "-y",
                "-loop", "1",
                "-i", frame_path,
                "-i", audio_path,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-tune", "stillimage",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                video_path
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise RuntimeError(
                    "FFmpeg tạo cảnh thất bại: "
                    + result.stderr[-2000:]
                )

            segments.append(video_path)

        concat_file = os.path.join(
            folder, "segments.txt"
        )

        with open(
            concat_file,
            "w",
            encoding="utf-8"
        ) as file:
            for path in segments:
                safe_path = path.replace("\\", "/")
                safe_path = safe_path.replace("'", "'\\''")
                file.write(f"file '{safe_path}'\n")

        final_path = os.path.join(
            folder, "BAP_AI_VIDEO.mp4"
        )

        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                final_path
            ],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Không ghép được video: "
                + result.stderr[-2000:]
            )

        with open(final_path, "rb") as file:
            return file.read()


# =====================================================
# 8. NÚT TẠO VIDEO
# =====================================================

if st.button(
    "🚀 BẮT ĐẦU TẠO VIDEO TIKTOK",
    type="primary",
    use_container_width=True
):

    links = [
        line.strip()
        for line in product_links.splitlines()
        if line.strip()
    ]

    if not links:
        st.warning("Bạn chưa nhập link sản phẩm.")

    elif not uploaded_files:
        st.warning("Bạn cần tải ít nhất một ảnh sản phẩm.")

    else:
        try:
            with st.status(
                "🎬 Đang sản xuất video...",
                expanded=True
            ) as status:

                st.write("1. Đang tạo kịch bản...")

                scenes = create_script(
                    gemini_key,
                    "\n".join(links),
                    product_description,
                    duration,
                    reviewer_style
                )

                st.write("2. Đang đọc ảnh sản phẩm...")

                images = []

                for file in uploaded_files:
                    file.seek(0)

                    with Image.open(file) as image:
                        images.append(
                            ImageOps.exif_transpose(
                                image
                            ).convert("RGB").copy()
                        )

                st.write("3. Đang tạo giọng đọc và dựng video...")

                video_bytes = build_video(
                    scenes,
                    voice_id,
                    reviewer_name,
                    images
                )

                st.session_state.video_result = video_bytes
                st.session_state.script_result = scenes

                status.update(
                    label="🎉 Đã hoàn thành video!",
                    state="complete",
                    expanded=False
                )

        except Exception as error:
            st.error("Không thể tạo video.")
            st.exception(error)


# =====================================================
# 9. HIỂN THỊ VIDEO VÀ TẢI XUỐNG
# =====================================================

if st.session_state.video_result:
    st.success("Video đã sẵn sàng!")

    st.video(st.session_state.video_result)

    st.download_button(
        "📥 TẢI VIDEO MP4",
        data=st.session_state.video_result,
        file_name="BAP_AI_VIDEO.mp4",
        mime="video/mp4",
        use_container_width=True
    )

    if st.session_state.script_result:
        with st.expander("📜 Xem kịch bản và lời thoại"):
            for index, scene in enumerate(
                st.session_state.script_result,
                start=1
            ):
                st.markdown(
                    f"**Cảnh {index}: {scene['caption']}**"
                )
                st.write(scene["voiceover"])

st.divider()
st.caption(
    "BẮP AI VIDEO • Phiên bản dựng video từ ảnh sản phẩm. "
    "Chưa tự động lấy ảnh từ TikTok Shop hoặc tạo người mẫu AI chuyển động."
)

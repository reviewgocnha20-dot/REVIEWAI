import asyncio
import concurrent.futures
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from typing import Optional

import streamlit as st

# Tự cài thư viện còn thiếu để Bắp chỉ cần thay MỘT file app.py.
# Streamlit đã được cài sẵn trên Streamlit Cloud nên không cài lại.
_PACKAGES = {
    "edge_tts": "edge-tts",
    "imageio_ffmpeg": "imageio-ffmpeg",
    "PIL": "Pillow",
    "google": "google-genai",
}
_missing = [
    package for module, package in _PACKAGES.items()
    if importlib.util.find_spec(module) is None
]
if _missing:
    with st.spinner("Đang tự cài thư viện cần thiết lần đầu..."):
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", *_missing]
            )
        except Exception as install_error:
            st.error(
                "Không thể tự cài thư viện: "
                + ", ".join(_missing)
                + f". Chi tiết: {install_error}"
            )
            st.stop()

try:
    import edge_tts
    import imageio_ffmpeg
    from google import genai
    from google.genai import types
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except Exception as import_error:
    st.error(f"Không nạp được thư viện sau khi cài: {import_error}")
    st.stop()

# ---------------------------------------------------------
# CẤU HÌNH
# ---------------------------------------------------------
st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop Edition",
    page_icon="🎬",
    layout="centered",
)

st.title("🎬 BẮP AI VIDEO - TẠO MP4")
st.caption("Bản tạo video thật: ảnh sản phẩm + giọng đọc tiếng Việt + phụ đề + MP4 dọc 9:16.")
st.success("Bộ dựng MP4 đã được tích hợp. Nhập mô tả, tải ảnh sản phẩm lên rồi nhấn nút tạo video.")

# ---------------------------------------------------------
# TIỆN ÍCH
# ---------------------------------------------------------
def run_async(coro):
    """Chạy hàm async an toàn trong môi trường Streamlit đồng bộ."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Trường hợp hiếm khi đã có event loop đang chạy.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def generate_tts_mp3(text: str, voice: str, out_path: str):
    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(out_path)


def get_unicode_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
        ])
    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ])

    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def clean_scenes(data):
    """Chuẩn hóa dữ liệu kịch bản trả về từ Gemini."""
    if isinstance(data, dict):
        data = data.get("scenes") or data.get("script") or []

    if not isinstance(data, list):
        raise ValueError("Kịch bản AI không đúng định dạng danh sách.")

    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        caption = str(item.get("caption", "")).strip()
        voiceover = str(item.get("voiceover", "")).strip()
        if voiceover:
            result.append({
                "caption": caption or voiceover[:60],
                "voiceover": voiceover,
            })

    if not result:
        raise ValueError("AI chưa tạo được lời thoại. Vui lòng thử lại.")
    return result


def generate_script_with_gemini(
    api_key: str,
    product_input: str,
    product_note: str,
    duration_str: str,
    reviewer_style: str,
):
    seconds = int(duration_str.split()[0])
    num_scenes = max(2, min(6, seconds // 5))

    if not api_key.strip():
        title = product_note.strip() or "sản phẩm tiện ích"
        templates = [
            {
                "caption": "Khoan lướt qua nhé!",
                "voiceover": f"Khoan lướt qua nha! Nếu bạn đang tìm một món đồ hữu ích thì xem thử {title} này nhé.",
            },
            {
                "caption": "Một lựa chọn đáng tham khảo",
                "voiceover": "Thiết kế tiện dụng, phù hợp để bạn tham khảo cho nhu cầu sử dụng hằng ngày. Nhớ xem kỹ thông tin và hình ảnh sản phẩm trước khi chọn mua nhé.",
            },
            {
                "caption": "Xem kỹ thông tin sản phẩm",
                "voiceover": "Bạn có thể xem thêm hình ảnh, phân loại, kích thước và đánh giá của người mua ngay tại trang sản phẩm.",
            },
            {
                "caption": "Tham khảo tại giỏ hàng",
                "voiceover": "Nếu thấy phù hợp, nhấn vào giỏ hàng để kiểm tra giá và ưu đãi đang hiển thị nha.",
            },
            {
                "caption": "Chọn đúng nhu cầu",
                "voiceover": "Hãy chọn phân loại phù hợp với nhu cầu của mình và kiểm tra thông tin trước khi đặt hàng.",
            },
            {
                "caption": "Cảm ơn bạn đã xem",
                "voiceover": "Cảm ơn bạn đã xem video. Theo dõi để xem thêm những sản phẩm hữu ích tiếp theo nhé.",
            },
        ]
        return templates[:num_scenes]

    prompt = f"""
Bạn là người viết kịch bản video giới thiệu sản phẩm TikTok bằng tiếng Việt.
Viết kịch bản video khoảng {seconds} giây, giọng tự nhiên, không phóng đại công dụng.

Thông tin đầu vào:
- Link tham khảo: {product_input}
- Mô tả do người dùng cung cấp: {product_note or "Chưa có mô tả"}
- Phong cách: {reviewer_style}

Chia thành đúng {num_scenes} cảnh theo mạch: mở đầu thu hút -> giới thiệu -> lợi ích/điểm đáng chú ý
(dựa trên mô tả được cung cấp, không tự bịa thông số) -> lời mời xem sản phẩm.
Không khẳng định giảm giá, tồn kho, chất lượng hoặc công dụng nếu đầu vào không có dữ liệu.

Chỉ trả về JSON dạng danh sách. Mỗi phần tử có:
{{"caption": "chữ ngắn trên màn hình", "voiceover": "lời thoại tiếng Việt"}}
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

    raw = (response.text or "").strip()
    raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.IGNORECASE)
    return clean_scenes(json.loads(raw))


def render_vertical_frame(
    bg_image: Optional[Image.Image],
    product_title: str,
    caption_text: str,
    reviewer_badge: str,
    out_png_path: str,
):
    width, height = 1080, 1920

    if bg_image is not None:
        original = ImageOps.exif_transpose(bg_image).convert("RGB")
        background = ImageOps.fit(
            original, (width, height), method=Image.Resampling.LANCZOS
        )
        background = background.filter(ImageFilter.GaussianBlur(radius=25))
        overlay = Image.new("RGBA", (width, height), (8, 12, 24, 125))
        canvas = Image.alpha_composite(background.convert("RGBA"), overlay)

        foreground = original.copy()
        foreground.thumbnail((940, 1120), Image.Resampling.LANCZOS)
        fw, fh = foreground.size
        canvas.paste(foreground, ((width - fw) // 2, (height - fh) // 2 - 50))
    else:
        canvas = Image.new("RGBA", (width, height), (18, 25, 43, 255))

    draw = ImageDraw.Draw(canvas)
    badge_font = get_unicode_font(30, bold=True)
    title_font = get_unicode_font(42, bold=True)
    caption_font = get_unicode_font(54, bold=True)

    draw.rounded_rectangle(
        [(55, 85), (width - 55, 175)],
        radius=28,
        fill=(10, 18, 32, 220),
    )
    draw.text(
        (width // 2, 130),
        f"BẮP AI VIDEO  •  {reviewer_badge}",
        font=badge_font,
        fill=(255, 255, 255, 255),
        anchor="mm",
    )

    if product_title.strip():
        title = textwrap.fill(product_title.strip()[:75], width=28)
        draw.multiline_text(
            (width // 2, 260),
            title,
            font=title_font,
            fill=(255, 255, 255, 255),
            anchor="mm",
            align="center",
            stroke_width=2,
            stroke_fill=(0, 0, 0, 180),
        )

    caption = textwrap.fill(caption_text.strip(), width=23)
    bbox = draw.multiline_textbbox((0, 0), caption, font=caption_font, align="center")
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    center_y = 1510
    left = max(45, (width - text_width) // 2 - 45)
    right = min(width - 45, (width + text_width) // 2 + 45)
    draw.rounded_rectangle(
        [
            (left, center_y - text_height // 2 - 35),
            (right, center_y + text_height // 2 + 35),
        ],
        radius=30,
        fill=(0, 0, 0, 205),
    )
    draw.multiline_text(
        (width // 2, center_y),
        caption,
        font=caption_font,
        fill=(255, 255, 255, 255),
        anchor="mm",
        align="center",
        spacing=12,
    )

    canvas.convert("RGB").save(out_png_path, format="PNG")


def build_tiktok_video(scenes, voice_id, reviewer_badge, product_title, images):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    with tempfile.TemporaryDirectory() as temp_dir:
        segment_paths = []

        for index, scene in enumerate(scenes):
            voice_text = scene.get("voiceover", "").strip()
            caption_text = scene.get("caption", voice_text).strip()
            if not voice_text:
                continue

            audio_path = os.path.join(temp_dir, f"audio_{index}.mp3")
            frame_path = os.path.join(temp_dir, f"frame_{index}.png")
            segment_path = os.path.join(temp_dir, f"segment_{index}.mp4")

            run_async(generate_tts_mp3(voice_text, voice_id, audio_path))

            selected_image = images[index % len(images)] if images else None
            render_vertical_frame(
                selected_image,
                product_title,
                caption_text,
                reviewer_badge,
                frame_path,
            )

            command = [
                ffmpeg_exe, "-y",
                "-loop", "1", "-i", frame_path,
                "-i", audio_path,
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-preset", "veryfast",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                segment_path,
            ]

            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if completed.returncode != 0 or not os.path.exists(segment_path):
                raise RuntimeError(
                    "FFmpeg không dựng được một cảnh video: "
                    + (completed.stderr[-1200:] if completed.stderr else "Không rõ nguyên nhân")
                )
            segment_paths.append(segment_path)

        if not segment_paths:
            raise ValueError("Không có cảnh video hợp lệ để ghép.")

        concat_file = os.path.join(temp_dir, "segments.txt")
        with open(concat_file, "w", encoding="utf-8") as file:
            for path in segment_paths:
                safe_path = path.replace("\\", "/").replace("'", r"'\''")
                file.write(f"file '{safe_path}'\n")

        final_path = os.path.join(temp_dir, "bap_ai_tiktok_video.mp4")
        completed = subprocess.run(
            [
                ffmpeg_exe, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                "-movflags", "+faststart",
                final_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if completed.returncode != 0 or not os.path.exists(final_path):
            raise RuntimeError(
                "FFmpeg không ghép được các cảnh: "
                + (completed.stderr[-1500:] if completed.stderr else "Không rõ nguyên nhân")
            )

        with open(final_path, "rb") as file:
            video_bytes = file.read()

        if not video_bytes:
            raise RuntimeError("Video xuất ra bị rỗng.")
        return video_bytes


# ---------------------------------------------------------
# GIAO DIỆN
# ---------------------------------------------------------
product_links = st.text_area(
    "Link sản phẩm TikTok Shop (để lưu/tham khảo)",
    placeholder="Dán link sản phẩm tại đây...",
    height=85,
)

product_note = st.text_area(
    "Mô tả sản phẩm (nên nhập để lời thoại chính xác)",
    placeholder="Ví dụ: tên sản phẩm, chất liệu, kích thước, màu sắc, công dụng...",
    height=100,
)

duration_str = st.selectbox(
    "Thời lượng video",
    ["10 giây", "20 giây", "30 giây", "40 giây"],
    index=1,
)

reviewer = st.radio(
    "Chọn người review",
    ["Nữ Reviewer (Hoài My)", "Nam Reviewer (Nam Minh)"],
    horizontal=True,
)

if reviewer.startswith("Nữ"):
    voice_choice = "vi-VN-HoaiMyNeural"
    reviewer_badge = "NỮ REVIEWER"
    reviewer_style = "Nữ reviewer thân thiện, tự nhiên, năng động"
else:
    voice_choice = "vi-VN-NamMinhNeural"
    reviewer_badge = "NAM REVIEWER"
    reviewer_style = "Nam reviewer gần gũi, rõ ràng, năng động"

uploaded_files = st.file_uploader(
    "Tải ảnh sản phẩm lên",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
)

if uploaded_files:
    st.caption(f"Đã chọn {len(uploaded_files)} ảnh.")
    preview_columns = st.columns(min(3, len(uploaded_files)))
    for index, uploaded in enumerate(uploaded_files):
        try:
            preview = Image.open(uploaded)
            with preview_columns[index % len(preview_columns)]:
                st.image(preview, caption=uploaded.name, use_column_width=True)
        except Exception:
            st.warning(f"Không đọc được ảnh: {uploaded.name}")

gemini_key = st.text_input(
    "Gemini API Key (không bắt buộc)",
    type="password",
    placeholder="Để trống để dùng kịch bản mẫu",
)

st.info(
    "Lưu ý: Link TikTok Shop hiện được dùng làm thông tin tham khảo cho kịch bản. "
    "Ứng dụng chưa tự trích xuất được tên, giá và ảnh từ trang sản phẩm. "
    "Hãy tải ảnh và nhập mô tả sản phẩm để video bám sát hàng thật."
)

if st.button(
    "🎬 TẠO VIDEO MP4 NGAY",
    type="primary",
    use_container_width=True,
):
    if not product_links.strip():
        st.warning("Vui lòng nhập link sản phẩm trước khi tạo video.")
    else:
        try:
            with st.status("🎬 Đang tạo video...", expanded=True) as status:
                st.write("1️⃣ Đang tạo kịch bản...")
                scenes = generate_script_with_gemini(
                    gemini_key,
                    product_links.strip(),
                    product_note.strip(),
                    duration_str,
                    reviewer_style,
                )
                st.write(f"Đã tạo {len(scenes)} cảnh.")

                st.write("2️⃣ Đang chuẩn bị ảnh sản phẩm...")
                pil_images = []
                for uploaded in uploaded_files or []:
                    uploaded.seek(0)
                    with Image.open(uploaded) as image_file:
                        pil_images.append(
                            ImageOps.exif_transpose(image_file).convert("RGB").copy()
                        )

                st.write("3️⃣ Đang tạo giọng đọc và dựng video 9:16...")
                video_bytes = build_tiktok_video(
                    scenes,
                    voice_choice,
                    reviewer_badge,
                    product_note.strip() or "Sản phẩm TikTok Shop",
                    pil_images,
                )

                status.update(
                    label="🎉 Tạo video thành công!",
                    state="complete",
                    expanded=False,
                )

            st.success("Video đã sẵn sàng!")
            st.video(video_bytes)
            st.download_button(
                "📥 TẢI VIDEO VỀ MÁY",
                data=video_bytes,
                file_name="bap_ai_tiktok_video.mp4",
                mime="video/mp4",
                use_container_width=True,
            )

            with st.expander("Xem kịch bản đã tạo"):
                for index, scene in enumerate(scenes, start=1):
                    st.markdown(f"**Cảnh {index}: {scene['caption']}**")
                    st.write(scene["voiceover"])

        except Exception as error:
            st.error(f"Không tạo được video: {error}")
            st.info(
                "Ứng dụng đã có bộ dựng MP4. Nếu lỗi Edge-TTS, kiểm tra Streamlit Cloud "
                "có cài edge-tts và máy chủ có thể kết nối dịch vụ giọng đọc. "
                "Nếu lỗi Gemini, hãy để trống API Key để dùng kịch bản mẫu."
            )

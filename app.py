import asyncio
import concurrent.futures
import html
import json
import os
import re
import subprocess
import tempfile
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import streamlit as st

st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop",
    page_icon="🎬",
    layout="centered"
)

# Thư viện bắt buộc được cài bằng requirements.txt
try:
    import edge_tts
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except ModuleNotFoundError as exc:
    st.error(
        f"Thiếu thư viện: {exc.name}. Hãy cài các thư viện trong requirements.txt "
        "rồi khởi động lại ứng dụng."
    )
    st.stop()

try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ModuleNotFoundError:
    GEMINI_AVAILABLE = False

st.title("🎬 BẮP AI VIDEO")
st.caption("Tạo video review sản phẩm • TikTok Shop • Khung dọc 9:16")
st.info(
    "Dán link để thử đọc thông tin sản phẩm, hoặc tải ảnh lên thủ công. "
    "Video hỗ trợ hiệu ứng chuyển động máy quay từ ảnh và giọng đọc tiếng Việt."
)


# ---------------- TIỆN ÍCH ----------------
def run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def make_voice(text, voice, output):
    await edge_tts.Communicate(text=text, voice=voice).save(output)


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.title_parts = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            value = attrs.get("content")
            if key and value:
                self.meta[key] = value
        elif tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)


def read_product_link(url):
    """Đọc metadata Open Graph nếu trang cho phép truy cập; không bypass đăng nhập/chặn."""
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Link không hợp lệ. Hãy dán link bắt đầu bằng http:// hoặc https://")

    request = urllib.request.Request(
        url.strip(),
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"
        }
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            raise ValueError("Link không trả về trang HTML sản phẩm.")
        raw = response.read(2_500_000)
        charset = response.headers.get_content_charset() or "utf-8"

    source = raw.decode(charset, errors="replace")
    parser = MetaParser()
    parser.feed(source)
    title = (parser.meta.get("og:title") or parser.meta.get("twitter:title")
             or " ".join(parser.title_parts)).strip()
    image_url = (parser.meta.get("og:image") or parser.meta.get("twitter:image") or "").strip()
    if image_url:
        image_url = urllib.parse.urljoin(url, html.unescape(image_url))
    title = html.unescape(re.sub(r"\s+", " ", title))
    if not title and not image_url:
        raise ValueError("Trang không cung cấp thông tin xem trước có thể đọc được.")
    return title, image_url


def download_product_image(image_url):
    if not image_url:
        return None
    request = urllib.request.Request(
        image_url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = response.read(12_000_000)
    from io import BytesIO
    with Image.open(BytesIO(data)) as im:
        return ImageOps.exif_transpose(im).convert("RGB").copy()


def get_font(size, bold=False):
    paths = []
    if bold:
        paths.append("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
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
    name = product_name.strip() or "sản phẩm này"

    if not api_key.strip() or not GEMINI_AVAILABLE:
        templates = [
            ("Khoan lướt qua nhé!", f"Khoan lướt qua nha! Hôm nay mình giới thiệu {name} đến mọi người."),
            ("Cùng xem sản phẩm", "Mình cùng xem thiết kế và những điểm đáng chú ý của sản phẩm này nhé."),
            ("Thông tin nổi bật", description.strip() or "Bạn hãy xem kỹ hình ảnh và thông tin sản phẩm để hiểu rõ hơn nha."),
            ("Tham khảo trước khi mua", "Nhớ kiểm tra phân loại, kích thước, chất liệu và thông tin từ gian hàng trước khi chọn mua nhé."),
            ("Xem tại giỏ hàng", "Nếu thấy phù hợp, bạn có thể nhấn vào giỏ hàng để xem thông tin chi tiết nha."),
            ("Cảm ơn bạn", "Cảm ơn mọi người đã xem video!")
        ]
        return [{"caption": c, "voiceover": v} for c, v in templates[:count]]

    client = genai.Client(api_key=api_key.strip())
    prompt = f"""
Bạn là chuyên gia viết kịch bản video TikTok Shop tiếng Việt.
Thời lượng: {seconds} giây. Số cảnh: {count}.
Tên sản phẩm: {product_name}
Mô tả được cung cấp: {description}
Phong cách: {style}
Viết lời thoại tự nhiên, ngắn gọn, có mở đầu và lời kêu gọi xem sản phẩm.
Không tự bịa giá, thông số, chất liệu, công dụng, đánh giá hay khuyến mãi.
Chỉ sử dụng dữ liệu trong tên và mô tả; nếu thiếu thì nói chung, không khẳng định.
Chỉ trả về JSON dạng danh sách:
[{{"caption":"Tiêu đề ngắn","voiceover":"Lời thoại"}}]
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0.65
        )
    )
    raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", (response.text or "").strip(), flags=re.I)
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("scenes") or data.get("script") or []
    if not isinstance(data, list):
        raise ValueError("Kịch bản AI không đúng định dạng.")
    scenes = []
    for item in data:
        if isinstance(item, dict):
            voiceover = str(item.get("voiceover", "")).strip()
            caption = str(item.get("caption", "")).strip()
            if voiceover:
                scenes.append({"caption": caption or voiceover[:55], "voiceover": voiceover})
    if not scenes:
        raise ValueError("AI chưa tạo được lời thoại.")
    return scenes[:count]


# ---------------- TẠO KHUNG HÌNH ----------------
def make_frame(image, caption, reviewer, output):
    width, height = 1080, 1920
    original = ImageOps.exif_transpose(image).convert("RGB")
    background = ImageOps.fit(original, (width, height), method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(25))
    overlay = Image.new("RGBA", (width, height), (8, 12, 24, 112))
    canvas = Image.alpha_composite(background.convert("RGBA"), overlay)

    foreground = original.copy()
    foreground.thumbnail((940, 1120), Image.Resampling.LANCZOS)
    x = (width - foreground.width) // 2
    y = (height - foreground.height) // 2 - 45
    canvas.paste(foreground, (x, y))

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((55, 85, width - 55, 175), radius=28, fill=(10, 18, 32, 220))
    draw.text((width // 2, 130), f"BẮP AI VIDEO • {reviewer}", font=get_font(30, True), fill="white", anchor="mm")

    caption = textwrap.fill(caption.strip(), width=23)
    font = get_font(54, True)
    bbox = draw.multiline_textbbox((0, 0), caption, font=font, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cy = 1510
    draw.rounded_rectangle(
        (max(40, (width - tw) // 2 - 45), cy - th // 2 - 35,
         min(width - 40, (width + tw) // 2 + 45), cy + th // 2 + 35),
        radius=30, fill=(0, 0, 0, 205)
    )
    draw.multiline_text((width // 2, cy), caption, font=font, fill="white",
                        anchor="mm", align="center", spacing=12)
    canvas.convert("RGB").save(output, "PNG")


# ---------------- DỰNG VIDEO CÓ CHUYỂN ĐỘNG MÁY QUAY ----------------
def build_video(scenes, voice, reviewer, images, motion="Zoom nhẹ"):
    if not images:
        raise ValueError("Bạn chưa tải ảnh sản phẩm.")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    segments = []
    with tempfile.TemporaryDirectory() as folder:
        for i, scene in enumerate(scenes):
            audio = os.path.join(folder, f"audio_{i}.mp3")
            frame = os.path.join(folder, f"frame_{i}.png")
            video = os.path.join(folder, f"segment_{i}.mp4")
            voice_text = scene["voiceover"].strip()
            if not voice_text:
                continue
            run_async(make_voice(voice_text, voice, audio))
            make_frame(images[i % len(images)], scene["caption"] or voice_text, reviewer, frame)

            if motion == "Lia máy nhẹ":
                motion_filter = (
                    "zoompan=z='1.06':x='(iw-iw/zoom)*on/180':"
                    "y='(ih-ih/zoom)/2':d=1:s=1080x1920:fps=30"
                )
            elif motion == "Zoom ra nhẹ":
                motion_filter = (
                    "zoompan=z='if(eq(on,1),1.08,max(1.0,zoom-0.00045))':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30"
                )
            else:
                motion_filter = (
                    "zoompan=z='min(zoom+0.00045,1.08)':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30"
                )

            command = [
                ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-i", frame,
                "-i", audio, "-vf", motion_filter,
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-r", "30", "-c:a", "aac", "-b:a", "192k", "-shortest",
                "-movflags", "+faststart", video
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError("Lỗi dựng cảnh video: " + result.stderr[-1600:])
            segments.append(video)

        if not segments:
            raise ValueError("Không có cảnh video hợp lệ.")
        concat_file = os.path.join(folder, "segments.txt")
        with open(concat_file, "w", encoding="utf-8") as file:
            for path in segments:
                safe_path = path.replace("\\", "/").replace("'", "'\\''")
                file.write(f"file '{safe_path}'\n")
        final_file = os.path.join(folder, "BAP_AI_VIDEO.mp4")
        result = subprocess.run([
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c", "copy", "-movflags", "+faststart", final_file
        ], capture_output=True, text=True)
        if result.returncode != 0:
            # Phương án tương thích nếu stream copy không ghép được.
            result = subprocess.run([
                ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", final_file
            ], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError("Lỗi ghép video: " + result.stderr[-1600:])
        with open(final_file, "rb") as file:
            return file.read()


# ---------------- GIAO DIỆN ----------------
if "link_title" not in st.session_state:
    st.session_state.link_title = ""
if "link_image" not in st.session_state:
    st.session_state.link_image = None
if "link_image_error" not in st.session_state:
    st.session_state.link_image_error = ""

product_link = st.text_input(
    "🔗 Link sản phẩm TikTok Shop",
    placeholder="Dán link sản phẩm tại đây..."
)

if st.button("🔎 ĐỌC THÔNG TIN TỪ LINK", use_container_width=True):
    if not product_link.strip():
        st.warning("Bạn hãy dán link sản phẩm trước.")
    else:
        try:
            with st.spinner("Đang thử đọc thông tin trang sản phẩm..."):
                title, image_url = read_product_link(product_link)
                st.session_state.link_title = title
                st.session_state.link_image = None
                st.session_state.link_image_error = ""
                if image_url:
                    try:
                        st.session_state.link_image = download_product_image(image_url)
                    except Exception as image_error:
                        st.session_state.link_image_error = str(image_error)
            st.success("Đã đọc được dữ liệu xem trước từ trang.")
        except Exception as error:
            st.warning(f"Chưa đọc tự động được link: {error}")
            st.caption("TikTok có thể giới hạn truy cập tự động. Bạn vẫn có thể nhập tên và tải ảnh sản phẩm thủ công.")

if st.session_state.link_title:
    st.caption("Thông tin trang đọc được (hãy kiểm tra lại trước khi dùng):")
    st.write(st.session_state.link_title)
    if st.session_state.link_image is not None:
        st.image(st.session_state.link_image, caption="Ảnh xem trước lấy từ trang", use_container_width=True)
    elif st.session_state.link_image_error:
        st.caption("Không tải được ảnh tự động; vui lòng tải ảnh thủ công.")

product_name = st.text_input("📦 Tên sản phẩm", value=st.session_state.link_title,
                             placeholder="Ví dụ: Khăn giấy rút...")
description = st.text_area("📝 Mô tả sản phẩm",
                            placeholder="Màu sắc, kích thước, chất liệu, công dụng...")
duration = st.selectbox("⏱ Thời lượng video", ["10 giây", "20 giây", "30 giây", "40 giây"], index=1)
reviewer = st.radio("🎤 Người review", ["Nữ Reviewer - Hoài My", "Nam Reviewer - Nam Minh"], horizontal=True)
if reviewer.startswith("Nữ"):
    voice, reviewer_name, style = "vi-VN-HoaiMyNeural", "HOÀI MY", "Nữ reviewer thân thiện, tự nhiên"
else:
    voice, reviewer_name, style = "vi-VN-NamMinhNeural", "NAM MINH", "Nam reviewer gần gũi, rõ ràng"

motion = st.selectbox("🎥 Chuyển động hình ảnh", ["Zoom nhẹ", "Zoom ra nhẹ", "Lia máy nhẹ"])
uploaded_files = st.file_uploader("🖼 Tải ảnh sản phẩm (có thể chọn nhiều ảnh)",
                                  type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
images_for_preview = []
if st.session_state.link_image is not None:
    images_for_preview.append(st.session_state.link_image)
if uploaded_files:
    st.caption(f"Đã chọn {len(uploaded_files)} ảnh tải lên.")
    columns = st.columns(min(3, len(uploaded_files)))
    for index, uploaded in enumerate(uploaded_files):
        uploaded.seek(0)
        with columns[index % len(columns)]:
            st.image(uploaded, caption=uploaded.name, use_container_width=True)

api_key = st.text_input("🔑 Gemini API Key (không bắt buộc)", type="password",
                        placeholder="Để trống dùng kịch bản mẫu")
if not GEMINI_AVAILABLE:
    st.caption("Gemini chưa được cài hoặc chưa khả dụng; có thể dùng kịch bản mẫu không cần API key.")

st.caption("Lưu ý: việc đọc link phụ thuộc quyền truy cập của TikTok. Nếu trang chặn bot hoặc yêu cầu đăng nhập, hãy nhập tên và tải ảnh thủ công. Hiệu ứng chuyển động là chuyển động máy quay trên ảnh, chưa phải nhân vật AI cử động.")

if st.button("🚀 BẮT ĐẦU TẠO VIDEO MP4", type="primary", use_container_width=True):
    all_images = list(images_for_preview)
    if uploaded_files:
        for uploaded in uploaded_files:
            uploaded.seek(0)
            try:
                with Image.open(uploaded) as image:
                    all_images.append(ImageOps.exif_transpose(image).convert("RGB").copy())
            except Exception as image_error:
                st.warning(f"Bỏ qua ảnh {uploaded.name}: {image_error}")
    if not product_link.strip():
        st.warning("Vui lòng nhập link sản phẩm.")
    elif not all_images:
        st.warning("Vui lòng tải ít nhất một ảnh sản phẩm hoặc đọc được ảnh từ link.")
    else:
        try:
            with st.status("🎬 Đang tạo video...", expanded=True) as status:
                st.write("1. Đang tạo kịch bản...")
                scenes = make_script(api_key, product_name, description, duration, style)
                st.write("2. Đang xử lý ảnh sản phẩm...")
                st.write("3. Đang tạo giọng đọc tiếng Việt...")
                st.write("4. Đang dựng video có hiệu ứng chuyển động...")
                video_bytes = build_video(scenes, voice, reviewer_name, all_images, motion)
                status.update(label="🎉 Đã tạo video thành công!", state="complete", expanded=False)
            st.success("Video của bạn đã sẵn sàng!")
            st.video(video_bytes)
            st.download_button("📥 TẢI VIDEO MP4", data=video_bytes,
                               file_name="BAP_AI_VIDEO.mp4", mime="video/mp4",
                               use_container_width=True)
            with st.expander("📄 Xem kịch bản video"):
                for index, scene in enumerate(scenes, 1):
                    st.markdown(f"**Cảnh {index}: {scene['caption']}**")
                    st.write(scene["voiceover"])
        except Exception as error:
            st.error(f"Không tạo được video: {error}")

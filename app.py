from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import anthropic
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator
from supabase import Client, create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [reviewai] %(message)s",
)
logger = logging.getLogger("reviewai")

# ==============================================================================
# 1. HẰNG SỐ & SCHEMA PYDANTIC
# ==============================================================================

STAGE_LABELS_VI: dict[str, str] = {
    "queued": "Đang trong hàng đợi",
    "analyzing_product": "Đang phân tích sản phẩm",
    "writing_script": "Đang viết kịch bản",
    "generating_voice": "Đang tạo giọng đọc",
    "generating_character": "Đang tạo nhân vật",
    "generating_scenes": "Đang tạo cảnh",
    "syncing_lips": "Đang đồng bộ khẩu hình",
    "merging_video": "Đang ghép video",
    "quality_checking": "Đang kiểm tra chất lượng",
    "saving_video": "Đang lưu video",
    "completed": "Hoàn thành",
    "needs_review": "Cần kiểm tra lại cảnh lỗi",
    "failed": "Thất bại",
}

STAGE_ORDER: list[str] = [
    "analyzing_product",
    "writing_script",
    "generating_voice",
    "generating_character",
    "generating_scenes",
    "syncing_lips",
    "merging_video",
    "quality_checking",
    "saving_video",
]

REVIEW_STYLES: dict[str, str] = {
    "kitchen": "Trong căn bếp đời thường, ánh sáng tự nhiên từ cửa sổ",
    "living_room": "Trong phòng khách gia đình, ánh sáng ban ngày dịu nhẹ",
    "vlog": "Vlog cầm tay tự nhiên, chuyển động nhẹ chân thực",
    "closeup": "Cầm tay cận cảnh giới thiệu từng chi tiết sản phẩm",
}


class ProductFacts(BaseModel):
    product_category: str
    features: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    dimensions: str = ""
    verified_uses: list[str] = Field(default_factory=list)
    notes: str = ""


class ScenePlan(BaseModel):
    scene_index: int = Field(ge=1)
    duration_sec: int = Field(ge=2, le=10)
    dialogue_text: str = Field(min_length=2)
    action_direction: str = Field(min_length=5)
    camera_framing: str = Field(min_length=3)
    needs_lipsync: bool = True
    visual_prompt_en: str = Field(min_length=10, max_length=950)


class ScriptPlan(BaseModel):
    target_duration_sec: int
    scenes: list[ScenePlan] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_total_duration(self) -> "ScriptPlan":
        total = sum(s.duration_sec for s in self.scenes)
        if total != self.target_duration_sec:
            raise ValueError(
                f"Tổng thời lượng các cảnh ({total}s) phải bằng đúng {self.target_duration_sec}s."
            )
        indices = [s.scene_index for s in self.scenes]
        if indices != list(range(1, len(self.scenes) + 1)):
            raise ValueError("scene_index phải đánh số liên tục từ 1.")
        return self


# ==============================================================================
# 2. LỚP LỖI & ADAPTER NHÀ CUNG CẤP AI THỰC TẾ
# ==============================================================================

class ProviderError(Exception):
    def __init__(self, code: str, message_vi: str, retryable: bool = False) -> None:
        super().__init__(message_vi)
        self.code = code
        self.message_vi = message_vi
        self.retryable = retryable


@dataclass
class ProviderCallResult:
    data: Any
    cost_usd: float
    request_id: str | None = None


class AnthropicLlmAdapter:
    MODEL = "claude-sonnet-5-5"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED", "Chưa cấu hình ANTHROPIC_API_KEY.", retryable=False)
        self._client = anthropic.Anthropic(api_key=api_key, timeout=90.0)

    @staticmethod
    def _calc_cost(usage: Any) -> float:
        in_t = getattr(usage, "input_tokens", 0)
        out_t = getattr(usage, "output_tokens", 0)
        return round((in_t * 2.0 + out_t * 10.0) / 1_000_000, 6)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(clean)

    def _wrap_err(self, exc: Exception) -> ProviderError:
        if isinstance(exc, anthropic.AuthenticationError):
            return ProviderError("AUTH_ERROR", "ANTHROPIC_API_KEY không hợp lệ.", retryable=False)
        if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.APITimeoutError)):
            return ProviderError("TRANSIENT_LLM_ERROR", f"Lỗi tạm thời Anthropic: {exc}", retryable=True)
        if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
            return ProviderError("SERVER_LLM_ERROR", f"Anthropic quá tải ({exc.status_code}).", retryable=True)
        return ProviderError("LLM_ERROR", f"Lỗi Claude API: {exc}", retryable=False)

    def analyze_product(
        self, product_name: str, product_url: str | None, page_text: str, image_bytes: bytes
    ) -> ProviderCallResult:
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Phân tích sản phẩm review trung thực chỉ dựa vào ảnh và nội dung cung cấp.\n"
            "KHÔNG bịa thông số, giá bán hay khuyến mãi.\n"
            f"Tên sản phẩm: {product_name}\nLink: {product_url or 'Không có'}\nNội dung trang: {page_text[:4000]}\n"
            'Trả về DUY NHẤT JSON: {"product_category":"...","features":["..."],"materials":["..."],"dimensions":"...","verified_uses":["..."],"notes":"..."}'
        )
        try:
            msg = self._client.messages.create(
                model=self.MODEL,
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            raw = "".join(b.text for b in msg.content if b.type == "text")
            facts = ProductFacts.model_validate(self._parse_json(raw))
            return ProviderCallResult(data=facts.model_dump(), cost_usd=self._calc_cost(msg.usage), request_id=msg.id)
        except ProviderError:
            raise
        except Exception as exc:
            raise self._wrap_err(exc) from exc

    def write_script(
        self,
        product_name: str,
        verified_facts: dict[str, Any],
        target_duration_sec: int,
        review_style: str,
        character_prompt: str,
        previous_error: str | None = None,
    ) -> ProviderCallResult:
        num_scenes = max(2, target_duration_sec // 5)
        fix_note = f"\nLỖI LẦN TRƯỚC CẦN SỬA: {previous_error}" if previous_error else ""
        prompt = (
            "Bạn là đạo diễn video review sản phẩm UGC đời thường tại Việt Nam.\n"
            f"Chia kịch bản thành các cảnh sao cho TỔNG duration_sec BẰNG ĐÚNG {target_duration_sec} giây "
            f"(gợi ý {num_scenes} cảnh, mỗi cảnh 2-10s).\n"
            "- Nhân vật giao tiếp tự nhiên như người thật: nhìn camera, liếc sản phẩm, cầm/xoay/chỉ chi tiết.\n"
            "- Lời thoại tiếng Việt tự nhiên, đúng chính tả, khớp độ dài cảnh (~2.5 từ/giây).\n"
            "- visual_prompt_en <= 900 ký tự tiếng Anh, ánh sáng tự nhiên, giữ nguyên hình dáng sản phẩm.\n"
            f"Sản phẩm: {product_name}\nThông số: {json.dumps(verified_facts, ensure_ascii=False)}\n"
            f"Phong cách: {review_style}\nNhân vật: {character_prompt}{fix_note}\n"
            'Trả về DUY NHẤT JSON: {"target_duration_sec":' + str(target_duration_sec) +
            ',"scenes":[{"scene_index":1,"duration_sec":5,"dialogue_text":"...","action_direction":"...","camera_framing":"...","needs_lipsync":true,"visual_prompt_en":"..."}]}'
        )
        try:
            msg = self._client.messages.create(
                model=self.MODEL,
                max_tokens=2500,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(b.text for b in msg.content if b.type == "text")
            plan = ScriptPlan.model_validate(self._parse_json(raw))
            return ProviderCallResult(data=plan, cost_usd=self._calc_cost(msg.usage), request_id=msg.id)
        except ProviderError:
            raise
        except ValueError as exc:
            raise ProviderError("SCRIPT_SCHEMA_INVALID", f"Kịch bản sai cấu trúc: {exc}", retryable=False) from exc
        except Exception as exc:
            raise self._wrap_err(exc) from exc


class ElevenLabsTtsAdapter:
    BASE_URL = "https://api.elevenlabs.io/v1"
    MODEL_ID = "eleven_flash_v2_5"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED", "Chưa cấu hình ELEVENLABS_API_KEY.", retryable=False)
        self._api_key = api_key

    def synthesize(self, text: str, voice_id: str, speed: float, out_path: Path) -> ProviderCallResult:
        clamped_speed = max(0.7, min(1.2, round(speed, 2)))
        url = f"{self.BASE_URL}/text-to-speech/{voice_id}"
        headers = {"xi-api-key": self._api_key, "Content-Type": "application/json"}
        payload = {
            "text": text,
            "model_id": self.MODEL_ID,
            "language_code": "vi",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": clamped_speed},
        }
        try:
            with httpx.Client(timeout=60.0) as hc:
                resp = hc.post(url, headers=headers, json=payload)
            if resp.status_code in (401, 403):
                raise ProviderError("AUTH_ERROR", "ELEVENLABS_API_KEY không hợp lệ.", retryable=False)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ProviderError("TRANSIENT_TTS_ERROR", f"ElevenLabs bận ({resp.status_code}).", retryable=True)
            if resp.status_code >= 400:
                raise ProviderError("TTS_INVALID_INPUT", f"Lỗi ElevenLabs ({resp.status_code}): {resp.text}", retryable=False)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(resp.content)
            return ProviderCallResult(data=out_path, cost_usd=round(len(text) * 0.00015, 5))
        except ProviderError:
            raise
        except httpx.RequestError as exc:
            raise ProviderError("NETWORK_TTS_ERROR", f"Lỗi kết nối ElevenLabs: {exc}", retryable=True) from exc


class RunwayVideoAdapter:
    BASE_URL = "https://api.dev.runwayml.com/v1"
    API_VERSION = "2024-11-06"
    MODEL = "gen4_turbo"
    RATIO_MAP = {"9:16": "720:1280", "16:9": "1280:720", "1:1": "960:960"}

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED", "Chưa cấu hình VIDEO_PROVIDER_API_KEY.", retryable=False)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Runway-Version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    def submit(self, image_url: str, prompt_text: str, duration_sec: int, aspect_ratio: str) -> str:
        payload = {
            "model": self.MODEL,
            "promptImage": image_url,
            "promptText": prompt_text[:1000],
            "duration": max(2, min(10, int(duration_sec))),
            "ratio": self.RATIO_MAP.get(aspect_ratio, "720:1280"),
        }
        try:
            with httpx.Client(timeout=45.0) as hc:
                resp = hc.post(f"{self.BASE_URL}/image_to_video", headers=self._headers, json=payload)
            if resp.status_code in (401, 403):
                raise ProviderError("AUTH_ERROR", "VIDEO_PROVIDER_API_KEY (Runway) không hợp lệ.", retryable=False)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ProviderError("TRANSIENT_VIDEO_ERROR", f"Runway tạm bận ({resp.status_code}).", retryable=True)
            if resp.status_code >= 400:
                raise ProviderError("VIDEO_REJECTED", f"Runway từ chối: {resp.text}", retryable=False)
            return resp.json()["id"]
        except ProviderError:
            raise
        except httpx.RequestError as exc:
            raise ProviderError("NETWORK_VIDEO_ERROR", f"Lỗi mạng Runway: {exc}", retryable=True) from exc

    def poll(self, task_id: str) -> tuple[str, str | None, int | None, float]:
        try:
            with httpx.Client(timeout=30.0) as hc:
                resp = hc.get(f"{self.BASE_URL}/tasks/{task_id}", headers=self._headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ProviderError("TRANSIENT_VIDEO_POLL", f"Lỗi polling Runway ({resp.status_code}).", retryable=True)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "RUNNING")
            raw_prog = data.get("progress")
            pct = int(round(float(raw_prog) * 100)) if isinstance(raw_prog, (int, float)) else None
            if status == "SUCCEEDED":
                outputs = data.get("output") or []
                if not outputs:
                    raise ProviderError("VIDEO_EMPTY_OUTPUT", "Runway trả về kết quả rỗng.", retryable=False)
                return "SUCCEEDED", outputs[0], 100, 0.25
            if status in ("FAILED", "CANCELLED"):
                fc = str(data.get("failureCode") or "VIDEO_FAILED")
                raise ProviderError(fc, f"Runway lỗi: {data.get('failure') or fc}", retryable=("UNAVAILABLE" in fc))
            return "RUNNING", None, pct, 0.0
        except ProviderError:
            raise
        except httpx.RequestError as exc:
            raise ProviderError("NETWORK_VIDEO_POLL", f"Mất kết nối polling Runway: {exc}", retryable=True) from exc


class SyncLabsAdapter:
    BASE_URL = "https://api.sync.so/v2"
    MODEL = "lipsync-2"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED", "Chưa cấu hình LIPSYNC_API_KEY.", retryable=False)
        self._headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    def submit(self, video_url: str, audio_url: str) -> str:
        payload = {
            "model": self.MODEL,
            "input": [{"type": "video", "url": video_url}, {"type": "audio", "url": audio_url}],
            "options": {"sync_mode": "cut_off"},
        }
        try:
            with httpx.Client(timeout=45.0) as hc:
                resp = hc.post(f"{self.BASE_URL}/generate", headers=self._headers, json=payload)
            if resp.status_code in (401, 403):
                raise ProviderError("AUTH_ERROR", "LIPSYNC_API_KEY không hợp lệ.", retryable=False)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ProviderError("TRANSIENT_LIPSYNC_ERROR", f"Sync Labs bận ({resp.status_code}).", retryable=True)
            if resp.status_code >= 400:
                raise ProviderError("LIPSYNC_REJECTED", f"Sync Labs từ chối: {resp.text}", retryable=False)
            return resp.json()["id"]
        except ProviderError:
            raise
        except httpx.RequestError as exc:
            raise ProviderError("NETWORK_LIPSYNC_ERROR", f"Lỗi mạng Sync Labs: {exc}", retryable=True) from exc

    def poll(self, gen_id: str) -> tuple[str, str | None, float]:
        try:
            with httpx.Client(timeout=30.0) as hc:
                resp = hc.get(f"{self.BASE_URL}/generate/{gen_id}", headers=self._headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ProviderError("TRANSIENT_LIPSYNC_POLL", f"Lỗi polling Sync Labs ({resp.status_code}).", retryable=True)
            resp.raise_for_status()
            data = resp.json()
            st_val = data.get("status", "PENDING")
            if st_val == "COMPLETED":
                out_url = data.get("outputUrl")
                if not out_url:
                    raise ProviderError("LIPSYNC_EMPTY_OUTPUT", "Sync Labs không trả về outputUrl.", retryable=False)
                dur = float(data.get("outputDuration") or 5.0)
                return "COMPLETED", out_url, round(dur * 0.04, 4)
            if st_val == "REJECTED":
                raise ProviderError("LIPSYNC_REJECTED", f"Sync Labs từ chối: {data.get('error')}", retryable=False)
            if st_val == "FAILED":
                raise ProviderError("LIPSYNC_FAILED", f"Sync Labs thất bại: {data.get('error')}", retryable=True)
            return st_val, None, 0.0
        except ProviderError:
            raise
        except httpx.RequestError as exc:
            raise ProviderError("NETWORK_LIPSYNC_POLL", f"Mất kết nối Sync Labs: {exc}", retryable=True) from exc


# ==============================================================================
# 3. FFMPEG, FFPROBE & KIỂM SOÁT CHẤT LƯỢNG (QC) THỰC TẾ
# ==============================================================================

@dataclass
class MediaInfo:
    duration_sec: float
    size_bytes: int
    has_video: bool
    has_audio: bool
    width: int
    height: int


@dataclass
class QcReport:
    passed: bool
    playable: bool
    duration_ok: bool
    resolution_ok: bool
    audio_not_silent: bool
    no_prolonged_black: bool
    size_bytes: int
    actual_duration_sec: float
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "playable": self.playable,
            "duration_ok": self.duration_ok,
            "resolution_ok": self.resolution_ok,
            "audio_not_silent": self.audio_not_silent,
            "no_prolonged_black": self.no_prolonged_black,
            "size_bytes": self.size_bytes,
            "actual_duration_sec": self.actual_duration_sec,
            "issues": self.issues,
        }


def run_cmd(args: list[str], timeout_sec: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout_sec, check=True)


def probe_media(media_path: Path) -> MediaInfo:
    res = run_cmd(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(media_path)], 30)
    info = json.loads(res.stdout)
    streams = info.get("streams", [])
    vs = next((s for s in streams if s.get("codec_type") == "video"), None)
    aus = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return MediaInfo(
        duration_sec=float(info.get("format", {}).get("duration") or 0.0),
        size_bytes=int(info.get("format", {}).get("size") or 0),
        has_video=vs is not None,
        has_audio=aus is not None,
        width=int(vs.get("width") or 0) if vs else 0,
        height=int(vs.get("height") or 0) if vs else 0,
    )


def target_resolution(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "16:9":
        return 1920, 1080
    if aspect_ratio == "1:1":
        return 1080, 1080
    return 1080, 1920


def normalize_scene(video_in: Path, audio_in: Path, out_mp4: Path, width: int, height: int, dur: float) -> MediaInfo:
    vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p"
    run_cmd([
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(video_in), "-i", str(audio_in),
        "-t", f"{dur:.2f}", "-vf", vf, "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", str(out_mp4),
    ], 240)
    return probe_media(out_mp4)


def merge_scenes_to_final(scene_paths: list[Path], srt_path: Path | None, out_mp4: Path, thumb_jpg: Path, work_dir: Path) -> MediaInfo:
    concat_file = work_dir / "concat.txt"
    concat_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in scene_paths), encoding="utf-8")
    raw_merged = work_dir / "merged_raw.mp4"
    run_cmd([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(raw_merged),
    ], 300)
    if srt_path and srt_path.exists():
        escaped = srt_path.as_posix().replace(":", "\\:")
        run_cmd([
            "ffmpeg", "-y", "-i", str(raw_merged),
            "-vf", f"subtitles='{escaped}':force_style='FontSize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=40'",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-c:a", "copy", "-movflags", "+faststart", str(out_mp4),
        ], 300)
    else:
        raw_merged.replace(out_mp4)
    run_cmd(["ffmpeg", "-y", "-ss", "0.5", "-i", str(out_mp4), "-vframes", "1", "-q:v", "2", str(thumb_jpg)], 30)
    return probe_media(out_mp4)


def inspect_video_quality(mp4_path: Path, target_dur: float, exp_w: int, exp_h: int) -> QcReport:
    issues: list[str] = []
    if not mp4_path.exists() or mp4_path.stat().st_size <= 0:
        return QcReport(False, False, False, False, False, False, 0, 0.0, ["File MP4 không tồn tại hoặc rỗng."])
    info = probe_media(mp4_path)
    playable = info.has_video and info.has_audio and info.size_bytes > 10_000
    if not playable:
        issues.append("File thiếu luồng video hoặc audio.")
    tol = max(1.0, target_dur * 0.10)
    duration_ok = abs(info.duration_sec - target_dur) <= tol
    if not duration_ok:
        issues.append(f"Thời lượng ({info.duration_sec:.2f}s) lệch quá ±10% so với {target_dur}s.")
    resolution_ok = (info.width == exp_w and info.height == exp_h)
    if not resolution_ok:
        issues.append(f"Độ phân giải {info.width}x{info.height} khác {exp_w}x{exp_h}.")

    audio_not_silent = True
    sil = run_cmd(["ffmpeg", "-i", str(mp4_path), "-af", "silencedetect=noise=-50dB:d=0.5", "-f", "null", "-"], 120)
    sil_total = sum(float(m) for m in re.findall(r"silence_duration:\s*([\d.]+)", sil.stderr))
    if info.duration_sec > 0 and sil_total >= info.duration_sec * 0.90:
        audio_not_silent = False
        issues.append("Âm thanh bị im lặng gần như toàn bộ.")

    no_black = True
    blk = run_cmd(["ffmpeg", "-i", str(mp4_path), "-vf", "blackdetect=d=0.5:pix_th=0.10", "-f", "null", "-"], 120)
    b_starts = re.findall(r"black_start:([\d.]+)", blk.stderr)
    if b_starts:
        no_black = False
        issues.append(f"Phát hiện khung đen kéo dài tại giây {', '.join(b_starts)}.")

    passed = playable and duration_ok and resolution_ok and audio_not_silent and no_black
    return QcReport(passed, playable, duration_ok, resolution_ok, audio_not_silent, no_black, info.size_bytes, info.duration_sec, issues)


# ==============================================================================
# 4. STORAGE, CREDITS & WORKER PIPELINE
# ==============================================================================

def build_path(user_id: str, project_id: str, job_id: str, filename: str) -> str:
    return f"{user_id}/{project_id}/{job_id}/{filename}"


def upload_bytes(client: Client, bucket: str, path_str: str, data: bytes, mime: str) -> int:
    client.storage.from_(bucket).upload(path=path_str, file=data, file_options={"content-type": mime, "upsert": "true"})
    return len(data)


def upload_file(client: Client, bucket: str, path_str: str, local: Path, mime: str) -> tuple[int, str]:
    data = local.read_bytes()
    return upload_bytes(client, bucket, path_str, data, mime), hashlib.sha256(data).hexdigest()


def download_from_storage(client: Client, bucket: str, path_str: str, dest: Path) -> Path:
    data = client.storage.from_(bucket).download(path_str)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def get_signed_url(client: Client, bucket: str, path_str: str, exp: int = 3600) -> str:
    res = client.storage.from_(bucket).create_signed_url(path_str, exp)
    url = res.get("signedURL") or res.get("signedUrl")
    if not url:
        raise RuntimeError(f"Không tạo được signed URL: {bucket}/{path_str}")
    return url


def estimate_credits(duration_sec: int, price_usd: float) -> float:
    return round((0.25 + (duration_sec / 10.0) * 0.65) / max(price_usd, 0.001), 2)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _with_retry(fn: Callable[[], Any], max_attempts: int = 3) -> Any:
    delay = 2.0
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except ProviderError as exc:
            if not exc.retryable or attempt == max_attempts:
                raise
            time.sleep(delay)
            delay *= 2


def _fetch_page_text(url: str | None) -> str:
    if not url:
        return ""
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as hc:
            txt = hc.get(url, headers={"User-Agent": "REVIEWAI/1.0"}).text
        clean = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", " ", txt, flags=re.I)
        clean = re.sub(r"<[^>]+>", " ", clean)
        return " ".join(clean.split())[:4000]
    except Exception:
        return ""


def _download_http(url: str, dest: Path) -> None:
    with httpx.Client(timeout=120.0, follow_redirects=True) as hc:
        r = hc.get(url)
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)


def _srt_ts(sec: float) -> str:
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def process_job(client: Client, job: dict[str, Any], credit_price_usd: float) -> None:
    job_id = job["id"]
    user_id = job["user_id"]
    project_id = job["project_id"]
    regen_scene_id = job.get("regenerate_scene_id")
    resume_stage = job.get("resume_from_status") or "analyzing_product"
    if resume_stage not in STAGE_ORDER:
        resume_stage = "analyzing_product"

    stage_costs: dict[str, float] = dict(job.get("stage_costs_usd") or {})
    used_credits = float(job.get("used_credits") or 0.0)
    current_stage = resume_stage

    def upd(patch: dict[str, Any]) -> None:
        patch["updated_at"] = _now_iso()
        patch["last_heartbeat_at"] = _now_iso()
        if "status" in patch and "current_stage_label" not in patch:
            patch["current_stage_label"] = STAGE_LABELS_VI.get(patch["status"], patch["status"])
        client.table("video_jobs").update(patch).eq("id", job_id).execute()

    def add_cost(stage: str, cost_usd: float) -> None:
        nonlocal used_credits
        if cost_usd <= 0:
            return
        stage_costs[stage] = round(stage_costs.get(stage, 0.0) + cost_usd, 6)
        delta_cr = round(cost_usd / max(credit_price_usd, 0.001), 2)
        if delta_cr > 0:
            client.rpc("apply_job_credit_delta", {"p_user_id": user_id, "p_delta": delta_cr}).execute()
            used_credits = round(used_credits + delta_cr, 2)
        upd({"stage_costs_usd": stage_costs, "used_credits": used_credits})

    def need(stage: str) -> bool:
        return STAGE_ORDER.index(stage) >= STAGE_ORDER.index(resume_stage)

    with tempfile.TemporaryDirectory(prefix=f"reviewai_{job_id}_") as tmp:
        wdir = Path(tmp)
        try:
            proj = client.table("video_projects").select("*").eq("id", project_id).single().execute().data
            llm = AnthropicLlmAdapter(os.getenv("ANTHROPIC_API_KEY", "").strip())
            tts = ElevenLabsTtsAdapter(os.getenv("ELEVENLABS_API_KEY", "").strip())
            vid_api = RunwayVideoAdapter(os.getenv("VIDEO_PROVIDER_API_KEY", "").strip())
            lip_api = SyncLabsAdapter(os.getenv("LIPSYNC_API_KEY", "").strip())

            prod_img = wdir / "product.jpg"
            prod_path_or_url = proj["product_image_url"]
            if prod_path_or_url.startswith("http"):
                _download_http(prod_path_or_url, prod_img)
                prod_signed = prod_path_or_url
            else:
                download_from_storage(client, "product-images", prod_path_or_url, prod_img)
                prod_signed = get_signed_url(client, "product-images", prod_path_or_url, 7200)

            # 1. analyzing_product
            facts = proj.get("verified_product_facts") or {}
            if need("analyzing_product") and not regen_scene_id:
                current_stage = "analyzing_product"
                upd({"status": "analyzing_product", "provider_progress_percent": None})
                res = _with_retry(lambda: llm.analyze_product(
                    proj["product_name"], proj.get("product_url"), _fetch_page_text(proj.get("product_url")), prod_img.read_bytes()
                ))
                facts = res.data
                client.table("video_projects").update({
                    "verified_product_facts": facts,
                    "product_category": facts.get("product_category") or proj.get("product_category"),
                    "updated_at": _now_iso(),
                }).eq("id", project_id).execute()
                add_cost("analyzing_product", res.cost_usd)

            # 2. writing_script
            script_dict = proj.get("script_json")
            if (need("writing_script") or not script_dict) and not regen_scene_id:
                current_stage = "writing_script"
                upd({"status": "writing_script", "provider_progress_percent": None})
                style_desc = REVIEW_STYLES.get(proj["review_style"], proj["review_style"])
                char_prompt = proj["character_config"].get("appearance_prompt", "")
                last_err: str | None = None
                sc_res = None
                for attempt in range(3):
                    try:
                        sc_res = _with_retry(lambda: llm.write_script(
                            proj["product_name"], facts, int(proj["target_duration_sec"]), style_desc, char_prompt, last_err
                        ))
                        break
                    except ProviderError as exc:
                        if exc.code == "SCRIPT_SCHEMA_INVALID" and attempt < 2:
                            last_err = exc.message_vi
                            continue
                        raise
                plan: ScriptPlan = sc_res.data
                script_dict = plan.model_dump()
                client.table("video_projects").update({"script_json": script_dict, "updated_at": _now_iso()}).eq("id", project_id).execute()
                client.table("video_scenes").delete().eq("job_id", job_id).execute()
                for sc in plan.scenes:
                    client.table("video_scenes").insert({
                        "user_id": user_id, "job_id": job_id, "scene_index": sc.scene_index,
                        "duration_sec": sc.duration_sec, "dialogue_text": sc.dialogue_text,
                        "action_direction": sc.action_direction, "camera_framing": sc.camera_framing,
                        "needs_lipsync": sc.needs_lipsync, "status": "pending",
                    }).execute()
                upd({"scenes_total": len(plan.scenes), "scenes_completed": 0})
                add_cost("writing_script", sc_res.cost_usd)

            scenes = client.table("video_scenes").select("*").eq("job_id", job_id).order("scene_index").execute().data
            sc_map = {s["scene_index"]: s for s in (script_dict or {}).get("scenes", [])}

            # 3. generating_voice
            if need("generating_voice"):
                current_stage = "generating_voice"
                upd({"status": "generating_voice", "provider_progress_percent": None})
                v_cfg = proj["voice_config"]
                spd = float(v_cfg.get("speed", 1.0))
                for sc in scenes:
                    if regen_scene_id and sc["id"] != regen_scene_id and sc.get("audio_storage_path"):
                        continue
                    aud_local = wdir / f"voice_{sc['scene_index']}.mp3"
                    r1 = _with_retry(lambda: tts.synthesize(sc["dialogue_text"], v_cfg["voice_id"], spd, aud_local))
                    add_cost("generating_voice", r1.cost_usd)
                    actual_d = probe_media(aud_local).duration_sec
                    tgt_d = float(sc["duration_sec"])
                    if tgt_d > 0 and abs(actual_d - tgt_d) / tgt_d > 0.15:
                        adj = max(0.7, min(1.2, spd * (actual_d / tgt_d)))
                        r2 = _with_retry(lambda: tts.synthesize(sc["dialogue_text"], v_cfg["voice_id"], adj, aud_local))
                        add_cost("generating_voice", r2.cost_usd)

                    a_path = build_path(user_id, project_id, job_id, f"voice_{sc['scene_index']}.mp3")
                    sz, sha = upload_file(client, "video-work", a_path, aud_local, "audio/mpeg")
                    client.table("video_scenes").update({"audio_storage_path": a_path}).eq("id", sc["id"]).execute()
                    client.table("video_assets").insert({
                        "user_id": user_id, "project_id": project_id, "job_id": job_id, "scene_id": sc["id"],
                        "asset_type": "voice_audio", "storage_bucket": "video-work", "storage_path": a_path,
                        "mime_type": "audio/mpeg", "file_size_bytes": sz, "duration_sec": probe_media(aud_local).duration_sec,
                        "checksum_sha256": sha,
                    }).execute()

            # 4. generating_character
            char_signed = prod_signed
            if need("generating_character"):
                current_stage = "generating_character"
                upd({"status": "generating_character", "provider_progress_percent": None})
                c_cfg = proj.get("character_config") or {}
                if c_cfg.get("reference_image_path"):
                    char_signed = get_signed_url(client, "product-images", c_cfg["reference_image_path"], 7200)

            # 5. generating_scenes
            scenes = client.table("video_scenes").select("*").eq("job_id", job_id).order("scene_index").execute().data
            if need("generating_scenes"):
                current_stage = "generating_scenes"
                upd({"status": "generating_scenes", "scenes_total": len(scenes), "scenes_completed": 0})
                done = 0
                for sc in scenes:
                    if regen_scene_id and sc["id"] != regen_scene_id and sc.get("raw_video_storage_path"):
                        done += 1
                        continue
                    client.table("video_scenes").update({"status": "generating"}).eq("id", sc["id"]).execute()
                    meta = sc_map.get(sc["scene_index"], {})
                    prompt_en = meta.get("visual_prompt_en") or f"{sc['action_direction']}, {sc['camera_framing']}"
                    ref_img = char_signed if sc.get("needs_lipsync") else prod_signed
                    task_id = _with_retry(lambda: vid_api.submit(ref_img, prompt_en, int(sc["duration_sec"]), proj["aspect_ratio"]))
                    client.table("video_scenes").update({"provider_name": "runway", "provider_request_id": task_id}).eq("id", sc["id"]).execute()

                    wait_s, deadline, temp_url = 5.0, time.time() + 900, None
                    while time.time() < deadline:
                        upd({"last_heartbeat_at": _now_iso()})
                        st_v, out_u, pct, cost_u = _with_retry(lambda: vid_api.poll(task_id))
                        if pct is not None:
                            upd({"provider_progress_percent": pct})
                        if st_v == "SUCCEEDED" and out_u:
                            temp_url = out_u
                            add_cost("generating_scenes", cost_u)
                            break
                        time.sleep(wait_s)
                        wait_s = min(15.0, wait_s * 1.2)
                    if not temp_url:
                        raise ProviderError("VIDEO_TIMEOUT", f"Timeout tạo Cảnh {sc['scene_index']}.", retryable=True)

                    raw_local = wdir / f"raw_{sc['scene_index']}.mp4"
                    _download_http(temp_url, raw_local)
                    raw_path = build_path(user_id, project_id, job_id, f"raw_{sc['scene_index']}.mp4")
                    sz, sha = upload_file(client, "video-work", raw_path, raw_local, "video/mp4")
                    client.table("video_scenes").update({"provider_temp_video_url": temp_url, "raw_video_storage_path": raw_path}).eq("id", sc["id"]).execute()
                    client.table("video_assets").insert({
                        "user_id": user_id, "project_id": project_id, "job_id": job_id, "scene_id": sc["id"],
                        "asset_type": "scene_raw", "storage_bucket": "video-work", "storage_path": raw_path,
                        "mime_type": "video/mp4", "file_size_bytes": sz, "checksum_sha256": sha,
                    }).execute()
                    done += 1
                    upd({"scenes_completed": done, "provider_progress_percent": None})

            # 6. syncing_lips
            scenes = client.table("video_scenes").select("*").eq("job_id", job_id).order("scene_index").execute().data
            if need("syncing_lips"):
                current_stage = "syncing_lips"
                upd({"status": "syncing_lips", "provider_progress_percent": None})
                for sc in scenes:
                    if not sc.get("needs_lipsync"):
                        continue
                    if regen_scene_id and sc["id"] != regen_scene_id and sc.get("synced_video_storage_path"):
                        continue
                    client.table("video_scenes").update({"status": "syncing"}).eq("id", sc["id"]).execute()
                    v_u = get_signed_url(client, "video-work", sc["raw_video_storage_path"], 3600)
                    a_u = get_signed_url(client, "video-work", sc["audio_storage_path"], 3600)
                    gid = _with_retry(lambda: lip_api.submit(v_u, a_u))
                    deadline, lip_url = time.time() + 600, None
                    while time.time() < deadline:
                        upd({"last_heartbeat_at": _now_iso()})
                        st_l, out_l, cost_l = _with_retry(lambda: lip_api.poll(gid))
                        if st_l == "COMPLETED" and out_l:
                            lip_url = out_l
                            add_cost("syncing_lips", cost_l)
                            break
                        time.sleep(10.0)
                    if not lip_url:
                        raise ProviderError("LIPSYNC_TIMEOUT", f"Timeout lip-sync Cảnh {sc['scene_index']}.", retryable=True)

                    lip_local = wdir / f"lip_{sc['scene_index']}.mp4"
                    _download_http(lip_url, lip_local)
                    lip_path = build_path(user_id, project_id, job_id, f"lip_{sc['scene_index']}.mp4")
                    sz, sha = upload_file(client, "video-work", lip_path, lip_local, "video/mp4")
                    client.table("video_scenes").update({"synced_video_storage_path": lip_path}).eq("id", sc["id"]).execute()
                    client.table("video_assets").insert({
                        "user_id": user_id, "project_id": project_id, "job_id": job_id, "scene_id": sc["id"],
                        "asset_type": "scene_lipsync", "storage_bucket": "video-work", "storage_path": lip_path,
                        "mime_type": "video/mp4", "file_size_bytes": sz, "checksum_sha256": sha,
                    }).execute()

            # 7. merging_video
            current_stage = "merging_video"
            upd({"status": "merging_video", "provider_progress_percent": None})
            scenes = client.table("video_scenes").select("*").eq("job_id", job_id).order("scene_index").execute().data
            out_w, out_h = target_resolution(proj["aspect_ratio"])
            norm_paths: list[Path] = []
            srt_blocks: list[str] = []
            cursor, sc_failed = 0.0, False

            for idx, sc in enumerate(scenes, start=1):
                src_v = sc.get("synced_video_storage_path") or sc["raw_video_storage_path"]
                in_v = download_from_storage(client, "video-work", src_v, wdir / f"in_v_{idx}.mp4")
                in_a = download_from_storage(client, "video-work", sc["audio_storage_path"], wdir / f"in_a_{idx}.mp3")
                norm_p = wdir / f"norm_{idx}.mp4"
                n_info = normalize_scene(in_v, in_a, norm_p, out_w, out_h, float(sc["duration_sec"]))
                sc_qc = inspect_video_quality(norm_p, float(sc["duration_sec"]), out_w, out_h)
                client.table("video_scenes").update({
                    "qc_report": sc_qc.to_dict(),
                    "status": "qc_passed" if sc_qc.passed else "qc_failed",
                    "error_message": "; ".join(sc_qc.issues) if not sc_qc.passed else None,
                }).eq("id", sc["id"]).execute()
                if not sc_qc.passed:
                    sc_failed = True
                srt_blocks.append(f"{idx}\n{_srt_ts(cursor)} --> {_srt_ts(cursor + n_info.duration_sec)}\n{sc['dialogue_text']}\n")
                cursor += n_info.duration_sec
                norm_paths.append(norm_p)

            if sc_failed:
                upd({
                    "status": "needs_review",
                    "failed_stage": "quality_checking",
                    "resume_from_status": "merging_video",
                    "error_code": "SCENE_QC_FAILED",
                    "error_message": "Có cảnh chưa đạt QC. Vui lòng tạo lại cảnh lỗi.",
                    "locked_by_worker": None,
                })
                return

            srt_file = wdir / "subtitles.srt"
            srt_file.write_text("\n".join(srt_blocks), encoding="utf-8")
            final_mp4 = wdir / "final_review.mp4"
            thumb_jpg = wdir / "thumbnail.jpg"
            merge_scenes_to_final(norm_paths, srt_file, final_mp4, thumb_jpg, wdir)

            # 8. quality_checking
            current_stage = "quality_checking"
            upd({"status": "quality_checking"})
            final_qc = inspect_video_quality(final_mp4, float(proj["target_duration_sec"]), out_w, out_h)
            if not final_qc.passed:
                upd({
                    "status": "needs_review",
                    "failed_stage": "quality_checking",
                    "resume_from_status": "merging_video",
                    "error_code": "FINAL_QC_FAILED",
                    "error_message": " | ".join(final_qc.issues),
                    "locked_by_worker": None,
                })
                return

            # 9. saving_video
            current_stage = "saving_video"
            upd({"status": "saving_video"})
            final_sp = build_path(user_id, project_id, job_id, "final_review.mp4")
            thumb_sp = build_path(user_id, project_id, job_id, "thumbnail.jpg")
            m_sz, m_sha = upload_file(client, "final-videos", final_sp, final_mp4, "video/mp4")
            t_sz, t_sha = upload_file(client, "final-videos", thumb_sp, thumb_jpg, "image/jpeg")

            client.table("video_assets").insert([
                {
                    "user_id": user_id, "project_id": project_id, "job_id": job_id,
                    "asset_type": "final_mp4", "storage_bucket": "final-videos", "storage_path": final_sp,
                    "mime_type": "video/mp4", "file_size_bytes": m_sz,
                    "duration_sec": final_qc.actual_duration_sec, "checksum_sha256": m_sha,
                },
                {
                    "user_id": user_id, "project_id": project_id, "job_id": job_id,
                    "asset_type": "thumbnail", "storage_bucket": "final-videos", "storage_path": thumb_sp,
                    "mime_type": "image/jpeg", "file_size_bytes": t_sz, "checksum_sha256": t_sha,
                },
            ]).execute()

            client.table("generation_history").upsert({
                "user_id": user_id,
                "project_id": project_id,
                "job_id": job_id,
                "product_name": proj["product_name"],
                "project_name": proj["project_name"],
                "thumbnail_storage_path": thumb_sp,
                "video_storage_path": final_sp,
                "duration_sec": round(final_qc.actual_duration_sec, 2),
                "aspect_ratio": proj["aspect_ratio"],
                "character_name": proj["character_config"]["name"],
                "voice_name": proj["voice_config"]["voice_name"],
                "script_snapshot": script_dict,
                "qc_summary": final_qc.to_dict(),
            }, on_conflict="job_id").execute()

            # 10. completed
            upd({
                "status": "completed",
                "regenerate_scene_id": None,
                "failed_stage": None,
                "resume_from_status": None,
                "error_code": None,
                "error_message": None,
                "completed_at": _now_iso(),
                "locked_by_worker": None,
            })
            logger.info("Hoàn thành job_id=%s", job_id)
        except ProviderError as exc:
            logger.error("Job lỗi job_id=%s stage=%s code=%s msg=%s", job_id, current_stage, exc.code, exc.message_vi)
            upd({
                "status": "failed",
                "failed_stage": current_stage,
                "resume_from_status": current_stage,
                "error_code": exc.code,
                "error_message": exc.message_vi,
                "retry_count": int(job.get("retry_count") or 0) + 1,
                "locked_by_worker": None,
            })
        except Exception as exc:
            logger.exception("Lỗi hệ thống job_id=%s stage=%s", job_id, current_stage)
            upd({
                "status": "failed",
                "failed_stage": current_stage,
                "resume_from_status": current_stage,
                "error_code": "INTERNAL_WORKER_ERROR",
                "error_message": f"Lỗi tại {STAGE_LABELS_VI.get(current_stage, current_stage)}: {exc}",
                "retry_count": int(job.get("retry_count") or 0) + 1,
                "locked_by_worker": None,
            })


def run_worker_loop() -> None:
    sb_url = os.getenv("SUPABASE_URL", "").strip()
    sb_srv = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    worker_id = os.getenv("WORKER_ID", "worker-1").strip()
    credit_price = float(os.getenv("CREDIT_PRICE_USD", "0.05"))
    if not sb_url or not sb_srv:
        raise RuntimeError("Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_ROLE_KEY cho worker.")
    client = create_client(sb_url, sb_srv)
    logger.info("Worker %s đang lắng nghe video_jobs...", worker_id)
    while True:
        try:
            res = client.rpc("claim_next_video_job", {"worker_id": worker_id}).execute()
            jobs = res.data or []
            if jobs:
                process_job(client, jobs[0], credit_price)
            else:
                time.sleep(3.0)
        except KeyboardInterrupt:
            logger.info("Đã dừng worker.")
            break
        except Exception as exc:
            logger.exception("Lỗi vòng lặp worker: %s", exc)
            time.sleep(5.0)


# ==============================================================================
# 5. GIAO DIỆN STREAMLIT TẤT CẢ TRONG 1 (CHỈ DÙNG ANON KEY + RLS USER JWT)
# ==============================================================================

def _app_cfg(st_mod: Any) -> tuple[str, str, float]:
    def _get(k: str, d: str = "") -> str:
        v = os.getenv(k)
        if v:
            return v.strip()
        try:
            return str(st_mod.secrets[k]).strip()
        except Exception:
            return d
    return _get("SUPABASE_URL"), _get("SUPABASE_ANON_KEY"), float(_get("CREDIT_PRICE_USD", "0.05"))


def run_streamlit_app() -> None:
    import streamlit as st

    st.set_page_config(page_title="REVIEWAI - Tạo Video Review AI", page_icon="🎬", layout="wide")
    sb_url, sb_anon, credit_price = _app_cfg(st)
    if not sb_url or not sb_anon:
        st.error("Thiếu SUPABASE_URL hoặc SUPABASE_ANON_KEY trong .env hoặc Streamlit secrets.")
        st.stop()

    anon = create_client(sb_url, sb_anon)

    st.title("🎬 REVIEWAI — Tạo Video Review AI Thực Tế")
    if "sb_user_id" not in st.session_state:
        t_in, t_up = st.tabs(["Đăng nhập", "Đăng ký tài khoản"])
        with t_in:
            em = st.text_input("Email", key="in_em")
            pw = st.text_input("Mật khẩu", type="password", key="in_pw")
            if st.button("Đăng nhập", type="primary"):
                try:
                    res = anon.auth.sign_in_with_password({"email": em, "password": pw})
                    st.session_state["sb_access"] = res.session.access_token
                    st.session_state["sb_refresh"] = res.session.refresh_token
                    st.session_state["sb_user_id"] = res.user.id
                    st.session_state["sb_email"] = res.user.email
                    st.rerun()
                except Exception as exc:
                    st.error(f"Đăng nhập thất bại: {exc}")
        with t_up:
            em_s = st.text_input("Email đăng ký", key="up_em")
            pw_s = st.text_input("Mật khẩu (>= 6 ký tự)", type="password", key="up_pw")
            if st.button("Đăng ký"):
                try:
                    anon.auth.sign_up({"email": em_s, "password": pw_s})
                    st.info("Đăng ký thành công, hãy kiểm tra email (nếu có) rồi đăng nhập.")
                except Exception as exc:
                    st.error(f"Lỗi đăng ký: {exc}")
        st.stop()

    client = create_client(sb_url, sb_anon)
    client.auth.set_session(st.session_state["sb_access"], st.session_state["sb_refresh"])
    user_id = str(st.session_state["sb_user_id"])

    with st.sidebar:
        st.success(f"Tài khoản: {st.session_state.get('sb_email')}")
        bal_row = client.table("user_credits").select("balance").eq("user_id", user_id).maybe_single().execute().data
        balance = float(bal_row["balance"]) if bal_row else 0.0
        st.metric("Credits hiện có", f"{balance:.2f}")
        if st.button("Đăng xuất"):
            for k in ("sb_access", "sb_refresh", "sb_user_id", "sb_email"):
                st.session_state.pop(k, None)
            st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs([
        "1. Tạo video",
        "2. Video đang xử lý",
        "3. Video đã hoàn thành",
        "4. Cài đặt & Credits",
    ])

    # --- TAB 1: TẠO VIDEO ---
    with tab1:
        if "idem_key" not in st.session_state:
            st.session_state["idem_key"] = str(uuid.uuid4())

        old_projs = client.table("video_projects").select("*").order("created_at", desc=True).limit(20).execute().data or []
        parent_id, prefill = None, {}
        if old_projs:
            opts = {"-- Tạo dự án mới --": None}
            for p in old_projs:
                opts[f"{p['project_name']} ({p['product_name']})"] = p["id"]
            lbl = st.selectbox("Tạo phiên bản mới từ dự án cũ", list(opts.keys()))
            parent_id = opts[lbl]
            if parent_id:
                prefill = next((p for p in old_projs if p["id"] == parent_id), {})

        with st.form("create_form"):
            c1, c2 = st.columns(2)
            with c1:
                project_name = st.text_input("Tên dự án *", value=f"{prefill['project_name']} (v2)" if prefill else "")
                product_name = st.text_input("Tên sản phẩm *", value=prefill.get("product_name", ""))
                product_url = st.text_input("Link sản phẩm (tuỳ chọn)", value=prefill.get("product_url") or "")
                product_cat = st.text_input("Danh mục", value=prefill.get("product_category") or "Gia dụng")
                prod_file = st.file_uploader("Ảnh sản phẩm gốc *", type=["jpg", "jpeg", "png"])
            with c2:
                c_pre = prefill.get("character_config") or {}
                char_name = st.text_input("Tên nhân vật *", value=c_pre.get("name", "Minh Linh"))
                char_prompt = st.text_area("Mô tả ngoại hình *", value=c_pre.get("appearance_prompt", "26yo Vietnamese woman, natural smile, casual home wear"))
                char_file = st.file_uploader("Ảnh tham chiếu nhân vật (tuỳ chọn)", type=["jpg", "jpeg", "png"])
                v_pre = prefill.get("voice_config") or {}
                tts_prov = st.selectbox("Provider giọng đọc", ["elevenlabs", "google", "fpt"])
                voice_id = st.text_input("Voice ID *", value=v_pre.get("voice_id", "EXAVITQu4vr4xnSDxMaL"))
                voice_name = st.text_input("Tên giọng đọc *", value=v_pre.get("voice_name", "Giọng Nữ Tự Nhiên"))
                voice_speed = st.slider("Tốc độ đọc", 0.7, 1.2, float(v_pre.get("speed", 1.0)), 0.05)

            c3, c4, c5 = st.columns(3)
            with c3:
                style_k = st.selectbox("Phong cách", list(REVIEW_STYLES.keys()), format_func=lambda k: f"{k} - {REVIEW_STYLES[k]}")
            with c4:
                dur_s = st.selectbox("Thời lượng (giây)", [10, 20, 30, 40], index=0)
            with c5:
                ratio_s = st.selectbox("Tỉ lệ khung hình", ["9:16", "16:9", "1:1"], index=0)

            est_cr = estimate_credits(dur_s, credit_price)
            st.info(f"Ước tính: **{est_cr} credits** | Số dư: **{balance:.2f} credits**")
            submit = st.form_submit_button("Tạo video", type="primary")

        if submit:
            if balance < est_cr:
                st.error("Số dư credits không đủ. Hãy nạp thêm ở tab Cài đặt & Credits.")
            elif not project_name or not product_name or (not prod_file and not prefill.get("product_image_url")):
                st.error("Vui lòng nhập Tên dự án, Tên sản phẩm và Ảnh sản phẩm.")
            else:
                pid = str(uuid.uuid4())
                img_path = prefill.get("product_image_url", "")
                if prod_file is not None:
                    img_path = f"{user_id}/{pid}/product_input.jpg"
                    upload_bytes(client, "product-images", img_path, prod_file.getvalue(), prod_file.type or "image/jpeg")
                c_ref = c_pre.get("reference_image_path")
                if char_file is not None:
                    c_ref = f"{user_id}/{pid}/character_ref.jpg"
                    upload_bytes(client, "product-images", c_ref, char_file.getvalue(), char_file.type or "image/jpeg")

                client.table("video_projects").insert({
                    "id": pid, "user_id": user_id, "parent_project_id": parent_id,
                    "project_name": project_name.strip(), "product_url": product_url.strip() or None,
                    "product_name": product_name.strip(), "product_image_url": img_path,
                    "product_category": product_cat.strip(), "target_duration_sec": int(dur_s),
                    "aspect_ratio": ratio_s, "review_style": style_k,
                    "character_config": {"name": char_name.strip(), "reference_image_path": c_ref, "appearance_prompt": char_prompt.strip()},
                    "voice_config": {"provider": tts_prov, "voice_id": voice_id.strip(), "voice_name": voice_name.strip(), "speed": float(voice_speed)},
                }).execute()

                idem = st.session_state["idem_key"]
                dup = client.table("video_jobs").select("id").eq("user_id", user_id).eq("idempotency_key", idem).maybe_single().execute().data
                if dup:
                    st.warning("Yêu cầu đã tồn tại (chống bấm đúp).")
                else:
                    client.table("video_jobs").insert({
                        "user_id": user_id, "project_id": pid, "idempotency_key": idem,
                        "status": "queued", "current_stage_label": "Đang trong hàng đợi", "estimated_credits": est_cr,
                    }).execute()
                    st.session_state["idem_key"] = str(uuid.uuid4())
                    st.success("Đã đẩy job vào hàng đợi! Xem tiến trình tại tab '2. Video đang xử lý'.")

    # --- TAB 2: VIDEO ĐANG XỬ LÝ ---
    with tab2:
        auto_poll = st.checkbox("Tự động làm mới mỗi 3 giây", value=False)
        if st.button("Làm mới trạng thái ngay"):
            st.rerun()

        jobs = (
            client.table("video_jobs")
            .select("*, video_projects(project_name, product_name)")
            .neq("status", "completed")
            .order("created_at", desc=True)
            .execute()
            .data or []
        )
        if not jobs:
            st.info("Không có tác vụ nào đang xử lý.")
        for j in jobs:
            pr = j.get("video_projects") or {}
            st_val = j["status"]
            elapsed = int((datetime.now(timezone.utc) - datetime.fromisoformat(j["started_at"].replace("Z", "+00:00"))).total_seconds())
            with st.container(border=True):
                c_l, c_r = st.columns([3, 1])
                with c_l:
                    st.subheader(f"{pr.get('product_name', 'SP')} — {pr.get('project_name', '')}")
                    st.write(f"**Công đoạn:** {STAGE_LABELS_VI.get(st_val, st_val)}")
                    if j.get("provider_progress_percent") is not None:
                        st.progress(int(j["provider_progress_percent"]) / 100.0, text=f"{j['provider_progress_percent']}% (từ nhà cung cấp)")
                    elif int(j.get("scenes_total") or 0) > 0:
                        st.write(f"**Cảnh hoàn thành:** {j['scenes_completed']}/{j['scenes_total']}")
                    st.caption(f"Đã chạy: {elapsed}s | Credits: {j['used_credits']}/{j['estimated_credits']} | ID: {j['id']}")
                    if st_val in ("failed", "needs_review"):
                        fs = j.get("failed_stage") or "unknown"
                        st.error(f"Lỗi tại [{STAGE_LABELS_VI.get(fs, fs)}]: {j.get('error_message')}")
                with c_r:
                    if st_val in ("failed", "needs_review"):
                        if st.button("Chạy lại từ công đoạn lỗi", key=f"rt_{j['id']}", type="primary"):
                            client.table("video_jobs").update({
                                "status": "queued", "error_message": None, "locked_by_worker": None, "timeout_at": None,
                                "current_stage_label": f"Chạy lại từ {STAGE_LABELS_VI.get(j.get('failed_stage') or '', '')}",
                            }).eq("id", j["id"]).execute()
                            st.rerun()
                    if st_val == "queued":
                        if st.button("Huỷ job", key=f"cn_{j['id']}"):
                            client.table("video_jobs").update({"status": "failed", "failed_stage": "queued", "error_message": "Người dùng đã huỷ."}).eq("id", j["id"]).execute()
                            st.rerun()
        if auto_poll:
            time.sleep(3)
            st.rerun()

    # --- TAB 3: VIDEO ĐÃ HOÀN THÀNH ---
    with tab3:
        f1, f2, f3 = st.columns(3)
        q_txt = f1.text_input("Tìm tên sản phẩm")
        f_dur = f2.selectbox("Lọc thời lượng", ["Tất cả", 10, 20, 30, 40])
        f_rat = f3.selectbox("Lọc tỉ lệ", ["Tất cả", "9:16", "16:9", "1:1"])

        hq = client.table("generation_history").select("*").eq("is_deleted", False).order("created_at", desc=True)
        if q_txt.strip():
            hq = hq.ilike("product_name", f"%{q_txt.strip()}%")
        if f_rat != "Tất cả":
            hq = hq.eq("aspect_ratio", f_rat)
        hist_items = hq.execute().data or []
        if f_dur != "Tất cả":
            hist_items = [x for x in hist_items if abs(float(x["duration_sec"]) - float(f_dur)) <= 3.0]

        if not hist_items:
            st.info("Chưa có video nào hoàn thành.")
        for it in hist_items:
            with st.container(border=True):
                cv, ci = st.columns([1, 2])
                s_mp4 = get_signed_url(client, "final-videos", it["video_storage_path"], 3600)
                with cv:
                    st.video(s_mp4)
                with ci:
                    st.subheader(f"{it['product_name']} — {it['project_name']}")
                    st.write(f"Thời lượng: **{it['duration_sec']}s** | Tỉ lệ: **{it['aspect_ratio']}** | Ngày: {it['created_at'][:19]}")
                    mp4_data = httpx.get(s_mp4, timeout=60.0).content
                    st.download_button("Tải MP4", data=mp4_data, file_name=f"{it['product_name'].replace(' ', '_')}.mp4", mime="video/mp4", key=f"dl_{it['id']}")
                    with st.expander("Kịch bản & Báo cáo QC"):
                        st.json(it["script_snapshot"])
                        st.json(it["qc_summary"])
                    with st.expander("Tạo lại một cảnh"):
                        scs = client.table("video_scenes").select("*").eq("job_id", it["job_id"]).order("scene_index").execute().data or []
                        if scs:
                            smap = {f"Cảnh {s['scene_index']}: {s['dialogue_text'][:40]}": s for s in scs}
                            ch = smap[st.selectbox("Chọn cảnh", list(smap.keys()), key=f"cs_{it['id']}")]
                            nd = st.text_input("Thoại mới", value=ch["dialogue_text"], key=f"nd_{it['id']}")
                            na = st.text_input("Hành động mới", value=ch["action_direction"], key=f"na_{it['id']}")
                            if st.button("Chạy lại cảnh này", key=f"rg_{it['id']}"):
                                client.table("video_scenes").update({
                                    "dialogue_text": nd, "action_direction": na, "status": "pending",
                                    "raw_video_storage_path": None, "synced_video_storage_path": None,
                                }).eq("id", ch["id"]).execute()
                                client.table("video_jobs").insert({
                                    "user_id": user_id, "project_id": it["project_id"], "idempotency_key": str(uuid.uuid4()),
                                    "status": "queued", "rerun_of_job_id": it["job_id"], "regenerate_scene_id": ch["id"],
                                    "resume_from_status": "generating_voice", "estimated_credits": 5.0,
                                    "current_stage_label": f"Tạo lại Cảnh {ch['scene_index']}",
                                }).execute()
                                st.success("Đã gửi yêu cầu tạo lại cảnh!")
                    if st.button("Xoá video", key=f"rm_{it['id']}"):
                        client.table("generation_history").update({"is_deleted": True}).eq("id", it["id"]).execute()
                        st.rerun()

    # --- TAB 4: CÀI ĐẶT & CREDITS ---
    with tab4:
        amt = st.number_input("Nạp credits dùng thử", min_value=1.0, max_value=500.0, value=50.0, step=10.0)
        if st.button("Nạp credits"):
            nb = client.rpc("add_user_credits", {"p_user_id": user_id, "p_amount": float(amt)}).execute().data
            st.success(f"Số dư mới: {nb}")
            st.rerun()
        cost_rows = client.table("video_jobs").select("id, status, used_credits, stage_costs_usd, created_at").order("created_at", desc=True).limit(20).execute().data or []
        if cost_rows:
            st.dataframe(cost_rows, use_container_width=True)


if __name__ == "__main__":
    if "--worker" in sys.argv:
        run_worker_loop()
    else:
        run_streamlit_app()

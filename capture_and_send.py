#!/usr/bin/env python3
"""
YouTube Live Stream Capture -> Telegram Bot
Compatible with: Local Windows (config.txt) + GitHub Actions (env vars)
"""

import subprocess
import requests
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "capture.log"

# ========================
# ĐỌC CONFIG: Env vars (GitHub Actions) hoặc config.txt (local)
# ========================
def load_config() -> dict:
    cfg = {}

    # Ưu tiên 1: Environment variables (GitHub Actions Secrets)
    env_keys = [
        "YOUTUBE_URL_1", "YOUTUBE_URL_2", "YOUTUBE_URL_3", "YOUTUBE_URL_4",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_THREAD_ID",
        "VIDEO_QUALITY", "INTERVAL_MINUTES", "CAPTION_PREFIX",
    ]
    for key in env_keys:
        val = os.environ.get(key, "")
        if val:
            cfg[key] = val

    # Ưu tiên 2: config.txt (local Windows)
    config_file = BASE_DIR / "config.txt"
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    k = key.strip()
                    # Không ghi đè env var đã có
                    if k not in cfg and val.strip():
                        cfg[k] = val.strip()
    return cfg

_cfg = load_config()

YOUTUBE_URLS       = [v for k, v in sorted(_cfg.items()) if k.startswith("YOUTUBE_URL_") and v]
TELEGRAM_BOT_TOKEN = _cfg.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = _cfg.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_THREAD_ID = int(_cfg.get("TELEGRAM_THREAD_ID", "0") or 0)
VIDEO_QUALITY      = _cfg.get("VIDEO_QUALITY", "best[height<=1440]/best")
CAPTION_PREFIX     = _cfg.get("CAPTION_PREFIX", "Bookmap Live")
INTERVAL_MINUTES   = int(_cfg.get("INTERVAL_MINUTES", "10"))

# ========================
# LOGGING
# ========================
_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
log = logging.getLogger(__name__)

# ========================
# FFMPEG: tự detect đường dẫn
# ========================
def get_ffmpeg():
    # Windows local: dùng ffmpeg.exe trong thư mục bot
    local_ffmpeg = BASE_DIR / "ffmpeg.exe"
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    # Linux/GitHub Actions: dùng ffmpeg từ PATH
    return "ffmpeg"

def get_ytdlp():
    # Windows local: dùng yt-dlp.exe đã cài
    local = r"C:\Users\Admin\AppData\Roaming\Python\Python314\Scripts\yt-dlp.exe"
    if Path(local).exists():
        return local
    # Linux/GitHub Actions: dùng từ PATH
    return "yt-dlp"

FFMPEG_EXE = get_ffmpeg()
YTDLP_EXE  = get_ytdlp()


def get_stream_url(youtube_url: str) -> str:
    log.info(f"Lay stream URL: {youtube_url}")
    kwargs = dict(capture_output=True, text=True, timeout=60)
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        [YTDLP_EXE, "--no-playlist", "-f", VIDEO_QUALITY, "-g", youtube_url],
        **kwargs
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp loi: {result.stderr.strip()}")
    url = result.stdout.strip().splitlines()[0]
    log.info(f"Stream URL: {url[:80]}...")
    return url


def capture_frame(stream_url: str, output_path: Path) -> bool:
    log.info("Chup frame tu stream...")
    kwargs = dict(capture_output=True, text=True, timeout=60)
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        [FFMPEG_EXE, "-y", "-i", stream_url, "-frames:v", "1", "-q:v", "2", str(output_path)],
        **kwargs
    )
    if result.returncode == 0 and output_path.exists():
        size_kb = output_path.stat().st_size // 1024
        log.info(f"Chup thanh cong: {output_path.name} ({size_kb} KB)")
        return True
    else:
        log.error(f"FFmpeg loi: {result.stderr[-300:]}")
        return False


def send_to_telegram(image_path: Path, caption: str) -> bool:
    log.info("Gui file anh vao Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    with open(image_path, "rb") as doc:
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
        if TELEGRAM_THREAD_ID:
            data["message_thread_id"] = TELEGRAM_THREAD_ID
        resp = requests.post(url, data=data, files={"document": doc}, timeout=60)
    if resp.status_code == 200:
        log.info("Gui Telegram thanh cong!")
        return True
    else:
        log.error(f"Telegram loi {resp.status_code}: {resp.text}")
        return False


def run_once():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(YOUTUBE_URLS)
    if total == 0:
        log.error("Khong co URL nao! Kiem tra config.txt hoac GitHub Secrets.")
        return
    for i, url in enumerate(YOUTUBE_URLS, start=1):
        label = f"Nguon {i}/{total}" if total > 1 else ""
        caption = f"<b>{CAPTION_PREFIX}</b>{'  |  ' + label if label else ''}\n<code>{now}</code>"
        screenshot = BASE_DIR / f"latest_frame_{i}.jpg"
        log.info(f"--- [{i}/{total}] ---")
        try:
            stream_url = get_stream_url(url)
            if capture_frame(stream_url, screenshot):
                send_to_telegram(screenshot, caption)
        except Exception as e:
            log.error(f"Loi nguon {i}: {e}")
            try:
                err_data = {"chat_id": TELEGRAM_CHAT_ID, "text": f"⚠️ Loi capture nguon {i}: {e}"}
                if TELEGRAM_THREAD_ID:
                    err_data["message_thread_id"] = TELEGRAM_THREAD_ID
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    data=err_data, timeout=10,
                )
            except Exception:
                pass


if __name__ == "__main__":
    run_once()

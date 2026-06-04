import os
import time
import json
import tempfile
import subprocess
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CSV_FILE = os.getenv("CSV_FILE", "table-modeli-pipe.csv")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "table-modeli-with-fileid.csv")
SEND_RESULT_TO_TELEGRAM = os.getenv("SEND_RESULT_TO_TELEGRAM", "1") == "1"
FORCE_REUPLOAD = os.getenv("FORCE_REUPLOAD", "0") == "1"

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("Нужно задать BOT_TOKEN и CHAT_ID в переменных окружения")

def build_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

session = build_session()

def check_ffmpeg():
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            check=True
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else "ffmpeg найден"
        print(first_line)
        return True
    except Exception as e:
        print(f"FFmpeg не найден или не запускается: {e}")
        return False

def get_yandex_direct_link(share_url):
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    resp = session.get(api_url, params={"public_key": share_url}, timeout=(30, 120))
    resp.raise_for_status()
    data = resp.json()
    href = data.get("href")
    print(f"Yandex API href: {href}")
    return href

def download_video(url, filepath):
    with session.get(url, stream=True, timeout=(30, 600), allow_redirects=True) as resp:
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        content_length = resp.headers.get("Content-Length", "")
        final_url = resp.url

        print(f"Download final URL: {final_url}")
        print(f"Content-Type: {content_type}")
        print(f"Content-Length: {content_length}")

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

def probe_video(filepath):
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr

def validate_video_file(filepath):
    if not os.path.exists(filepath):
        return False, "Файл не существует"

    file_size = os.path.getsize(filepath)
    print(f"Размер скачанного файла: {file_size} байт")

    if file_size == 0:
        return False, "Файл пустой"

    code, out, err = probe_video(filepath)
    if code != 0:
        return False, f"ffprobe не распознал файл как видео. stderr: {err}"

    try:
        meta = json.loads(out)
    except Exception as e:
        return False, f"Не удалось распарсить ffprobe JSON: {e}"

    streams = meta.get("streams", [])
    format_info = meta.get("format", {})

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    print("FFprobe format:", json.dumps(format_info, ensure_ascii=False))
    print(f"Видео-потоков: {len(video_streams)}, аудио-потоков: {len(audio_streams)}")

    if not video_streams:
        return False, "В файле нет видео-потока"

    duration = format_info.get("duration")
    size = format_info.get("size")
    format_name = format_info.get("format_name")

    print(f"format_name: {format_name}, duration: {duration}, size: {size}")

    return True, "OK"

def convert_video_for_telegram(input_path, output_path):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-preset", "faster",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-profile:v", "baseline",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-ac", "2",
        output_path,
    ]
    subprocess.run(cmd, check=True)

def upload_to_telegram(filepath, caption=""):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    with open(filepath, "rb") as f:
        resp = session.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption[:1024]},
            files={"video": f},
            timeout=(30, 1200),
        )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data["result"]["video"]["file_id"]

def send_document(filepath, caption="Готовый CSV"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(filepath, "rb") as f:
        resp = session.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption[:1024]},
            files={"document": f},
            timeout=(30, 1200),
        )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")

def is_telegram_file_id(value):
    if not value or str(value).lower() == "nan":
        return False
    value = str(value).strip()
    return value.startswith("BAAC") or value.startswith("AAM")

def main():
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg не установлен или недоступен в PATH")

    df = pd.read_csv(CSV_FILE, sep=";", quotechar='"', encoding="utf-8")

    for i, row in df.iterrows():
        raw_file = str(row.get("file_id", "")).strip()
        model_name = str(row.get("code_RF", "")).strip() or f"model_{i}"

        if is_telegram_file_id(raw_file):
            if not FORCE_REUPLOAD:
                print(f"[{i}] {model_name} — уже есть Telegram file_id, пропуск")
                continue
            else:
                print(f"[{i}] {model_name} — FORCE_REUPLOAD=1, но в file_id уже Telegram id, скачать заново неоткуда")
                continue

        if not raw_file or raw_file.lower() == "nan":
            print(f"[{i}] {model_name} — пустой file_id, пропуск")
            continue

        print(f"[{i}] {model_name} — получаем ссылку Яндекс.Диска")
        temp_path = None
        converted_path = None

        try:
            direct_link = get_yandex_direct_link(raw_file)
            if not direct_link:
                print(f"[{i}] {model_name} — не удалось получить прямую ссылку")
                continue

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                temp_path = tmp.name

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp2:
                converted_path = tmp2.name

            print(f"[{i}] {model_name} — скачиваем видео")
            download_video(direct_link, temp_path)

            ok, message = validate_video_file(temp_path)
            if not ok:
                print(f"[{i}] {model_name} — файл невалиден: {message}")
                continue

            print(f"[{i}] {model_name} — конвертируем видео для Telegram")
            convert_video_for_telegram(temp_path, converted_path)

            ok2, message2 = validate_video_file(converted_path)
            if not ok2:
                print(f"[{i}] {model_name} — сконвертированный файл невалиден: {message2}")
                continue

            caption = f"Модель: {model_name}"
            print(f"[{i}] {model_name} — загружаем в Telegram")
            new_file_id = upload_to_telegram(converted_path, caption=caption)

            df.at[i, "file_id"] = new_file_id
            print(f"[{i}] {model_name} — OK: {new_file_id[:40]}...")

            df.to_csv(OUTPUT_FILE, sep=";", index=False, encoding="utf-8", quoting=1)
            time.sleep(2)

        except subprocess.CalledProcessError as e:
            print(f"[{i}] {model_name} — ошибка ffmpeg: {e}")

        except Exception as e:
            print(f"[{i}] {model_name} — ошибка: {e}")

        finally:
            for p in [temp_path, converted_path]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    df.to_csv(OUTPUT_FILE, sep=";", index=False, encoding="utf-8", quoting=1)
    print(f"Готово: {OUTPUT_FILE}")

    if SEND_RESULT_TO_TELEGRAM and os.path.exists(OUTPUT_FILE):
        send_document(OUTPUT_FILE, caption="Готовый CSV с file_id")
        print("CSV отправлен в Telegram")

if __name__ == "__main__":
    main()

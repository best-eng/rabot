import requests
import pandas as pd
import time
import os

# === НАСТРОЙКИ ===
BOT_TOKEN = "8551140583:AAEw3NOzoiRDWoV0Yoe7ZFfLBN3SLVog9ds"  # токен бота из SaleBot
CHAT_ID = "1445696823"  # свой Telegram ID (можно узнать у @userinfobot)
CSV_FILE = "table-modeli-pipe.csv"
OUTPUT_FILE = "table-modeli-with-fileid.csv"


# ==================

def get_yandex_direct_link(share_url):
    """Получает прямую ссылку на скачивание с Яндекс Диска"""
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    resp = requests.get(api_url, params={"public_key": share_url})
    if resp.status_code == 200:
        return resp.json().get("href")
    return None


def download_video(url, filename):
    """Скачивает видео по прямой ссылке"""
    resp = requests.get(url, stream=True)
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def upload_to_telegram(filepath):
    """Загружает видео в Telegram и возвращает file_id"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    with open(filepath, "rb") as f:
        resp = requests.post(url, data={"chat_id": CHAT_ID}, files={"video": f})
    if resp.status_code == 200:
        result = resp.json()
        return result["result"]["video"]["file_id"]
    else:
        print(f"Ошибка загрузки: {resp.text}")
        return None


# Читаем таблицу
df = pd.read_csv(CSV_FILE, sep=";", quotechar='"', encoding="utf-8")

for i, row in df.iterrows():
    file_id = str(row["file_id"]).strip()
    code = str(row["code_RF"]).strip()

    # Пропускаем строки где уже есть Telegram file_id
    if file_id.startswith("BAAC"):
        print(f"[{i}] {code} — уже есть file_id, пропускаем")
        continue

    # Пропускаем пустые
    if not file_id or file_id == "nan":
        print(f"[{i}] {code} — нет ссылки, пропускаем")
        continue

    print(f"[{i}] {code} — скачиваем с Яндекс Диска...")

    try:
        # Получаем прямую ссылку
        direct_link = get_yandex_direct_link(file_id)
        if not direct_link:
            print(f"  ❌ Не удалось получить прямую ссылку")
            continue

        # Скачиваем
        tmp_file = f"tmp_{i}.mp4"
        download_video(direct_link, tmp_file)
        print(f"  ✅ Скачано")

        # Загружаем в Telegram
        print(f"  📤 Загружаем в Telegram...")
        new_file_id = upload_to_telegram(tmp_file)

        if new_file_id:
            df.at[i, "file_id"] = new_file_id
            print(f"  ✅ file_id получен: {new_file_id[:30]}...")
            # Сохраняем после каждой строки на случай обрыва
            df.to_csv(OUTPUT_FILE, sep=";", index=False, encoding="utf-8", quoting=1)

        # Удаляем временный файл
        os.remove(tmp_file)

        # Пауза чтобы не получить бан от Telegram
        time.sleep(3)

    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
        continue

df.to_csv(OUTPUT_FILE, sep=";", index=False, encoding="utf-8", quoting=1)
print(f"\n✅ Готово! Результат сохранён в {OUTPUT_FILE}")
# Railway uploader

Файлы для запуска на Railway.

## Что делает
- читает CSV
- скачивает видео по ссылкам Яндекс Диска
- загружает видео в Telegram
- записывает полученные file_id обратно в CSV
- отправляет готовый CSV в Telegram

## Файлы
- `main.py`
- `requirements.txt`
- `railway.json`

## Переменные окружения Railway
- `BOT_TOKEN` — токен Telegram бота
- `CHAT_ID` — твой Telegram chat id
- `CSV_FILE` — имя входного CSV, по умолчанию `table-modeli-pipe.csv`
- `OUTPUT_FILE` — имя выходного CSV, по умолчанию `table-modeli-with-fileid.csv`
- `SEND_RESULT_TO_TELEGRAM` — `1` или `0`

## Как запускать
1. Залей файлы в GitHub-репозиторий.
2. Добавь туда свой CSV рядом с `main.py`.
3. Создай проект в Railway из репозитория.
4. В Variables добавь `BOT_TOKEN` и `CHAT_ID`.
5. Запусти deploy.

## Для Cron Job
Можно использовать этот же проект как Cron Job в Railway.
Команда запуска: `python main.py`

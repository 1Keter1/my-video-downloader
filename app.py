import os
import uuid
import time
import json
import threading
import yt_dlp
from flask import (
    Flask, render_template, request, send_file,
    after_this_request, Response, stream_with_context,
)

app = Flask(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ⬇️ ДОБАВЛЕНО: глобальное хранилище прогресса + блокировка
download_progress = {}
progress_lock = threading.Lock()


# ⬇️ COOKIES: ищем файл cookies в папке проекта (локально) или в /data (Amvera)
cookies_file = None
_project_dir = os.path.dirname(os.path.abspath(__file__))

cookies_candidates = [
    "/data/cookies.txt",
    os.path.join(_project_dir, "cookies_all.txt"),
    os.path.join(_project_dir, "cookies.txt"),
]

for candidate in cookies_candidates:
    if os.path.exists(candidate):
        cookies_file = candidate
        size_kb = os.path.getsize(candidate) / 1024
        print(f"✅ Файл cookies найден: {candidate} ({size_kb:.1f} КБ)", flush=True)
        break
else:
    print("⚠️ Файл cookies не найден. Скачивание с YouTube/TikTok может не работать.", flush=True)


# ⬇️ ДОБАВЛЕНО: класс-хук, который yt-dlp будет вызывать при каждом изменении прогресса
class MyProgressHook:
    def __init__(self, download_id, url):
        self.download_id = download_id
        self.url = url

    def __call__(self, d):
        with progress_lock:
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                percent = (downloaded / total * 100) if total > 0 else 0
                download_progress[self.download_id] = {
                    'id': self.download_id,
                    'url': self.url,
                    'status': 'downloading',
                    'percent': round(percent, 1),
                    'speed': d.get('speed'),
                    'eta': d.get('eta'),
                    'filename': os.path.basename(d.get('filename', '') or ''),
                }
            elif d['status'] == 'finished':
                if self.download_id in download_progress:
                    download_progress[self.download_id].update({
                        'status': 'processing',
                        'percent': 100,
                        'speed': None,
                        'eta': None,
                        'filename': os.path.basename(d.get('filename', '') or ''),
                    })
            elif d['status'] == 'error':
                if self.download_id in download_progress:
                    download_progress[self.download_id].update({
                        'status': 'error',
                        'error': 'Download failed',
                    })


def download_video(url):
    """Скачивает видео, возвращает (путь, download_name, download_id)."""
    file_id = str(uuid.uuid4())[:8]

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_id}_%(title)s.%(ext)s'),
        # ⬇️ ИЗМЕНЕНО: для TikTok надёжнее 'b' (лучший единый файл)
        'format': 'b',
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [MyProgressHook(file_id, url)],
        'cookiefile': cookies_file,
        # ⬇️ КЛЮЧЕВЫЕ НАСТРОЙКИ ДЛЯ TIKTOK
        'impersonate': 'chrome',  # Имитация браузера Chrome (TLS-отпечаток)
        'extractor_args': {
            'tiktok': {
                'api_hostname': ['api22-normal-c-alisg.tiktokv.com'],
            },
        },
    }

    # Регистрируем загрузку как «начатую», до первого хука
    with progress_lock:
        download_progress[file_id] = {
            'id': file_id,
            'url': url,
            'status': 'downloading',
            'percent': 0,
            'speed': None,
            'eta': None,
            'filename': '',
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get('requested_downloads'):
            path = info['requested_downloads'][0]['filepath']
        else:
            path = ydl.prepare_filename(info)

    # Имя для браузера (без UUID-префикса)
    download_name = os.path.basename(path).split('_', 1)[-1]
    return path, download_name, file_id


@app.route('/', methods=['GET', 'POST'])
def index():
    error = None

    if request.method == 'POST':
        url = request.form.get('url', '').strip()

        if not url or not url.startswith(('http://', 'https://')):
            error = "Вставь корректную ссылку (должна начинаться с http:// или https://)"
        else:
            file_id = None
            try:
                filepath, download_name, file_id = download_video(url)

                @after_this_request
                def cleanup(response):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                    with progress_lock:
                        download_progress.pop(file_id, None)
                    return response

                return send_file(
                    filepath,
                    as_attachment=True,
                    download_name=download_name,
                    mimetype='application/octet-stream',
                    conditional=True,
                )

            except Exception as e:
                if file_id:
                    with progress_lock:
                        download_progress.pop(file_id, None)
                error = f"Не удалось скачать: {str(e)[:200]}"

    return render_template('index.html', error=error)


# ⬇️ ДОБАВЛЕНО: SSE-поток с прогрессом
@app.route('/stream')
def stream():
    def event_stream():
        while True:
            with progress_lock:
                snapshot = list(download_progress.values())
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            time.sleep(1)

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ⬇️ ДОБАВЛЕНО: страница мониторинга
@app.route('/monitor')
def monitor():
    return render_template('monitor.html')


if __name__ == '__main__':
    # ⬇️ ИЗМЕНЕНО: порт по умолчанию 3000 (требование Amvera)
    port = int(os.environ.get('PORT', 3000))
    app.run(debug=False, host='0.0.0.0', port=port)
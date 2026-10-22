import os
import uuid
import yt_dlp
from flask import Flask, render_template, request, send_file, after_this_request

app = Flask(__name__)

# Папка для временных загрузок — создастся автоматически
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def download_video(url):
    """Скачивает видео по ссылке, возвращает путь к файлу."""
    file_id = str(uuid.uuid4())[:8]

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_id}_%(title)s.%(ext)s'),
        'format': 'bestvideo*+bestaudio/best',
        'quiet': True,
        'no_warnings': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get('requested_downloads'):
            return info['requested_downloads'][0]['filepath']
        return ydl.prepare_filename(info)


@app.route('/', methods=['GET', 'POST'])
def index():
    error = None

    if request.method == 'POST':
        url = request.form.get('url', '').strip()

        if not url or not url.startswith(('http://', 'https://')):
            error = "Вставь корректную ссылку (должна начинаться с http:// или https://)"
        else:
            try:
                filepath = download_video(url)

                @after_this_request
                def cleanup(response):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                    return response

                return send_file(filepath, as_attachment=True)

            except Exception as e:
                error = f"Не удалось скачать: {str(e)[:200]}"

    return render_template('index.html', error=error)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
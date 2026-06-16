import os
import json
import threading
import uuid
import tempfile
import shutil
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
import yt_dlp
app = Flask(__name__)
app.config['TEMP_FOLDER'] = os.path.join(tempfile.gettempdir(), 'video_downloader')
app.config['DOWNLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(app.config['TEMP_FOLDER'], exist_ok=True)
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)
tasks = {}
def get_cookie_file():
    cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    if os.path.exists(cookie_path):
        return cookie_path
    return None
def progress_hook(d):
    task_id = d.get('task_id')
    if not task_id or task_id not in tasks:
        return
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        speed = d.get('speed', 0)
        eta = d.get('eta', 0)
        percent = (downloaded / total * 100) if total > 0 else 0
        tasks[task_id]['progress'] = round(percent, 1)
        tasks[task_id]['speed'] = f"{(speed / 1024 / 1024):.1f} MB/s" if speed else "N/A"
        tasks[task_id]['eta'] = f"{eta}s" if eta else "N/A"
        tasks[task_id]['downloaded'] = f"{(downloaded / 1024 / 1024):.1f} MB"
        tasks[task_id]['total'] = f"{(total / 1024 / 1024):.1f} MB" if total else "Unknown"
    elif d['status'] == 'finished':
        tasks[task_id]['status'] = 'processing'
        tasks[task_id]['progress'] = 100
        tasks[task_id]['message'] = 'Processing...'
def get_ydl_opts(task_id, quality='best'):
    output_dir = tasks[task_id].get('output_dir', app.config['TEMP_FOLDER'])
    os.makedirs(output_dir, exist_ok=True)
    if quality == 'audio':
        format_spec = 'bestaudio/bestaudio[ext=m4a]/best'
    elif quality == 'best':
        format_spec = 'bestvideo+bestaudio/best'
    elif quality == '1080p':
        format_spec = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
    elif quality == '720p':
        format_spec = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
    elif quality == '480p':
        format_spec = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
    else:
        format_spec = 'bestvideo+bestaudio/best'
    opts = {
        'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        'format': format_spec,
        'merge_output_format': 'mp4' if quality != 'audio' else None,
        'progress_hooks': [progress_hook],
        'noplaylist': False,
        'ignoreerrors': True,
        'no_warnings': True,
        'quiet': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.tiktok.com/',
        },
    }
    cookie_file = get_cookie_file()
    if cookie_file:
        opts['cookiefile'] = cookie_file
    return opts
def find_downloaded_file(output_dir):
    if not os.path.exists(output_dir):
        return None
    files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
    if not files:
        return None
    return max(files, key=lambda f: os.path.getmtime(os.path.join(output_dir, f)))
def move_to_downloads(src_path, filename):
    dest_path = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
    counter = 1
    base, ext = os.path.splitext(filename)
    while os.path.exists(dest_path):
        dest_path = os.path.join(app.config['DOWNLOAD_FOLDER'], f"{base} ({counter}){ext}")
        counter += 1
    for attempt in range(5):
        try:
            shutil.copy2(src_path, dest_path)
            return dest_path
        except PermissionError:
            import time
            time.sleep(0.5)
    return src_path
def download_video(url, task_id):
    try:
        quality = tasks[task_id].get('quality', 'best')
        output_dir = tasks[task_id].get('output_dir', app.config['TEMP_FOLDER'])
        opts = get_ydl_opts(task_id, quality)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        filename = find_downloaded_file(output_dir)
        if filename:
            src = os.path.join(output_dir, filename)
            final_path = move_to_downloads(src, filename)
            tasks[task_id]['filename'] = filename
            tasks[task_id]['download_path'] = final_path
            tasks[task_id]['status'] = 'completed'
            tasks[task_id]['progress'] = 100
            tasks[task_id]['message'] = 'Download complete!'
        else:
            tasks[task_id]['status'] = 'error'
            tasks[task_id]['message'] = 'Download completed but file not found'
    except Exception as e:
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['message'] = str(e)
def download_batch(urls, task_id):
    total = len(urls)
    completed = 0
    failed = 0
    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue
        sub_task_id = f"{task_id}_{i}"
        output_dir = tasks[task_id].get('output_dir', app.config['TEMP_FOLDER'])
        tasks[sub_task_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': f'Downloading {i + 1}/{total}...',
            'current_url': url,
            'quality': tasks[task_id].get('quality', 'best'),
            'output_dir': output_dir,
        }
        try:
            quality = tasks[task_id].get('quality', 'best')
            opts = get_ydl_opts(sub_task_id, quality)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            filename = find_downloaded_file(output_dir)
            if filename:
                src = os.path.join(output_dir, filename)
                final_path = move_to_downloads(src, filename)
                tasks[sub_task_id]['filename'] = filename
                tasks[sub_task_id]['download_path'] = final_path
                tasks[sub_task_id]['status'] = 'completed'
                completed += 1
            else:
                tasks[sub_task_id]['status'] = 'error'
                tasks[sub_task_id]['message'] = 'File not found after download'
                failed += 1
        except Exception as e:
            failed += 1
            tasks[sub_task_id]['status'] = 'error'
            tasks[sub_task_id]['message'] = str(e)
        tasks[task_id]['completed_count'] = completed
        tasks[task_id]['failed_count'] = failed
        tasks[task_id]['total_count'] = total
    tasks[task_id]['status'] = 'completed'
    tasks[task_id]['message'] = f'Done! {completed}/{total} downloaded, {failed} failed.'
@app.route('/')
def index():
    return render_template('index.html')
@app.route('/api/info', methods=['POST'])
def get_info():
    url = request.json.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            },
        }
        cookie_file = get_cookie_file()
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        is_playlist = 'entries' in info
        results = []
        if is_playlist:
            results.append({
                'type': 'playlist',
                'title': info.get('title', 'Unknown Playlist'),
                'uploader': info.get('uploader', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'count': len(list(info.get('entries', []))),
            })
            for entry in info.get('entries', []):
                if entry:
                    results.append({
                        'type': 'video',
                        'title': entry.get('title', 'Unknown'),
                        'duration': format_duration(entry.get('duration', 0)),
                        'thumbnail': entry.get('thumbnail', ''),
                        'url': entry.get('webpage_url', ''),
                    })
        else:
            results.append({
                'type': 'video',
                'title': info.get('title', 'Unknown'),
                'uploader': info.get('uploader', 'Unknown'),
                'duration': format_duration(info.get('duration', 0)),
                'thumbnail': info.get('thumbnail', ''),
                'url': info.get('webpage_url', url),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', ''),
            })
        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
def format_duration(seconds):
    if not seconds:
        return 'Unknown'
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json
    urls = data.get('urls', [])
    quality = data.get('quality', 'best')
    if not urls:
        return jsonify({'error': 'No URLs provided'}), 400
    output_dir = os.path.join(app.config['TEMP_FOLDER'], str(uuid.uuid4())[:8])
    os.makedirs(output_dir, exist_ok=True)
    if len(urls) == 1:
        task_id = str(uuid.uuid4())[:8]
        tasks[task_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': 'Starting download...',
            'quality': quality,
            'output_dir': output_dir,
        }
        thread = threading.Thread(target=download_video, args=(urls[0], task_id))
        thread.daemon = True
        thread.start()
        return jsonify({'task_id': task_id, 'mode': 'single'})
    else:
        task_id = str(uuid.uuid4())[:8]
        tasks[task_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': f'Downloading {len(urls)} videos...',
            'quality': quality,
            'output_dir': output_dir,
            'completed_count': 0,
            'failed_count': 0,
            'total_count': len(urls),
        }
        thread = threading.Thread(target=download_batch, args=(urls, task_id))
        thread.daemon = True
        thread.start()
        return jsonify({'task_id': task_id, 'mode': 'batch'})
@app.route('/api/status/<task_id>')
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
    task = tasks[task_id]
    return jsonify(task)
@app.route('/download/<task_id>')
def download_file(task_id):
    if task_id not in tasks:
        return 'Task not found', 404
    task = tasks[task_id]
    download_path = task.get('download_path')
    filename = task.get('filename')
    if not download_path or not os.path.exists(download_path):
        return 'File not found', 404
    return send_file(
        download_path,
        as_attachment=True,
        download_name=filename
    )
@app.route('/download/batch/<task_id>/<int:index>')
def download_batch_file(task_id, index):
    sub_task_id = f"{task_id}_{index}"
    if sub_task_id not in tasks:
        return 'Task not found', 404
    task = tasks[sub_task_id]
    download_path = task.get('download_path')
    filename = task.get('filename')
    if not download_path or not os.path.exists(download_path):
        return 'File not found', 404
    return send_file(
        download_path,
        as_attachment=True,
        download_name=filename
    )
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)

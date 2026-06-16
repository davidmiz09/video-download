import yt_dlp

ydl_opts = {
    'quiet': True,
    'no_warnings': True,
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info('https://www.youtube.com/watch?v=dQw4w9WgXcQ', download=False)
    
    for f in info.get('formats', []):
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        ext = f.get('ext', '?')
        height = f.get('height', '?')
        fid = f.get('format_id', '?')
        print(f'{fid}: v={vcodec} a={acodec} ext={ext} {height}p')

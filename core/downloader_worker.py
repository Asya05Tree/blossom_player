import re
from PyQt6.QtCore import QThread
from yt_dlp import YoutubeDL

class DownloadWorker(QThread):
    def __init__(self, url, video_id):
        super().__init__()
        self.url = url
        self.video_id = video_id

    def run(self):
        try:
            clean_link = re.sub(r'(&list=.*|&start_radio=.*)', '', self.url)
            ydl_opts = {
                'format': 'best[height<=480]',
                'outtmpl': f'video_backgrounds/{self.video_id}.mp4',
                'quiet': True,
                'no_warnings': True,
                'js_engine': 'node'
            }
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([clean_link])
        except Exception as e:
            print(f"[-] Ошибка загрузки: {e}")
import json
from pathlib import Path
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal


class VideoInfoWorker(QThread):
    """Извлекает метаданные видео в отдельном потоке."""

    finished = pyqtSignal(str, dict)  # (video_path, info_dict)
    failed = pyqtSignal(str)  # video_path

    def __init__(self, mp4_path: Path, parent=None):
        super().__init__(parent)
        self.mp4_path = Path(mp4_path)

    def run(self):
        if self.isInterruptionRequested():
            self.failed.emit(str(self.mp4_path))
            return

        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_name,duration",
                "-show_entries",
                "format=duration,size",
                "-of",
                "json",
                str(self.mp4_path),
            ]
            result = subprocess.run(
                cmd, capture_output=True, check=True, timeout=5, text=True
            )
            data = json.loads(result.stdout)

            info = {}
            # видео-поток
            streams = data.get("streams", [])
            if streams:
                stream = streams[0]
                width = stream.get("width", 0)
                height = stream.get("height", 0)
                codec = stream.get("codec_name", "unknown")
                info["resolution"] = f"{width}x{height}"
                info["codec"] = codec
                # определяем качество
                if height >= 2160:
                    info["quality"] = "4K"
                elif height >= 1080:
                    info["quality"] = "1080p"
                elif height >= 720:
                    info["quality"] = "720p"
                elif height >= 480:
                    info["quality"] = "480p"
                else:
                    info["quality"] = f"{height}p"

            # формат
            fmt = data.get("format", {})
            duration = fmt.get("duration")
            size = fmt.get("size")
            if duration:
                info["duration"] = float(duration)
            if size:
                info["size_mb"] = int(size) / (1024 * 1024)

            self.finished.emit(str(self.mp4_path), info)
        except Exception:
            self.failed.emit(str(self.mp4_path))

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


class PreviewWorker(QThread):
    """Извлекает кадр из видео в отдельном потоке."""

    finished = pyqtSignal(str, str)  # (video_path, tmp_jpg_path)
    failed = pyqtSignal(str)  # video_path

    def __init__(self, mp4_path: Path, parent=None):
        super().__init__(parent)
        self.mp4_path = Path(mp4_path)

    def run(self):
        import tempfile

        if self.isInterruptionRequested():
            self.failed.emit(str(self.mp4_path))
            return

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            cmd = [
                "ffmpeg",
                "-i",
                str(self.mp4_path),
                "-ss",
                "00:01:00",
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-y",
                tmp_path,
            ]
            subprocess.run(cmd, capture_output=True, check=True, timeout=10)
            if self.isInterruptionRequested():
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                self.failed.emit(str(self.mp4_path))
                return
            self.finished.emit(str(self.mp4_path), tmp_path)
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            self.failed.emit(str(self.mp4_path))

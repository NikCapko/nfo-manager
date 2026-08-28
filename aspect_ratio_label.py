from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel


class AspectRatioLabel(QLabel):
    """QLabel, который масштабирует pixmap с сохранением пропорций."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #2b2b2b;")

    def setPixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._update_scaled()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        size = self.size()
        if size.width() == 0 or size.height() == 0:
            return
        scaled = self._pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        super().setPixmap(scaled)

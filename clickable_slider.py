from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class ClickableSlider(QSlider):
    """QSlider, который прыгает на место клика мышью."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # вычисляем позицию по координатам клика
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            handle_rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,
                opt,
                QStyle.SubControl.SC_SliderHandle,
                self,
            )
            # доступная для движения область
            available = self._pixelPosToRangeValue(event.position().x())
            self.setValue(available)
            self.sliderMoved.emit(available)
            event.accept()
        else:
            super().mousePressEvent(event)

    def _pixelPosToRangeValue(self, pos: float) -> int:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        slider_min = groove.left()
        slider_max = groove.right() - handle.width() + 1
        if slider_max == slider_min:
            return self.minimum()
        span = slider_max - slider_min
        value_range = self.maximum() - self.minimum()
        x = max(slider_min, min(pos, slider_max))
        return int(self.minimum() + (x - slider_min) * value_range / span)

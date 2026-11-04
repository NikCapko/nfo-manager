from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    """Диалог настроек приложения."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)
        self.setWindowTitle("Настройки")
        self.resize(400, 200)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Группа "Видео" ---
        video_group = QGroupBox("Видео")
        video_layout = QVBoxLayout()

        self.chk_show_preview = QCheckBox(
            "Показывать кадр-превью перед воспроизведением"
        )
        self.chk_show_preview.setChecked(bool(self.settings.get("show_preview", True)))
        self.chk_show_preview.setToolTip(
            "Если включено — при выборе видео сначала отображается кадр,\n"
            "и только после клика/пробела начинается воспроизведение."
        )
        video_layout.addWidget(self.chk_show_preview)

        sub_font_row = QHBoxLayout()
        sub_font_row.addWidget(QLabel("Размер шрифта субтитров:"))
        self.spin_sub_font = QSpinBox()
        self.spin_sub_font.setRange(10, 40)
        self.spin_sub_font.setValue(int(self.settings.get("subtitle_font_size", 16)))
        sub_font_row.addWidget(self.spin_sub_font)
        sub_font_row.addStretch()
        video_layout.addLayout(sub_font_row)

        video_group.setLayout(video_layout)
        layout.addWidget(video_group)

        # --- Кнопки ---
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("Сохранить")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_accept(self):
        self.settings["show_preview"] = self.chk_show_preview.isChecked()
        self.settings["subtitle_font_size"] = self.spin_sub_font.value()
        self.accept()

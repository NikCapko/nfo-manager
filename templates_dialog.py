from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class TemplatesDialog(QDialog):
    """Диалог управления шаблонами метаданных."""

    def __init__(self, templates: dict, parent=None):
        super().__init__(parent)
        self.templates = dict(templates)
        self.result_template: Optional[str] = None  # имя применённого шаблона
        self.setWindowTitle("Шаблоны метаданных")
        self.resize(420, 360)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Выберите шаблон для применения:"))

        self.list_templates = QListWidget()
        self.list_templates.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_templates.itemDoubleClicked.connect(self._on_apply)
        for name in sorted(self.templates.keys(), key=str.casefold):
            self.list_templates.addItem(name)
        layout.addWidget(self.list_templates, 1)

        # содержимое выбранного шаблона
        self.lbl_details = QLabel()
        self.lbl_details.setWordWrap(True)
        self.lbl_details.setStyleSheet(
            "color: palette(mid); background: palette(window); padding: 6px; border-radius: 4px;"
        )
        self.lbl_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.lbl_details)

        self.list_templates.currentItemChanged.connect(self._on_selection_changed)

        # кнопки
        btn_row = QHBoxLayout()
        btn_new = QPushButton("Создать из текущего")
        btn_new.clicked.connect(self._on_create)
        btn_update = QPushButton("Обновить выбранный")
        btn_update.clicked.connect(self._on_update)
        btn_delete = QPushButton("Удалить")
        btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(btn_new)
        btn_row.addWidget(btn_update)
        btn_row.addWidget(btn_delete)
        layout.addLayout(btn_row)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Close
        )
        btn_box.button(QDialogButtonBox.StandardButton.Apply).setText("Применить")
        btn_box.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        btn_box.accepted.connect(self._on_apply)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        if self.list_templates.count() > 0:
            self.list_templates.setCurrentRow(0)

    def _on_selection_changed(self, current: Optional[QListWidgetItem], _prev):
        if current is None:
            self.lbl_details.setText("")
            return
        name = current.text()
        tpl = self.templates.get(name, {})
        lines = []
        if tpl.get("genres"):
            lines.append(f"<b>Жанры:</b> {', '.join(tpl['genres'])}")
        if tpl.get("tags"):
            lines.append(f"<b>Теги:</b> {', '.join(tpl['tags'])}")
        if tpl.get("studios"):
            lines.append(f"<b>Студии:</b> {', '.join(tpl['studios'])}")
        self.lbl_details.setText("<br>".join(lines) if lines else "<i>Шаблон пуст</i>")

    def _on_apply(self, *_args):
        item = self.list_templates.currentItem()
        if item is None:
            QMessageBox.information(self, "Шаблон", "Выберите шаблон")
            return
        self.result_template = item.text()
        self.accept()

    def _on_create(self):
        # родителю нужно будет передать текущие жанры/теги/студии
        parent = self.parent()
        if not hasattr(parent, "_get_current_metadata"):
            return
        current = parent._get_current_metadata()
        if not any(current.values()):
            QMessageBox.information(
                self, "Шаблон", "Сначала заполните жанры/теги/студии в форме."
            )
            return
        name, ok = QInputDialog.getText(self, "Новый шаблон", "Название шаблона:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.templates:
            box = QMessageBox(self)
            box.setWindowTitle("Шаблон уже существует")
            box.setText(f"Шаблон «{name}» уже существует. Перезаписать?")
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
        self.templates[name] = current
        self._notify_change()
        self.list_templates.clear()
        for n in sorted(self.templates.keys(), key=str.casefold):
            self.list_templates.addItem(n)
        items = self.list_templates.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self.list_templates.setCurrentItem(items[0])

    def _on_update(self):
        item = self.list_templates.currentItem()
        if item is None:
            QMessageBox.information(self, "Шаблон", "Выберите шаблон")
            return
        parent = self.parent()
        if not hasattr(parent, "_get_current_metadata"):
            return
        current = parent._get_current_metadata()
        if not any(current.values()):
            QMessageBox.information(
                self, "Шаблон", "Сначала заполните жанры/теги/студии в форме."
            )
            return
        name = item.text()
        self.templates[name] = current
        self._notify_change()
        self._on_selection_changed(item, None)
        QMessageBox.information(self, "Шаблон", f"Шаблон «{name}» обновлён")

    def _on_delete(self):
        item = self.list_templates.currentItem()
        if item is None:
            return
        name = item.text()
        box = QMessageBox(self)
        box.setWindowTitle("Удалить шаблон")
        box.setText(f"Удалить шаблон «{name}»?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        del self.templates[name]
        self._notify_change()
        self.list_templates.takeItem(self.list_templates.row(item))

    def _notify_change(self):
        """Сообщает родителю об изменении словаря шаблонов."""
        parent = self.parent()
        if hasattr(parent, "_on_templates_changed"):
            parent._on_templates_changed(self.templates)

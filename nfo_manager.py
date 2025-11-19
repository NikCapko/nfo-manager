#!/usr/bin/env python3
"""
Simple .nfo editor (single-file) using PyQt6.
Features:
- Open a single .nfo (XML) file used by Kodi/Plex/Emby
- Edit main movie fields: title, originaltitle, year, rating, plot, runtime
- Edit genres (categories), actors (name + role), and tags
- Preserve other XML nodes when saving (only update the nodes we touch)
- History of previously used studios, genres, tags and actors (saved to config)
Dependencies:
    pip install PyQt6
Run:
    python3 nfo_editor_pyqt.py [path_to_file.nfo]
"""

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

NAMES = [
    "title",
    "originaltitle",
    "year",
    "original_filename",
    # "rating",
    "plot",
]
TITLES = {
    "title": "Название",
    "originaltitle": "Оригинальное название",
    "year": "Год",
    "original_filename": "Название файла",
    # "rating": "Title 2",
    "plot": "Сюжет",
}

# --- History (config) -------------------------------------------------------

HISTORY_PATH = Path.home() / ".config" / "nfo_editor" / "history.json"

DEFAULT_HISTORY = {
    "studios": [],
    "genres": [],
    "tags": [],
    "actors": [],  # list of {"name": "...", "role": "..."}
}


def load_history() -> dict:
    try:
        if HISTORY_PATH.exists():
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            # ensure keys exist
            for k, v in DEFAULT_HISTORY.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception:
        pass
    return dict(DEFAULT_HISTORY)


def save_history(history: dict):
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"Не удалось сохранить историю: {e}", file=sys.stderr)


def add_to_history_list(history: dict, key: str, value: str):
    value = value.strip()
    if not value:
        return
    lst = history.setdefault(key, [])
    if value not in lst:
        lst.append(value)
        # keep reasonable size
        if len(lst) > 500:
            history[key] = lst[-500:]
        save_history(history)


def add_actor_to_history(history: dict, name: str, role: str):
    name = name.strip()
    role = role.strip()
    if not name:
        return
    actors = history.setdefault("actors", [])
    entry = {"name": name, "role": role}
    if entry not in actors:
        actors.append(entry)
        if len(actors) > 500:
            history["actors"] = actors[-500:]
        save_history(history)


# --- NFO document -----------------------------------------------------------


class NfoDocument:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        self.tree: Optional[ET.ElementTree] = None
        self.root: Optional[ET.Element] = None

    def load(self, path: Path):
        self.path = Path(path)
        self.tree = ET.parse(self.path)
        self.root = self.tree.getroot()

    def save(self, path: Optional[Path] = None):
        if path:
            self.path = Path(path)
        if not self.path or not self.root:
            raise RuntimeError("No document loaded")
        # Write XML with utf-8 and pretty printing
        self._indent(self.root)
        self.tree.write(str(self.path), encoding="utf-8", xml_declaration=True)

    def _indent(self, elem, level=0):
        # simple pretty print
        i = "\n" + level * " "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + " "
            for e in elem:
                self._indent(e, level + 1)
            if not e.tail or not e.tail.strip():
                e.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    # helpers to get/set single text nodes
    def get_text(self, tag: str) -> str:
        if self.root is None:
            return ""
        # Check for the new structure
        if tag == "set":
            set_el = self.root.find("set")
            if set_el is not None:
                name_el = set_el.find("name")
                if name_el is not None and name_el.text is not None:
                    return name_el.text.strip()
        else:
            el = self.root.find(tag)
            return el.text if el is not None and el.text is not None else ""

    def set_text(self, tag: str, text: str):
        if self.root is None:
            return
        el = self.root.find(tag)
        if el is None:
            el = ET.SubElement(self.root, tag)
        # Check for the new structure
        if tag == "set":
            # Remove existing set element if it exists
            for e in list(self.root.findall("set")):
                self.root.remove(e)
            # Create a new set element with name sub-element
            set_el = ET.SubElement(self.root, "set")
            name_el = ET.SubElement(set_el, "name")
            name_el.text = text.strip()
        else:
            el.text = text.strip()

    def get_studios(self):
        if self.root is None:
            return []
        return [g.text for g in self.root.findall("studio") if g.text]

    def set_studios(self, studios):
        if self.root is None:
            return
        # remove existing studio elements
        for g in list(self.root.findall("studio")):
            self.root.remove(g)
        # append new ones
        for g in studios:
            el = ET.SubElement(self.root, "studio")
            el.text = g

    def get_genres(self):
        if self.root is None:
            return []
        return [g.text for g in self.root.findall("genre") if g.text]

    def set_genres(self, genres):
        if self.root is None:
            return
        # remove existing genre elements
        for g in list(self.root.findall("genre")):
            self.root.remove(g)
        # append new ones
        for g in genres:
            el = ET.SubElement(self.root, "genre")
            el.text = g

    def get_tags(self):
        if self.root is None:
            return []
        return [t.text for t in self.root.findall("tag") if t.text]

    def set_tags(self, tags):
        if self.root is None:
            return
        for t in list(self.root.findall("tag")):
            self.root.remove(t)
        for t in tags:
            el = ET.SubElement(self.root, "tag")
            el.text = t

    def get_actors(self):
        if self.root is None:
            return []
        actors = []
        for a in self.root.findall("actor"):
            name = a.findtext("name") or ""
            role = a.findtext("role") or ""
            actors.append((name, role))
        return actors

    def set_actors(self, actors):
        if self.root is None:
            return
        for a in list(self.root.findall("actor")):
            self.root.remove(a)
        for name, role in actors:
            a = ET.SubElement(self.root, "actor")
            n = ET.SubElement(a, "name")
            n.text = name
            r = ET.SubElement(a, "role")
            r.text = role


# --- Main window ------------------------------------------------------------


class NfoEditorWindow(QMainWindow):
    def __init__(self, initial_file: Optional[str] = None):
        super().__init__()
        if initial_file is None:
            self.setWindowTitle("NFO Editor — single file")
        else:
            self.setWindowTitle(Path(initial_file).name)
        self.resize(900, 600)
        self.doc = NfoDocument()
        self.history = load_history()
        self._build_ui()
        # автозагрузка файла, если указан в аргументах
        if initial_file:
            try:
                self.doc.load(Path(initial_file))
                self._populate_from_doc()
            except Exception as e:
                QMessageBox.critical(
                    self, "Ошибка", f"Не удалось открыть файл при запуске:\n{e}"
                )
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.save_file)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout()
        central.setLayout(main_layout)
        # Top buttons
        top_row = QHBoxLayout()
        btn_open = QPushButton("Открыть .nfo")
        btn_open.clicked.connect(self.open_file)
        btn_save = QPushButton("Сохранить")
        btn_save.clicked.connect(self.save_file)
        btn_save_as = QPushButton("Сохранить как...")
        btn_save_as.clicked.connect(self.save_file_as)
        top_row.addWidget(btn_open)
        top_row.addWidget(btn_save)
        top_row.addWidget(btn_save_as)
        top_row.addStretch()
        main_layout.addLayout(top_row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        # Left: form fields
        left = QWidget()
        left_layout = QVBoxLayout()
        left.setLayout(left_layout)
        form = QWidget()
        form_layout = QVBoxLayout()
        form.setLayout(form_layout)
        self.fields = {}
        for name in NAMES:
            lbl = QLabel(TITLES[name])
            row = None
            if name == "plot":
                widget = QTextEdit()
                row = QVBoxLayout()
                row.addWidget(lbl)
                row.addWidget(widget)
            else:
                widget = QLineEdit()
                row = QVBoxLayout()
                row.addWidget(lbl)
                # special case: add button for original_filename
                if name == "original_filename":
                    h = QHBoxLayout()
                    h.addWidget(widget)
                    btn_browse = QPushButton("▶")
                    btn_browse.setFixedWidth(30)
                    btn_browse.clicked.connect(self.browse_original_file)
                    h.addWidget(btn_browse)
                    row.addLayout(h)
                else:
                    row.addWidget(widget)
            self.fields[name] = widget
            form_layout.addLayout(row)
        left_layout.addWidget(form)
        # Studios
        sbox = QWidget()
        sbox_layout = QVBoxLayout()
        sbox.setLayout(sbox_layout)
        sbox_layout.addWidget(QLabel("Студии"))
        self.list_studios = QListWidget()
        sbox_layout.addWidget(self.list_studios)
        ss = QHBoxLayout()
        btn_add_studio = QPushButton("Добавить студию")
        btn_add_studio.clicked.connect(self.add_studio)
        btn_remove_studio = QPushButton("Удалить студию")
        btn_remove_studio.clicked.connect(self.remove_studio)
        ss.addWidget(btn_add_studio)
        ss.addWidget(btn_remove_studio)
        sbox_layout.addLayout(ss)
        left_layout.addWidget(sbox)
        # Genres
        gbox = QWidget()
        gbox_layout = QVBoxLayout()
        gbox.setLayout(gbox_layout)
        gbox_layout.addWidget(QLabel("Жанры"))
        self.list_genres = QListWidget()
        gbox_layout.addWidget(self.list_genres)
        gg = QHBoxLayout()
        btn_add_genre = QPushButton("Добавить жанр")
        btn_add_genre.clicked.connect(self.add_genre)
        btn_remove_genre = QPushButton("Удалить жанр")
        btn_remove_genre.clicked.connect(self.remove_genre)
        gg.addWidget(btn_add_genre)
        gg.addWidget(btn_remove_genre)
        gbox_layout.addLayout(gg)
        left_layout.addWidget(gbox)
        # Tags
        tbox = QWidget()
        tbox_layout = QVBoxLayout()
        tbox.setLayout(tbox_layout)
        tbox_layout.addWidget(QLabel("Теги"))
        self.list_tags = QListWidget()
        tbox_layout.addWidget(self.list_tags)
        tt = QHBoxLayout()
        btn_add_tag = QPushButton("Добавить тег")
        btn_add_tag.clicked.connect(self.add_tag)
        btn_remove_tag = QPushButton("Удалить тег")
        btn_remove_tag.clicked.connect(self.remove_tag)
        tt.addWidget(btn_add_tag)
        tt.addWidget(btn_remove_tag)
        tbox_layout.addLayout(tt)
        left_layout.addWidget(tbox)
        splitter.addWidget(left)
        # Right: actors and raw xml
        right = QWidget()
        right_layout = QVBoxLayout()
        right.setLayout(right_layout)
        right_layout.addWidget(QLabel("Актёры"))
        self.table_actors = QTableWidget(0, 2)
        self.table_actors.setHorizontalHeaderLabels(["Имя", "Роль"])
        self.table_actors.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table_actors.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        right_layout.addWidget(self.table_actors)
        aa = QHBoxLayout()
        btn_add_actor = QPushButton("Добавить актёра")
        btn_add_actor.clicked.connect(self.add_actor)
        btn_remove_actor = QPushButton("Удалить актёра")
        btn_remove_actor.clicked.connect(self.remove_actor)
        aa.addWidget(btn_add_actor)
        aa.addWidget(btn_remove_actor)
        aa.addStretch()
        right_layout.addLayout(aa)
        # Raw XML preview
        right_layout.addWidget(QLabel("Исходный XML (предпросмотр)"))
        self.raw_xml = QTextEdit()
        self.raw_xml.setReadOnly(True)
        right_layout.addWidget(self.raw_xml)
        splitter.addWidget(right)
        splitter.setSizes([450, 450])

    def show_info_message(self, title, message, duration_ms=500):
        """Показывает информационное сообщение QMessageBox и скрывает его через заданное время."""
        msg = QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setIcon(QMessageBox.Icon.Information)
        QTimer.singleShot(duration_ms, msg.close)
        msg.exec()  # Показывает модальный диалог

    def browse_original_file(self):
        filename = self.fields["original_filename"].text().strip()
        if not filename:
            QMessageBox.warning(self, "Ошибка", "Поле пустое")
            return
        # строим путь относительно текущего .nfo
        base_dir = self.doc.path.parent if self.doc.path else None
        path = os.path.join(base_dir, filename) if base_dir else filename
        if not os.path.exists(path):
            QMessageBox.warning(self, "Ошибка", f"Файл не найден: {path}")
            return
        try:
            if sys.platform.startswith("darwin"):
                subprocess.Popen(["open", path])
            elif os.name == "nt":
                os.startfile(path)
            elif os.name == "posix":
                subprocess.Popen(["mpv", path])
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл: {e}")

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть .nfo",
            "",
            "NFO files (*.nfo);;XML files (*.xml);;All files (*)",
        )
        if not path:
            return
        try:
            self.doc.load(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{e}")
            return
        self._populate_from_doc()
        self.show_info_message("Открыто", f"Файл открыт: {path}")

    def save_file(self):
        if not self.doc.path:
            return self.save_file_as()
        try:
            self._update_doc_from_ui()
            self.doc.save()
            self.show_info_message("Сохранено", f"Сохранено: {self.doc.path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{e}")

    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить как",
            "",
            "NFO files (*.nfo);;XML files (*.xml);;All files (*)",
        )
        if not path:
            return
        try:
            self._update_doc_from_ui()
            self.doc.save(Path(path))
            self.show_info_message("Сохранено", f"Сохранено: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{e}")

    def _populate_from_doc(self):
        if not self.doc.root:
            return
        for name in NAMES:
            self.fields[name].setText(self.doc.get_text(name))
        # studios
        self.list_studios.clear()
        for s in self.doc.get_studios():
            self.list_studios.addItem(s)
        # genres
        self.list_genres.clear()
        for g in self.doc.get_genres():
            self.list_genres.addItem(g)
        # tags
        self.list_tags.clear()
        for t in self.doc.get_tags():
            self.list_tags.addItem(t)
        # actors
        self.table_actors.setRowCount(0)
        for name, role in self.doc.get_actors():
            r = self.table_actors.rowCount()
            self.table_actors.insertRow(r)
            self.table_actors.setItem(r, 0, QTableWidgetItem(name))
            self.table_actors.setItem(r, 1, QTableWidgetItem(role))
        # raw xml
        self._refresh_raw()

    def _update_doc_from_ui(self):
        for name in NAMES:
            text = (
                self.fields[name].toPlainText()
                if name == "plot"
                else self.fields[name].text()
            )
            self.doc.set_text(name, text)
        # studios
        studios = [
            self.list_studios.item(i).text() for i in range(self.list_studios.count())
        ]
        self.doc.set_studios(studios)
        # genres
        genres = [
            self.list_genres.item(i).text() for i in range(self.list_genres.count())
        ]
        self.doc.set_genres(genres)
        # tags
        tags = [self.list_tags.item(i).text() for i in range(self.list_tags.count())]
        self.doc.set_tags(tags)
        # actors
        actors = []
        for r in range(self.table_actors.rowCount()):
            name_item = self.table_actors.item(r, 0)
            role_item = self.table_actors.item(r, 1)
            name = name_item.text() if name_item else ""
            role = role_item.text() if role_item else ""
            actors.append((name, role))
        self.doc.set_actors(actors)
        # refresh raw preview
        self._refresh_raw()

    def _refresh_raw(self):
        if not self.doc.tree:
            self.raw_xml.setPlainText("")
            return
        # produce string
        try:
            self.doc._indent(self.doc.root)
            xml_bytes = ET.tostring(self.doc.root, encoding="utf-8")
            xml_text = xml_bytes.decode("utf-8")
        except Exception:
            xml_text = "(Не удалось показать XML-превью)"
        self.raw_xml.setPlainText(xml_text)

    # ---------- UI actions with history ----------

    def _pick_from_history(
        self, title: str, label: str, items: list[str]
    ) -> Optional[str]:
        """Показывает диалог с выбором из списка (редактируемый). Возвращает текст или None."""
        items = sorted(set(items), key=str.casefold) if items else [""]
        text, ok = QInputDialog.getItem(
            self,
            title,
            label,
            items,
            0,
            editable=True,
        )
        if ok and text.strip():
            return text.strip()
        return None

    def add_studio(self):
        text = self._pick_from_history(
            "Добавить студию",
            "Название студии (можно выбрать из истории или ввести новое):",
            self.history.get("studios", []),
        )
        if text:
            self.list_studios.addItem(text)
            add_to_history_list(self.history, "studios", text)

    def remove_studio(self):
        for item in self.list_studios.selectedItems():
            self.list_studios.takeItem(self.list_studios.row(item))

    def add_genre(self):
        text = self._pick_from_history(
            "Добавить жанр",
            "Название жанра (можно выбрать из истории или ввести новое):",
            self.history.get("genres", []),
        )
        if text:
            self.list_genres.addItem(text)
            add_to_history_list(self.history, "genres", text)

    def remove_genre(self):
        for item in self.list_genres.selectedItems():
            self.list_genres.takeItem(self.list_genres.row(item))

    def add_tag(self):
        text = self._pick_from_history(
            "Добавить тег",
            "Тег (можно выбрать из истории или ввести новое):",
            self.history.get("tags", []),
        )
        if text:
            self.list_tags.addItem(text)
            add_to_history_list(self.history, "tags", text)

    def remove_tag(self):
        items = self.list_tags.selectedItems()
        for it in items:
            self.list_tags.takeItem(self.list_tags.row(it))

    def add_actor(self):
        # имена из истории актёров
        names = sorted(
            {
                a.get("name", "")
                for a in self.history.get("actors", [])
                if a.get("name")
            },
            key=str.casefold,
        )
        name = self._pick_from_history(
            "Актёр — имя",
            "Имя (можно выбрать из истории или ввести новое):",
            names or [""],
        )
        if not name:
            return

        # роли, которые уже встречались с этим именем + все роли
        roles_for_name = [
            a.get("role", "")
            for a in self.history.get("actors", [])
            if a.get("name") == name and a.get("role")
        ]
        all_roles = sorted(
            {
                a.get("role", "")
                for a in self.history.get("actors", [])
                if a.get("role")
            },
            key=str.casefold,
        )
        # предпочитаем роли этого актёра
        role_items = roles_for_name + [r for r in all_roles if r not in roles_for_name]
        if not role_items:
            role_items = [""]

        role, ok = QInputDialog.getItem(
            self,
            "Актёр — роль",
            "Роль (можно выбрать из истории или ввести новую, можно оставить пустой):",
            role_items,
            0,
            editable=True,
        )
        if not ok:
            return

        name = name.strip() if name else ""
        role = role.strip() if role else ""

        r = self.table_actors.rowCount()
        self.table_actors.insertRow(r)
        self.table_actors.setItem(r, 0, QTableWidgetItem(name))
        self.table_actors.setItem(r, 1, QTableWidgetItem(role))

        add_actor_to_history(self.history, name, role)

    def remove_actor(self):
        sel = self.table_actors.selectionModel().selectedRows()
        rows = sorted([s.row() for s in sel], reverse=True)
        for r in rows:
            self.table_actors.removeRow(r)


def main():
    app = QApplication(sys.argv)
    initial_file = sys.argv[1] if len(sys.argv) > 1 else None
    win = NfoEditorWindow(initial_file)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

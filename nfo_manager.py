#!/usr/bin/env python3
"""
Simple .nfo editor (single-file) using PyQt6.
Features:
- Left panel: all .mp4 files in the current folder (optional subfolders)
- For each .mp4, looks for a matching .nfo (same name, .nfo extension)
- If .nfo exists — loads it; if not — starts with empty fields
- Edit main movie fields: title, originaltitle, year, plot, original_filename
- Edit studios, genres (categories), actors (name + role), and tags
- Preserve other XML nodes when saving (only update the nodes we touch)
- History of previously used studios, genres, tags and actors (saved to config)

Dependencies:
    pip install PyQt6

Run:
    python3 nfo_editor_pyqt.py [path_to_file.mp4 | path_to_file.nfo | path_to_folder]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QPixmap,
)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from aspect_ratio_label import AspectRatioLabel
from clickable_slider import ClickableSlider
from preview_worker import PreviewWorker
from video_info_worker import VideoInfoWorker

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
    "last_folder": "",
    "recursive": False,
}


def load_history() -> dict:
    try:
        if HISTORY_PATH.exists():
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
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
    if value in lst:
        lst.remove(value)
    lst.append(value)
    save_history(history)


def add_actor_to_history(history: dict, name: str, role: str):
    name = name.strip()
    role = role.strip()
    if not name:
        return
    actors = history.setdefault("actors", [])
    entry = {"name": name, "role": role}
    if entry in actors:
        actors.remove(entry)
    actors.append(entry)
    save_history(history)


def iter_mp4_files(folder: Path, recursive: bool):
    """Yield .mp4 paths in folder. Skips hidden directories when recursive."""
    if not folder or not folder.is_dir():
        return
    if not recursive:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() == ".mp4":
                yield p
        return
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.lower().endswith(".mp4"):
                yield Path(dirpath) / name


# --- NFO document -----------------------------------------------------------
class NfoDocument:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        self.video_path: Optional[Path] = None
        self.tree: Optional[ET.ElementTree] = None
        self.root: Optional[ET.Element] = None

    def load(self, path: Path):
        self.path = Path(path)
        self.tree = ET.parse(self.path)
        self.root = self.tree.getroot()
        # предполагаемое видео — с тем же именем, но .mp4
        potential_video = self.path.with_suffix(".mp4")
        self.video_path = potential_video if potential_video.exists() else None

    def new_empty(self, video_path: Path):
        """Создаёт пустой документ, привязанный к видео-файлу.
        NFO будет сохранён по пути video_path.with_suffix('.nfo')."""
        self.video_path = Path(video_path)
        self.path = self.video_path.with_suffix(".nfo")
        self.root = ET.Element("movie")
        self.tree = ET.ElementTree(self.root)

    def save(self, path: Optional[Path] = None):
        if path:
            self.path = Path(path)
        if not self.path:
            raise RuntimeError("No document path")
        if self.root is None:
            # если корня ещё нет (например, после new_empty без изменений) — создаём
            self.root = ET.Element("movie")
            self.tree = ET.ElementTree(self.root)
        self._indent(self.root)
        self.tree.write(str(self.path), encoding="utf-8", xml_declaration=True)

    def _indent(self, elem, level=0):
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            for e in elem:
                self._indent(e, level + 1)
            if not e.tail or not e.tail.strip():
                e.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    def get_text(self, tag: str) -> str:
        if self.root is None:
            return ""
        if tag == "set":
            set_el = self.root.find("set")
            if set_el is not None:
                name_el = set_el.find("name")
                if name_el is not None and name_el.text is not None:
                    return name_el.text.strip()
            return ""
        el = self.root.find(tag)
        return el.text if el is not None and el.text is not None else ""

    def set_text(self, tag: str, text: str):
        if self.root is None:
            return
        if tag == "set":
            for e in list(self.root.findall("set")):
                self.root.remove(e)
            set_el = ET.SubElement(self.root, "set")
            name_el = ET.SubElement(set_el, "name")
            name_el.text = text.strip()
            return
        el = self.root.find(tag)
        if el is None:
            el = ET.SubElement(self.root, tag)
        el.text = text.strip()

    def get_studios(self):
        if self.root is None:
            return []
        return [g.text for g in self.root.findall("studio") if g.text]

    def set_studios(self, studios):
        if self.root is None:
            return
        for g in list(self.root.findall("studio")):
            self.root.remove(g)
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
        for g in list(self.root.findall("genre")):
            self.root.remove(g)
        for g in genres:
            el = ET.SubElement(self.root, "genre")
            el.text = g

    def get_tags(self):
        if self.root is None:
            return []
        return sorted([t.text for t in self.root.findall("tag") if t.text])

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
    def __init__(self, initial_path: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("NFO Editor")
        self.resize(1200, 740)
        self.setAcceptDrops(True)

        self.doc = NfoDocument()
        self.history = load_history()
        self.current_folder: Optional[Path] = None
        self._dirty = False
        self._loading = False
        self._ignore_selection = False
        self._mp4_paths: list[Path] = []
        self._preview_workers: list[PreviewWorker] = []
        self._current_preview_path: Optional[str] = None

        self._video_info_workers: list[VideoInfoWorker] = []
        self._video_info_cache: dict[str, dict] = {}

        self._previous_volume = 100
        self._is_muted = False

        self._build_ui()
        self._connect_dirty_signals()

        if initial_path:
            self._open_initial_path(Path(initial_path))
        else:
            last = self.history.get("last_folder") or ""
            if last and Path(last).is_dir():
                self._open_folder(Path(last), autoload_first=True)

    def _load_video_info(self, mp4_path: Path):
        """Запускает асинхронную загрузку метаданных видео."""
        mp4_str = str(mp4_path)

        # если уже в кэше — ничего не делаем
        if mp4_str in self._video_info_cache:
            return

        # отменяем старые воркеры для этого файла
        for worker in self._video_info_workers:
            if str(worker.mp4_path) == mp4_str and worker.isRunning():
                worker.requestInterruption()

        worker = VideoInfoWorker(mp4_path, self)
        worker.finished.connect(self._on_video_info_ready)
        worker.failed.connect(self._on_video_info_failed)
        worker.finished.connect(lambda: self._remove_video_info_worker(worker))
        worker.failed.connect(lambda: self._remove_video_info_worker(worker))
        self._video_info_workers.append(worker)
        worker.start()

    def _remove_video_info_worker(self, worker: VideoInfoWorker):
        if worker in self._video_info_workers:
            self._video_info_workers.remove(worker)
        worker.deleteLater()

    def _on_video_info_ready(self, video_path: str, info: dict):
        """Сохраняет метаданные и обновляет tooltip."""
        self._video_info_cache[video_path] = info
        # находим элемент в списке и обновляем tooltip
        for i in range(self.list_files.count()):
            item = self.list_files.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == video_path:
                self._update_item_tooltip(item)
                break
        if self.doc.video_path and str(self.doc.video_path) == video_path:
            self._update_file_info(self.doc.video_path)

    def _update_item_tooltip(self, item: QListWidgetItem):
        """Обновляет tooltip с метаданными."""
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        info = self._video_info_cache.get(str(path), {})

        lines = [str(path)]
        if info:
            if "quality" in info:
                lines.append(f"Качество: {info['quality']}")
            if "resolution" in info:
                lines.append(f"Разрешение: {info['resolution']}")
            if "codec" in info:
                lines.append(f"Кодек: {info['codec']}")
            if "duration" in info:
                mins = int(info["duration"] // 60)
                secs = int(info["duration"] % 60)
                lines.append(f"Длительность: {mins}:{secs:02d}")
            if "size_mb" in info:
                lines.append(f"Размер: {info['size_mb']:.1f} MB")

        item.setToolTip("\n".join(lines))

    def _on_video_info_failed(self, video_path: str):
        # можно добавить заглушку в кэш
        self._video_info_cache[video_path] = {}

    def _check_subtitles(self, mp4_path: Path) -> dict:
        """Проверяет наличие субтитров для видео."""
        base = mp4_path.stem
        folder = mp4_path.parent
        subs = {"en": False, "ru": False}
        if (folder / f"{base}.en.srt").exists():
            subs["en"] = True
        if (folder / f"{base}.ru.srt").exists():
            subs["ru"] = True
        return subs

    def _open_initial_path(self, path: Path):
        try:
            path = path.expanduser().resolve()
        except Exception:
            path = path.expanduser()
        if path.is_dir():
            self._open_folder(path, autoload_first=True)
            return
        suffix = path.suffix.lower()
        if suffix == ".nfo":
            # ищем соответствующий mp4
            mp4 = path.with_suffix(".mp4")
            if mp4.exists():
                self._open_folder(path.parent, select=mp4)
            else:
                # mp4 нет — просто открываем папку
                self._open_folder(path.parent, autoload_first=True)
            return
        if suffix == ".mp4":
            self._open_folder(path.parent, select=path)
            return
        # другой файл — открываем его папку
        self._open_folder(path.parent, autoload_first=True)

    def _build_ui(self):
        self._build_toolbar()
        self.statusBar().showMessage("Откройте папку с видео")

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        central.setLayout(main_layout)

        outer = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(outer)

        outer.addWidget(self._build_file_panel())

        inner = QSplitter(Qt.Orientation.Horizontal)
        inner.addWidget(self._build_form_panel())
        inner.addWidget(self._build_actors_panel())
        inner.setSizes([480, 460])
        inner.setStretchFactor(0, 1)
        inner.setStretchFactor(1, 1)

        outer.addWidget(inner)
        outer.setSizes([280, 900])
        outer.setStretchFactor(0, 0)
        outer.setStretchFactor(1, 1)
        outer.setChildrenCollapsible(False)

    def _build_toolbar(self):
        tb = QToolBar("Главная")
        tb.setMovable(False)
        tb.setIconSize(tb.iconSize())
        self.addToolBar(tb)

        style = self.style()

        act_folder = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            "Папка",
            self,
        )
        act_folder.setShortcut(QKeySequence("Ctrl+O"))
        act_folder.setToolTip("Открыть папку (Ctrl+O)")
        act_folder.triggered.connect(self.open_folder)
        tb.addAction(act_folder)

        act_file = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Файл",
            self,
        )
        act_file.setShortcut(QKeySequence("Ctrl+Shift+O"))
        act_file.setToolTip("Открыть .nfo файл напрямую (Ctrl+Shift+O)")
        act_file.triggered.connect(self.open_file)
        tb.addAction(act_file)

        tb.addSeparator()

        act_save = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "Сохранить",
            self,
        )
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.setToolTip("Сохранить (Ctrl+S)")
        act_save.triggered.connect(self.save_file)
        tb.addAction(act_save)

        tb.addSeparator()

        act_refresh = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
            "Обновить",
            self,
        )
        act_refresh.setShortcut(QKeySequence("F5"))
        act_refresh.setToolTip("Обновить список файлов (F5)")
        act_refresh.triggered.connect(self.refresh_file_list)
        tb.addAction(act_refresh)

    def _build_file_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(220)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 4, 0)
        panel.setLayout(layout)

        header = QHBoxLayout()
        title = QLabel("Видео (.mp4)")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        self.lbl_file_count = QLabel("0")
        self.lbl_file_count.setStyleSheet("color: palette(mid);")
        header.addWidget(self.lbl_file_count)
        layout.addLayout(header)

        legend = QLabel("● — есть .nfo, ○ — нет, [EN/RU] — субтитры")
        legend.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(legend)

        self.lbl_folder = QLabel("Папка не выбрана")
        self.lbl_folder.setWordWrap(True)
        self.lbl_folder.setStyleSheet("color: palette(mid);")
        self.lbl_folder.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.lbl_folder)

        self.file_filter = QLineEdit()
        self.file_filter.setPlaceholderText("Фильтр…")
        self.file_filter.setClearButtonEnabled(True)
        self.file_filter.textChanged.connect(self._apply_file_filter)
        layout.addWidget(self.file_filter)

        self.list_files = QListWidget()
        self.list_files.setAlternatingRowColors(True)
        self.list_files.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_files.setUniformItemSizes(True)
        self.list_files.currentItemChanged.connect(self._on_file_current_changed)
        self.list_files.itemDoubleClicked.connect(self._on_file_double_clicked)
        layout.addWidget(self.list_files, 1)

        self.chk_recursive = QCheckBox("Включая подпапки")
        self.chk_recursive.setChecked(bool(self.history.get("recursive")))
        self.chk_recursive.toggled.connect(self._on_recursive_toggled)
        layout.addWidget(self.chk_recursive)

        btns = QHBoxLayout()
        btn_folder = QPushButton("Папка…")
        btn_folder.clicked.connect(self.open_folder)
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self.refresh_file_list)
        btns.addWidget(btn_folder)
        btns.addWidget(btn_refresh)
        layout.addLayout(btns)

        return panel

    def _build_form_panel(self) -> QWidget:
        left = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(4, 0, 4, 0)
        left.setLayout(left_layout)

        form = QWidget()
        form_layout = QVBoxLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form.setLayout(form_layout)

        self.fields = {}
        for name in NAMES:
            lbl = QLabel(TITLES[name])
            if name == "plot":
                widget = QTextEdit()
                widget.setAcceptRichText(False)
                widget.setMinimumHeight(90)
                widget.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                )
                row = QVBoxLayout()
                row.addWidget(lbl)
                row.addWidget(widget)
            else:
                widget = QLineEdit()
                row = QVBoxLayout()
                row.addWidget(lbl)
                if name == "original_filename":
                    h = QHBoxLayout()
                    h.addWidget(widget)
                    btn_browse = QPushButton("▶")
                    btn_browse.setFixedWidth(30)
                    btn_browse.setToolTip("Открыть медиафайл")
                    btn_browse.clicked.connect(self.browse_original_file)
                    h.addWidget(btn_browse)
                    row.addLayout(h)
                else:
                    row.addWidget(widget)
            self.fields[name] = widget
            form_layout.addLayout(row)

        left_layout.addWidget(form, 1)

        left_layout.addWidget(self._build_list_box("Студии", "studios"))
        left_layout.addWidget(self._build_list_box("Теги", "tags"))

        self.video_preview = AspectRatioLabel()
        self.video_preview.setMaximumHeight(270)
        self.video_preview.setMinimumHeight(270)
        self.video_preview.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        left_layout.addWidget(self.video_preview, 1)

        # left_layout.addWidget(QLabel("Превью видео"))
        self.video_widget = QVideoWidget()
        self.video_widget.setMaximumHeight(270)
        self.video_widget.setMinimumHeight(270)
        self.video_widget.setStyleSheet("background: black;")
        self.video_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video_widget.setStyleSheet("background: #2b2b2b;")
        self.video_widget.hide()
        # self.video_widget.setToolTip("← → перемотка ±10 сек, ↑ ↓ ±1 мин")
        left_layout.addWidget(self.video_widget, 1)

        self.video_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.video_slider.setEnabled(False)
        self.video_slider.sliderPressed.connect(self._on_slider_pressed)
        self.video_slider.sliderReleased.connect(self._on_slider_released)
        self.video_slider.sliderMoved.connect(self._on_slider_moved)
        left_layout.addWidget(self.video_slider)

        self.video_preview.installEventFilter(self)
        self.video_widget.installEventFilter(self)

        # кнопки управления
        video_btns = QHBoxLayout()
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(40)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_stop = QPushButton("■")
        self.btn_stop.setFixedWidth(40)
        self.btn_stop.clicked.connect(self._stop_video)
        video_btns.addWidget(self.btn_play)
        video_btns.addWidget(self.btn_stop)
        video_btns.addStretch()

        self.lbl_volume = QLabel("🔊")
        self.lbl_volume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_volume.setToolTip("Клик — mute/unmute")
        self.lbl_volume.installEventFilter(self)
        video_btns.addWidget(self.lbl_volume)
        self.volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setToolTip("Громкость")
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        video_btns.addWidget(self.volume_slider)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("color: palette(mid); font-family: monospace;")
        video_btns.addWidget(self.lbl_time)

        left_layout.addLayout(video_btns)

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.positionChanged.connect(self._update_time_display)
        self.media_player.durationChanged.connect(self._update_duration)
        self._video_duration = 0

        self._slider_pressed = False

        return left

    def _update_file_info(self, mp4_path: Path):
        """Обновляет отображение информации о файле."""
        if not mp4_path or not mp4_path.exists():
            self.lbl_file_info.setText("Файл не найден")
            return

        lines = []

        # имя файла
        lines.append(f"<b>Файл:</b> {mp4_path.name}")

        # качество и метаданные
        info = self._video_info_cache.get(str(mp4_path), {})
        if info:
            if "quality" in info:
                lines.append(f"<b>Качество:</b> {info['quality']}")
            if "resolution" in info:
                lines.append(f"<b>Разрешение:</b> {info['resolution']}")
            if "codec" in info:
                lines.append(f"<b>Кодек:</b> {info['codec']}")
            if "duration" in info:
                mins = int(info["duration"] // 60)
                secs = int(info["duration"] % 60)
                lines.append(f"<b>Длительность:</b> {mins}:{secs:02d}")
            if "size_mb" in info:
                lines.append(f"<b>Размер:</b> {info['size_mb']:.1f} MB")
        else:
            lines.append("<i>Загрузка метаданных...</i>")

        # субтитры
        subs = self._check_subtitles(mp4_path)
        sub_list = []
        if subs["en"]:
            sub_list.append("Английские")
        if subs["ru"]:
            sub_list.append("Русские")
        if sub_list:
            lines.append(f"<b>Субтитры:</b> {', '.join(sub_list)}")
        else:
            lines.append("<b>Субтитры:</b> нет")

        self.lbl_file_info.setText("<br>".join(lines))

    def _on_volume_changed(self, value: int):
        """Устанавливает громкость (0-100 -> 0.0-1.0)."""
        self.audio_output.setVolume(value / 100.0)

    def _build_list_box(self, title: str, kind: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 8, 0, 0)
        box.setLayout(layout)
        layout.addWidget(QLabel(title))
        lst = QListWidget()
        lst.setMaximumHeight(120)
        layout.addWidget(lst)
        row = QHBoxLayout()
        btn_add = QPushButton("Добавить")
        btn_remove = QPushButton("Удалить")
        row.addWidget(btn_add)
        row.addWidget(btn_remove)
        layout.addLayout(row)

        if kind == "studios":
            self.list_studios = lst
            btn_add.clicked.connect(self.add_studio)
            btn_remove.clicked.connect(self.remove_studio)
        elif kind == "genres":
            self.list_genres = lst
            btn_add.clicked.connect(self.add_genre)
            btn_remove.clicked.connect(self.remove_genre)
        else:
            self.list_tags = lst
            btn_add.clicked.connect(self.add_tag)
            btn_remove.clicked.connect(self.remove_tag)
        return box

    def _build_actors_panel(self) -> QWidget:
        right = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(4, 0, 0, 0)
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
        self.table_actors.itemChanged.connect(self._on_actor_item_changed)
        right_layout.addWidget(self.table_actors, 1)

        aa = QHBoxLayout()
        btn_add_actor = QPushButton("Добавить актёра")
        btn_add_actor.clicked.connect(self.add_actor)
        btn_remove_actor = QPushButton("Удалить актёра")
        btn_remove_actor.clicked.connect(self.remove_actor)
        aa.addWidget(btn_add_actor)
        aa.addWidget(btn_remove_actor)
        aa.addStretch()
        right_layout.addLayout(aa)

        right_layout.addWidget(self._build_list_box("Жанры", "genres"))

        right_layout.addWidget(QLabel("Исходный XML (предпросмотр)"))
        self.raw_xml = QTextEdit()
        self.raw_xml.setReadOnly(True)
        self.raw_xml.setMinimumHeight(300)
        right_layout.addWidget(self.raw_xml)

        # Информация о файле
        info_box = QWidget()
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 8)
        info_box.setLayout(info_layout)

        info_layout.addWidget(QLabel("Информация о файле").setStyleSheet("font-weight: 600;"))

        self.lbl_file_info = QLabel()
        self.lbl_file_info.setWordWrap(True)
        self.lbl_file_info.setStyleSheet("background: palette(window); padding: 8px; border-radius: 4px;")
        self.lbl_file_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.lbl_file_info)

        right_layout.addWidget(info_box)

        return right

    def _connect_dirty_signals(self):
        for name, widget in self.fields.items():
            if isinstance(widget, QTextEdit):
                widget.textChanged.connect(self._mark_dirty)
            else:
                widget.textChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_args):
        if self._loading:
            return
        if not self._dirty:
            self._dirty = True
            self._update_title()
            self._refresh_current_list_mark()

    def _on_actor_item_changed(self, _item):
        self._mark_dirty()

    def _update_title(self):
        if self.doc.path:
            name = self.doc.path.name
            mark = " •" if self._dirty else ""
            new_mark = " [новый]" if self._is_new_document() else ""
            self.setWindowTitle(f"{name}{new_mark}{mark} — NFO Editor")
        else:
            self.setWindowTitle("NFO Editor")

    def _is_new_document(self) -> bool:
        """Документ считается 'новым', если nfo-файл ещё не сохранён на диск."""
        if not self.doc.path:
            return True
        return not self.doc.path.exists()

    def _refresh_current_list_mark(self):
        current_mp4 = self.doc.video_path
        current_res = None
        if current_mp4:
            try:
                current_res = current_mp4.resolve()
            except Exception:
                current_res = current_mp4

        for i in range(self.list_files.count()):
            item = self.list_files.item(i)
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            label = self._item_label(path)
            if (
                current_res is not None
                and self._dirty
                and self._paths_equal(path, current_res)
            ):
                label = f"{label} •"
            item.setText(label)

    def _item_label(self, mp4_path: Path) -> str:
        """Формирует подпись элемента списка с маркерами."""
        base = self._display_name(mp4_path)
        nfo_path = mp4_path.with_suffix(".nfo")
        prefix = "● " if nfo_path.exists() else "○ "

        # маркеры субтитров
        subs = self._check_subtitles(mp4_path)
        sub_marks = []
        if subs["en"]:
            sub_marks.append("EN")
        if subs["ru"]:
            sub_marks.append("RU")

        sub_suffix = f" [{', '.join(sub_marks)}] " if sub_marks else ""

        return prefix + sub_suffix + base

    def _display_name(self, path: Path) -> str:
        if self.current_folder and self.chk_recursive.isChecked():
            try:
                return str(path.relative_to(self.current_folder))
            except ValueError:
                return path.name
        return path.name

    def _elide_folder(self, folder: Path) -> str:
        text = str(folder)
        if len(text) <= 48:
            return text
        return "…" + text[-47:]

    def _paths_equal(self, a: Path, b) -> bool:
        try:
            return Path(a).resolve() == Path(b).resolve()
        except Exception:
            return Path(a) == Path(b)

    # ---------- folder / file list ----------
    def open_folder(self):
        start = str(self.current_folder) if self.current_folder else ""
        path = QFileDialog.getExistingDirectory(self, "Открыть папку с видео", start)
        if not path:
            return
        if not self._confirm_leave():
            return
        self._open_folder(Path(path), autoload_first=True)

    def _on_recursive_toggled(self, checked: bool):
        self.history["recursive"] = bool(checked)
        save_history(self.history)
        if self.current_folder:
            select = self.doc.video_path
            self._scan_and_fill(select=select)

    def refresh_file_list(self):
        if not self.current_folder:
            self.statusBar().showMessage("Сначала откройте папку", 3000)
            return
        self._scan_and_fill(select=self.doc.video_path)
        self.statusBar().showMessage("Список файлов обновлён", 2000)

    def _open_folder(
        self,
        folder: Path,
        select: Optional[Path] = None,
        autoload_first: bool = False,
    ):
        folder = Path(folder)
        if not folder.is_dir():
            QMessageBox.warning(self, "Ошибка", f"Это не папка:\n{folder}")
            return
        self.current_folder = folder
        self.history["last_folder"] = str(folder)
        save_history(self.history)
        self.lbl_folder.setText(self._elide_folder(folder))
        self.lbl_folder.setToolTip(str(folder))
        self._scan_and_fill(select=select)

        target: Optional[Path] = None
        if select is not None:
            target = Path(select)
        elif autoload_first and self._mp4_paths:
            target = self._mp4_paths[0]

        if target is not None:
            self._load_for_mp4(target)
        elif not self._mp4_paths:
            self._clear_editor()
            self.statusBar().showMessage("В папке нет .mp4 файлов", 4000)

    def _scan_and_fill(self, select: Optional[Path] = None):
        folder = self.current_folder
        if folder is None:
            return
        files = sorted(
            iter_mp4_files(folder, self.chk_recursive.isChecked()),
            key=lambda p: str(p).casefold(),
        )
        self._mp4_paths = files
        visible_n = 0

        self._ignore_selection = True
        self.list_files.clear()
        select_item = None
        select_res = None
        if select is not None:
            try:
                select_res = Path(select).resolve()
            except Exception:
                select_res = Path(select)

        for path in files:
            label = self._item_label(path)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setData(Qt.ItemDataRole.UserRole + 1, self._build_search_text(path))
            item.setToolTip(str(path))
            # если nfo ещё нет — делаем текст чуть бледнее
            nfo_path = path.with_suffix(".nfo")
            if not nfo_path.exists():
                palette = self.list_files.palette()
                color = palette.color(
                    palette.ColorGroup.Disabled, palette.ColorRole.Text
                )
                from PyQt6.QtGui import QBrush

                item.setForeground(QBrush(color))
            self.list_files.addItem(item)
            self._update_item_tooltip(item)
            self._load_video_info(path)
            if select_res is not None and self._paths_equal(path, select_res):
                select_item = item

        self._apply_file_filter()
        for i in range(self.list_files.count()):
            if not self.list_files.item(i).isHidden():
                visible_n += 1
        self.lbl_file_count.setText(str(len(files)))

        if select_item is not None:
            self.list_files.setCurrentItem(select_item)
        self._ignore_selection = False
        self._refresh_current_list_mark()

        if self.current_folder:
            extra = f", показано {visible_n}" if visible_n != len(files) else ""
            self.statusBar().showMessage(f"{folder} — {len(files)} .mp4{extra}", 4000)

    def _apply_file_filter(self):
        q = self.file_filter.text().strip().casefold()
        for i in range(self.list_files.count()):
            item = self.list_files.item(i)
            if not q:
                item.setHidden(False)
                continue
            search_text = item.data(Qt.ItemDataRole.UserRole + 1) or ""
            item.setHidden(q not in search_text.casefold())

    def _on_file_current_changed(self, current: Optional[QListWidgetItem], _previous):
        if self._ignore_selection or current is None:
            return
        mp4_path = Path(current.data(Qt.ItemDataRole.UserRole))
        if self.doc.video_path and self._paths_equal(mp4_path, self.doc.video_path):
            return
        if not self._confirm_leave():
            self._reselect_current_doc()
            return
        self._load_for_mp4(mp4_path)

    def _on_file_double_clicked(self, item: QListWidgetItem):
        mp4_path = Path(item.data(Qt.ItemDataRole.UserRole))
        if self.doc.video_path and self._paths_equal(mp4_path, self.doc.video_path):
            return
        if not self._confirm_leave():
            self._reselect_current_doc()
            return
        self._load_for_mp4(mp4_path)

    def _reselect_current_doc(self):
        current_mp4 = self.doc.video_path
        if not current_mp4:
            return
        self._ignore_selection = True
        target = None
        try:
            current_res = current_mp4.resolve()
        except Exception:
            current_res = current_mp4
        for i in range(self.list_files.count()):
            item = self.list_files.item(i)
            p = Path(item.data(Qt.ItemDataRole.UserRole))
            if self._paths_equal(p, current_res):
                target = item
                break
        if target is not None:
            self.list_files.setCurrentItem(target)
        self._ignore_selection = False

    def _load_for_mp4(self, mp4_path: Path) -> bool:
        """Загружает .nfo для данного .mp4, либо создаёт пустой документ."""
        mp4_path = Path(mp4_path)
        nfo_path = mp4_path.with_suffix(".nfo")
        try:
            self._loading = True
            if nfo_path.exists():
                self.doc.load(nfo_path)
                # на всякий случай явно выставим video_path
                self.doc.video_path = mp4_path
            else:
                self.doc.new_empty(mp4_path)
            self._populate_from_doc()
            self._dirty = False
            self._update_title()
            self._reselect_current_doc()
            self._refresh_current_list_mark()
            status = (
                f"{nfo_path}"
                if nfo_path.exists()
                else f"{nfo_path} (новый, не сохранён)"
            )

            # загружаем видео в плеер
            self.media_player.stop()
            self.media_player.setSource(QUrl.fromLocalFile(str(mp4_path)))
            self._extract_preview_frame(mp4_path)
            self.video_slider.setEnabled(False)
            self.video_slider.setValue(0)
            self._video_duration = 0
            self.lbl_time.setText("00:00 / 00:00")
            self.btn_play.setText("▶")

            self.statusBar().showMessage(status, 4000)
            self._update_file_info(mp4_path)
            return True
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось открыть файл:\n{nfo_path}\n\n{e}"
            )
            return False
        finally:
            self._loading = False

    def _clear_editor(self):
        self._loading = True
        self.doc = NfoDocument()
        self.lbl_file_info.setText("Файл не выбран")
        for name, widget in self.fields.items():
            if isinstance(widget, QTextEdit):
                widget.setPlainText("")
            else:
                widget.setText("")
        self.list_studios.clear()
        self.list_genres.clear()
        self.list_tags.clear()
        self.table_actors.setRowCount(0)
        self.raw_xml.setPlainText("")
        self._dirty = False
        self._update_title()
        self._loading = False

    def _confirm_leave(self) -> bool:
        if not self._dirty:
            return True
        name = self.doc.path.name if self.doc.path else "документ"
        box = QMessageBox(self)
        box.setWindowTitle("Несохранённые изменения")
        box.setText(f"Файл «{name}» изменён.")
        box.setInformativeText("Сохранить изменения перед переключением?")
        box.setIcon(QMessageBox.Icon.Question)
        btn_save = box.addButton("Сохранить", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Не сохранять", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_cancel:
            return False
        if clicked is btn_save:
            return self.save_file()
        self._dirty = False
        return True

    def closeEvent(self, event: QCloseEvent):
        self.media_player.stop()
        if self._confirm_leave():
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if not path.exists():
            return
        if not self._confirm_leave():
            return
        suffix = path.suffix.lower()
        if path.is_dir():
            self._open_folder(path, autoload_first=True)
        elif suffix == ".mp4":
            self._open_folder(path.parent, select=path)
        elif suffix == ".nfo":
            # ищем соответствующий mp4
            mp4 = path.with_suffix(".mp4")
            if mp4.exists():
                self._open_folder(path.parent, select=mp4)
            else:
                self._open_folder(path.parent, autoload_first=True)
        else:
            self._open_folder(path.parent, autoload_first=True)

    def browse_original_file(self):
        # приоритет — video_path, потом папка nfo
        if self.doc.video_path and self.doc.video_path.exists():
            target = self.doc.video_path
        else:
            filename = self.fields["original_filename"].text().strip()
            if not filename:
                QMessageBox.warning(self, "Ошибка", "Поле пустое")
                return
            base_dir = self.doc.path.parent if self.doc.path else None
            target_str = os.path.join(str(base_dir), filename) if base_dir else filename
            target = Path(target_str)

        if not target.exists():
            QMessageBox.warning(self, "Ошибка", f"Файл не найден: {target}")
            return
        try:
            if sys.platform.startswith("darwin"):
                subprocess.Popen(["open", str(target)])
            elif os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                for cmd in (["mpv", str(target)], ["xdg-open", str(target)]):
                    try:
                        subprocess.Popen(cmd)
                        break
                    except FileNotFoundError:
                        continue
                else:
                    raise FileNotFoundError("mpv / xdg-open")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл: {e}")

    def open_file(self):
        start = str(self.current_folder) if self.current_folder else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть .nfo напрямую",
            start,
            "NFO files (*.nfo);;XML files (*.xml);;All files (*)",
        )
        if not path:
            return
        if not self._confirm_leave():
            return
        p = Path(path)
        # открываем папку и пытаемся выбрать соответствующий mp4
        mp4 = p.with_suffix(".mp4")
        if mp4.exists():
            self._open_folder(p.parent, select=mp4)
        else:
            # mp4 нет — просто открываем папку
            self._open_folder(p.parent, autoload_first=True)

    def save_file(self) -> bool:
        if not self.doc.path:
            return self.save_file_as()
        try:
            self._update_doc_from_ui()
            self.doc.save()
            self._dirty = False
            self._update_title()
            # обновляем маркер ●/○ у текущего элемента (nfo теперь существует)
            self._refresh_current_list_mark()
            self.statusBar().showMessage(f"Сохранено: {self.doc.path}", 3000)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{e}")
            return False

    def save_file_as(self) -> bool:
        start = (
            str(self.doc.path)
            if self.doc.path
            else (str(self.current_folder) if self.current_folder else "")
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить как",
            start,
            "NFO files (*.nfo);;XML files (*.xml);;All files (*)",
        )
        if not path:
            return False
        try:
            self._update_doc_from_ui()
            self.doc.save(Path(path))
            self._dirty = False
            if self.current_folder is None:
                self.current_folder = Path(path).parent
            self._scan_and_fill(select=self.doc.video_path)
            self._update_title()
            self.statusBar().showMessage(f"Сохранено: {path}", 3000)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{e}")
            return False

    def _populate_from_doc(self):
        if self.doc.root is None:
            return
        for name in NAMES:
            value = self.doc.get_text(name)
            widget = self.fields[name]
            if isinstance(widget, QTextEdit):
                widget.setPlainText(value)
            else:
                widget.setText(value)

        self.list_studios.clear()
        for s in self.doc.get_studios():
            self.list_studios.addItem(s)

        self.list_genres.clear()
        for g in self.doc.get_genres():
            self.list_genres.addItem(g)

        self.list_tags.clear()
        for t in self.doc.get_tags():
            self.list_tags.addItem(t)

        self.table_actors.blockSignals(True)
        self.table_actors.setRowCount(0)
        for name, role in self.doc.get_actors():
            r = self.table_actors.rowCount()
            self.table_actors.insertRow(r)
            self.table_actors.setItem(r, 0, QTableWidgetItem(name))
            self.table_actors.setItem(r, 1, QTableWidgetItem(role))
        self.table_actors.blockSignals(False)

        self._refresh_raw()

    def _update_doc_from_ui(self):
        for name in NAMES:
            widget = self.fields[name]
            text = (
                widget.toPlainText() if isinstance(widget, QTextEdit) else widget.text()
            )
            self.doc.set_text(name, text)

        studios = [
            self.list_studios.item(i).text() for i in range(self.list_studios.count())
        ]
        self.doc.set_studios(studios)

        genres = [
            self.list_genres.item(i).text() for i in range(self.list_genres.count())
        ]
        self.doc.set_genres(genres)

        tags = [self.list_tags.item(i).text() for i in range(self.list_tags.count())]
        self.doc.set_tags(tags)

        actors = []
        for r in range(self.table_actors.rowCount()):
            name_item = self.table_actors.item(r, 0)
            role_item = self.table_actors.item(r, 1)
            name = name_item.text() if name_item else ""
            role = role_item.text() if role_item else ""
            actors.append((name, role))
        self.doc.set_actors(actors)
        self._refresh_raw()

    def _refresh_raw(self):
        if self.doc.tree is None or self.doc.root is None:
            self.raw_xml.setPlainText("")
            return
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
            self._mark_dirty()

    def remove_studio(self):
        for item in self.list_studios.selectedItems():
            self.list_studios.takeItem(self.list_studios.row(item))
            self._mark_dirty()

    def add_genre(self):
        text = self._pick_from_history(
            "Добавить жанр",
            "Название жанра (можно выбрать из истории или ввести новое):",
            self.history.get("genres", []),
        )
        if text:
            self.list_genres.addItem(text)
            add_to_history_list(self.history, "genres", text)
            self._mark_dirty()

    def remove_genre(self):
        for item in self.list_genres.selectedItems():
            self.list_genres.takeItem(self.list_genres.row(item))
            self._mark_dirty()

    def add_tag(self):
        text = self._pick_from_history(
            "Добавить тег",
            "Тег (можно выбрать из истории или ввести новое):",
            self.history.get("tags", []),
        )
        if text:
            self.list_tags.addItem(text)
            add_to_history_list(self.history, "tags", text)
            self._mark_dirty()

    def remove_tag(self):
        items = self.list_tags.selectedItems()
        for it in items:
            self.list_tags.takeItem(self.list_tags.row(it))
            self._mark_dirty()

    def add_actor(self):
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
        self.table_actors.blockSignals(True)
        r = self.table_actors.rowCount()
        self.table_actors.insertRow(r)
        self.table_actors.setItem(r, 0, QTableWidgetItem(name))
        self.table_actors.setItem(r, 1, QTableWidgetItem(role))
        self.table_actors.blockSignals(False)
        add_actor_to_history(self.history, name, role)
        self._mark_dirty()

    def remove_actor(self):
        sel = self.table_actors.selectionModel().selectedRows()
        rows = sorted([s.row() for s in sel], reverse=True)
        if not rows:
            return
        self.table_actors.blockSignals(True)
        for r in rows:
            self.table_actors.removeRow(r)
        self.table_actors.blockSignals(False)
        self._mark_dirty()

    def _toggle_play(self):
        self.video_preview.hide()
        self.video_widget.show()
        self.video_widget.setFocus()
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.btn_play.setText("▶")
        else:
            self.media_player.play()
            self.btn_play.setText("❚❚")

    def _stop_video(self):
        self.video_preview.hide()
        self.video_widget.show()
        self.media_player.stop()
        self.media_player.setPosition(0)
        self.btn_play.setText("▶")

    def _build_search_text(self, mp4_path: Path) -> str:
        """Собирает строку для поиска: имя файла + поля из .nfo (если есть)."""
        parts = [mp4_path.name]
        nfo_path = mp4_path.with_suffix(".nfo")
        if nfo_path.exists():
            try:
                tree = ET.parse(nfo_path)
                root = tree.getroot()
                # простые текстовые поля
                for tag in ("title", "originaltitle", "year", "plot"):
                    el = root.find(tag)
                    if el is not None and el.text:
                        parts.append(el.text.strip())
                # set/name
                set_el = root.find("set")
                if set_el is not None:
                    name_el = set_el.find("name")
                    if name_el is not None and name_el.text:
                        parts.append(name_el.text.strip())
                # повторяющиеся поля
                for tag in ("genre", "tag", "studio"):
                    for el in root.findall(tag):
                        if el.text:
                            parts.append(el.text.strip())
                # актёры
                for actor in root.findall("actor"):
                    name = actor.findtext("name") or ""
                    role = actor.findtext("role") or ""
                    if name:
                        parts.append(name.strip())
                    if role:
                        parts.append(role.strip())
            except Exception:
                pass
        return " ".join(parts)

    def _format_time(self, ms: int) -> str:
        """Форматирует миллисекунды в MM:SS или HH:MM:SS."""
        if ms < 0:
            ms = 0
        seconds = ms // 1000
        minutes = seconds // 60
        hours = minutes // 60
        seconds %= 60
        minutes %= 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _update_time_display(self, position: int):
        """Обновляет отображение текущей позиции."""
        current = self._format_time(position)
        total = self._format_time(self._video_duration)
        self.lbl_time.setText(f"{current} / {total}")
        if not self._slider_pressed:
            self.video_slider.setValue(position)

    def _update_duration(self, duration: int):
        self._video_duration = duration
        self.video_slider.setRange(0, duration)
        self.video_slider.setEnabled(duration > 0)
        self._update_time_display(self.media_player.position())

    def _on_slider_pressed(self):
        self._slider_pressed = True

    def _on_slider_released(self):
        self._slider_pressed = False
        # финальная перемотка на отпущенную позицию
        # self.media_player.setPosition(self.video_slider.value())

    def _on_slider_moved(self, position: int):
        # обновляем label времени и перематываем видео
        self._update_time_display(position)
        self.media_player.setPosition(position)

    def eventFilter(self, obj, event):

        if obj == self.video_preview and event.type() == event.Type.MouseButtonPress:
            # клик по превью — запускаем воспроизведение
            self.video_preview.hide()
            self.video_widget.show()
            self.video_widget.setFocus()
            self._toggle_play()
            return True

        if obj == self.video_widget:
            if event.type() == event.Type.KeyPress:
                key = event.key()
                pos = self.media_player.position()
                duration = self.media_player.duration()
                new_pos = pos

                if key == Qt.Key.Key_Left:
                    new_pos = max(0, pos - 10_000)
                elif key == Qt.Key.Key_Right:
                    new_pos = pos + 10_000
                    if duration > 0:
                        new_pos = min(duration, new_pos)
                elif key == Qt.Key.Key_Up:
                    new_pos = pos + 60_000
                    if duration > 0:
                        new_pos = min(duration, new_pos)
                elif key == Qt.Key.Key_Down:
                    new_pos = max(0, pos - 60_000)
                elif key == Qt.Key.Key_Space:
                    self._toggle_play()
                    return True
                elif key == Qt.Key.Key_Escape:
                    self._stop_video()
                    return True
                else:
                    return super().eventFilter(obj, event)

                self.media_player.setPosition(new_pos)
                return True

            if event.type() == event.Type.MouseButtonPress:
                # клик по видео — ставим/снимаем с паузы
                self._toggle_play()
                return True
        if obj == self.lbl_volume and event.type() == event.Type.MouseButtonPress:
            self._toggle_mute()
            return True

        return super().eventFilter(obj, event)

    def _toggle_mute(self):
        """Переключает mute/unmute."""
        if self._is_muted:
            # снимаем mute — возвращаем предыдущую громкость
            self.volume_slider.setValue(self._previous_volume)
            self.lbl_volume.setText("🔊")
            self._is_muted = False
        else:
            # включаем mute — сохраняем текущую громкость и ставим 0
            self._previous_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
            self.lbl_volume.setText("🔇")
            self._is_muted = True

    def _extract_preview_frame(self, mp4_path: Path):
        """Запускает асинхронное извлечение кадра."""
        mp4_str = str(mp4_path)
        self._current_preview_path = mp4_str

        # отменяем старые воркеры
        for worker in self._preview_workers:
            if worker.isRunning():
                worker.requestInterruption()

        # очищаем старое превью сразу
        self.video_preview.clear()
        self.video_preview.show()
        self.video_widget.hide()

        worker = PreviewWorker(mp4_path, self)
        worker.finished.connect(self._on_preview_ready)
        worker.failed.connect(self._on_preview_failed)
        # удаляем воркер только после завершения
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.failed.connect(lambda: self._remove_worker(worker))
        self._preview_workers.append(worker)
        worker.start()

    def _remove_worker(self, worker: PreviewWorker):
        """Удаляет завершённый воркер из списка."""
        if worker in self._preview_workers:
            self._preview_workers.remove(worker)
        worker.deleteLater()

    def _cleanup_workers(self):
        self._preview_workers = [w for w in self._preview_workers if w.isRunning()]

    def _on_preview_ready(self, video_path: str, tmp_path: str):
        """Вызывается в главном потоке, когда кадр готов."""
        # игнорируем, если уже загружено другое видео
        if video_path != self._current_preview_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return
        pixmap = QPixmap(tmp_path)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        if pixmap.isNull():
            return
        self.video_preview.setPixmap(pixmap)
        self.video_preview.show()
        self.video_widget.hide()

    def _on_preview_failed(self, video_path: str):
        if video_path != self._current_preview_path:
            return
        self.video_preview.clear()
        self.video_preview.setText("Нет превью")
        self.video_preview.show()
        self.video_widget.hide()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("NFO Editor")
    app.setOrganizationName("nfo_editor")
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    win = NfoEditorWindow(initial)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

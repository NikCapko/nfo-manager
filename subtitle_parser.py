class SubtitleParser:
    """Парсер SRT-файлов."""

    @staticmethod
    def parse(path: Path) -> list[tuple[int, int, str]]:
        """Возвращает список (start_ms, end_ms, text)."""
        if not path.exists():
            return []
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        # нормализуем переносы строк
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        blocks = content.strip().split("\n\n")

        subtitles = []
        for block in blocks:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if len(lines) < 2:
                continue
            # ищем строку с таймкодами
            time_line_idx = -1
            for i, line in enumerate(lines):
                if "-->" in line:
                    time_line_idx = i
                    break
            if time_line_idx < 0 or time_line_idx + 1 >= len(lines):
                continue

            time_parts = lines[time_line_idx].split("-->")
            if len(time_parts) != 2:
                continue
            start = SubtitleParser._parse_time(time_parts[0].strip())
            end = SubtitleParser._parse_time(time_parts[1].strip())
            text = "<br>".join(lines[time_line_idx + 1 :])
            if start is not None and end is not None:
                subtitles.append((start, end, text))

        subtitles.sort(key=lambda x: x[0])
        return subtitles

    @staticmethod
    def _parse_time(s: str) -> Optional[int]:
        """Парсит '00:01:23,456' в миллисекунды."""
        try:
            s = s.replace(",", ".")
            parts = s.split(":")
            if len(parts) != 3:
                return None
            h = int(parts[0])
            m = int(parts[1])
            sec_parts = parts[2].split(".")
            sec = int(sec_parts[0])
            ms = int(sec_parts[1].ljust(3, "0")[:3]) if len(sec_parts) > 1 else 0
            return ((h * 60 + m) * 60 + sec) * 1000 + ms
        except Exception:
            return None


class AssParser:
    """Парсер ASS/SSA файлов субтитров."""
    @staticmethod
    def parse(path: Path) -> list[tuple[int, int, str]]:
        """Возвращает список (start_ms, end_ms, text)."""
        if not path.exists():
            return []
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        subtitles = []
        in_events = False

        for line in content.split("\n"):
            line = line.strip()

            # ищем секцию [Events]
            if line.startswith("[Events]"):
                in_events = True
                continue

            # выходим из секции при следующей секции
            if line.startswith("[") and in_events:
                break

            if not in_events:
                continue

            # парсим Dialogue строки
            if line.startswith("Dialogue:"):
                parts = line[9:].split(",", 9)  # максимум 10 частей
                if len(parts) < 10:
                    continue

                start = AssParser._parse_time(parts[1].strip())
                end = AssParser._parse_time(parts[2].strip())
                text = parts[9].strip()

                # очищаем ASS теги форматирования
                text = AssParser._clean_ass_text(text)

                if start is not None and end is not None and text:
                    subtitles.append((start, end, text))

        subtitles.sort(key=lambda x: x[0])
        return subtitles

    @staticmethod
    def _parse_time(s: str) -> Optional[int]:
        """Парсит '0:01:23.45' в миллисекунды."""
        try:
            parts = s.split(":")
            if len(parts) != 3:
                return None
            h = int(parts[0])
            m = int(parts[1])
            sec_parts = parts[2].split(".")
            sec = int(sec_parts[0])
            cs = int(sec_parts[1].ljust(2, "0")[:2]) if len(sec_parts) > 1 else 0
            # cs = centiseconds (сотые), конвертируем в миллисекунды
            ms = cs * 10
            return ((h * 60 + m) * 60 + sec) * 1000 + ms
        except Exception:
            return None

    @staticmethod
    def _clean_ass_text(text: str) -> str:
        """Удаляет ASS теги форматирования."""
        import re
        # удаляем теги в фигурных скобках: {\b1}, {\an8}, и т.д.
        text = re.sub(r"\{[^}]*\}", "", text)
        # заменяем \N на перенос строки
        text = text.replace("\\N", "<br>")
        # заменяем \n на перенос строки
        text = text.replace("\\n", "<br>")
        # удаляем остальные escape-последовательности
        text = re.sub(r"\\[a-zA-Z]", "", text)
        return text.strip()

"""每日分类日志文件：人类可读文本行 + 归档压缩。"""

import heapq
import lzma
import os
import shutil
import tarfile
import threading
from datetime import date, datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Iterator, Optional

# 动作 -> 每日日志文件名
CATEGORY_FILES = {
    "break": "break.log",
    "place": "place.log",
    "explode": "explosion.log",
    "container_open": "container.log",
    "click": "click.log",
    "leaves_decay": "world.log",
    "block_grow": "world.log",
    "block_form": "world.log",
    "liquid_flow": "world.log",
    "piston": "world.log",
    "block_cook": "world.log",
    "weather": "world.log",
    "thunder": "world.log",
    "plugin_enable": "world.log",
    "plugin_disable": "world.log",
    "chat": "chat.log",
    "command": "command.log",
    "broadcast": "chat.log",
    "join": "session.log",
    "quit": "session.log",
    "kick": "session.log",
    "kill": "kill.log",
    "entity_kill": "kill.log",
    "item_drop": "item.log",
    "item_pickup": "item.log",
    "item_consume": "item.log",
    "gamemode": "player.log",
    "teleport": "player.log",
    "bed_enter": "player.log",
    "bed_leave": "player.log",
    "dimension_change": "player.log",
    "respawn": "player.log",
    "emote": "player.log",
    "entity_interact": "player.log",
    "rollback": "rollback.log",
    "undo": "rollback.log",
}

_STRATEGY_EXT = {"gzip": "gz", "bz2": "bz2", "xz": "xz"}

# 玩家名 -> 目录名的非法字符（跨平台路径安全）
_UNSAFE_CHARS = '\\/:*?"<>|'


def _safe_dir_name(name: str) -> str:
    safe = "".join("_" if c in _UNSAFE_CHARS else c for c in name).strip()
    return safe or "unknown"


class DailyLog:
    """每日日志文件与压缩归档管理。

    目录结构（位于插件数据目录下）：
        logs/YYYY-MM-DD/break.log                 全局：非玩家来源
        logs/YYYY-MM-DD/players/Steve/break.log   玩家操作独立分层
        archives/YYYY-MM-DD.tar.gz                已压缩的历史日志

    玩家分层由调用方判定归属并传入 actor（None 写全局文件）。
    """

    def __init__(self, data_folder: str):
        self.base = Path(data_folder) / "logs"
        self.archive_dir = Path(data_folder) / "archives"
        self.base.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        # 内存缓冲：{(日期, 分类, 归属玩家|None): [行, ...]}
        self._buffers: dict[tuple[str, str, Optional[str]], list[str]] = {}
        self._last_compress_date: Optional[str] = None
        # 主线程与后台写线程共用一把锁，防止文件写入交错
        self._io_lock = threading.Lock()

    def write(self, category: str, line: str, actor: Optional[str] = None) -> None:
        with self._io_lock:
            self._buffers.setdefault(
                (self._today(), category, actor), []
            ).append(line)

    def flush(self) -> None:
        """把缓冲写入日志文件（线程安全，全程持锁防交错）。"""
        with self._io_lock:
            if not self._buffers:
                return
            pending = self._buffers
            self._buffers = {}
            for (day, category, actor), lines in pending.items():
                if not lines:
                    continue
                day_dir = self.base / day
                if actor:
                    day_dir = day_dir / "players" / _safe_dir_name(actor)
                try:
                    day_dir.mkdir(parents=True, exist_ok=True)
                    path = day_dir / CATEGORY_FILES.get(category, f"{category}.log")
                    with path.open("a", encoding="utf-8") as f:
                        f.write("\n".join(lines) + "\n")
                except OSError:
                    continue  # 单文件失败不影响其余分类

    def _day_files(self, day: str, categories: Optional[list[str]],
                   actor: Optional[str]) -> Iterator[Path]:
        """迭代该归属下要读取的日志文件路径（存在性过滤，已去重）。"""
        day_dir = self.base / day
        if actor:
            day_dir = day_dir / "players" / _safe_dir_name(actor)
        if not day_dir.is_dir():
            return
        wanted = categories or sorted(set(CATEGORY_FILES.values()))
        seen: set[str] = set()
        for file_name in wanted:
            if file_name in seen:
                continue
            seen.add(file_name)
            path = day_dir / file_name
            if path.is_file():
                yield path

    @staticmethod
    def _iter_lines(path: Path) -> Iterator[str]:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    s = line.rstrip("\n")
                    if s.strip():
                        yield s
        except OSError:
            return

    def count_day(self, day: str, categories: Optional[list[str]] = None,
                  actor: Optional[str] = None) -> int:
        """统计某天日志总行数（按块换行计数，O(1) 内存）。"""
        total = 0
        for path in self._day_files(day, categories, actor):
            try:
                with path.open("rb") as f:
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        total += chunk.count(b"\n")
            except OSError:
                continue
        return total

    def read_day_page(self, day: str, categories: Optional[list[str]] = None,
                      actor: Optional[str] = None,
                      offset: int = 0, limit: int = 10) -> list[str]:
        """流式读取某天日志的一页（时间正序，多文件惰性归并，O(limit) 内存）。"""
        if limit <= 0:
            return []
        paths = list(self._day_files(day, categories, actor))
        if not paths:
            return []
        # 行首 [HH:MM:SS] 的字符串序即时间序
        merged = heapq.merge(*(self._iter_lines(p) for p in paths))
        return list(islice(merged, max(0, offset), max(0, offset) + limit))

    def list_players(self, day: str) -> list[str]:
        pdir = self.base / day / "players"
        if not pdir.is_dir():
            return []
        try:
            return sorted(p.name for p in pdir.iterdir() if p.is_dir())
        except OSError:
            return []

    def list_days(self) -> list[str]:
        """所有可浏览的日志日期（倒序；已归档的需解压后才能浏览）。"""
        days: list[str] = []
        try:
            for p in self.base.iterdir():
                if not p.is_dir():
                    continue
                try:
                    datetime.strptime(p.name, "%Y-%m-%d")
                except ValueError:
                    continue
                days.append(p.name)
        except OSError:
            return days
        return sorted(days, reverse=True)

    def compress_old(self, strategy: str = "auto", auto_gzip_days: int = 7,
                     keep_archives_days: int = 0,
                     force: bool = False) -> list[dict]:
        """把今天之前的日志目录压缩归档。

        strategy: gzip / bz2 / xz / auto（auto = 近期 gzip、更早 xz）。
        """
        results: list[dict] = []
        today = date.today()
        for name in sorted(os.listdir(self.base)):
            day_dir = self.base / name
            if not day_dir.is_dir():
                continue
            try:
                day = date.fromisoformat(name)
            except ValueError:
                continue
            if day >= today:
                continue  # 只压缩今天之前的

            actual = strategy
            if actual == "auto":
                actual = "gzip" if (today - day).days <= auto_gzip_days else "xz"
            if actual not in ("gzip", "bz2", "xz"):
                actual = "gzip"

            archive_path = (
                self.archive_dir / f"{name}.tar.{_STRATEGY_EXT[actual]}"
            )
            if archive_path.exists() and not force:
                shutil.rmtree(day_dir, ignore_errors=True)
                continue

            tmp_path = archive_path.with_name(archive_path.name + ".tmp")
            try:
                self.archive_dir.mkdir(parents=True, exist_ok=True)
                if actual == "xz":
                    # 极限压缩：lzma preset 9 | EXTREME
                    with lzma.LZMAFile(
                        str(tmp_path), mode="wb",
                        preset=9 | lzma.PRESET_EXTREME,
                    ) as xz_file:
                        with tarfile.open(fileobj=xz_file, mode="w") as tar:
                            tar.add(str(day_dir), arcname=name)
                else:
                    mode = "w:gz" if actual == "gzip" else "w:bz2"
                    with tarfile.open(str(tmp_path), mode, compresslevel=9) as tar:
                        tar.add(str(day_dir), arcname=name)
                tmp_path.replace(archive_path)
                shutil.rmtree(day_dir, ignore_errors=True)
                results.append({
                    "day": name,
                    "strategy": actual,
                    "size": archive_path.stat().st_size,
                })
            except OSError:
                # 压缩失败则保留原目录，下次再试
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue

        # 按保留天数清理旧压缩包
        if keep_archives_days > 0:
            cutoff = today - timedelta(days=keep_archives_days)
            for path in self.archive_dir.glob("*.tar.*"):
                try:
                    day = date.fromisoformat(path.name.split(".")[0])
                    if day < cutoff:
                        path.unlink()
                except (ValueError, OSError):
                    continue
        return results

    def maybe_auto_compress(self, hour: int, strategy: str,
                            auto_gzip_days: int, keep_archives_days: int
                            ) -> Optional[tuple[str, int, int]]:
        """每天指定小时触发一次压缩检查（只做时间门控，压缩由后台执行）。"""
        now = datetime.now()
        today_str = now.date().isoformat()
        if self._last_compress_date == today_str:
            return None
        if now.hour != hour:
            return None
        self._last_compress_date = today_str
        return (strategy, auto_gzip_days, keep_archives_days)

    def stats(self) -> dict:
        try:
            dirs = [p for p in self.base.iterdir() if p.is_dir()]
            archives = list(self.archive_dir.glob("*.tar.*"))
            logs_bytes = sum(
                f.stat().st_size
                for d in dirs for f in d.rglob("*") if f.is_file()
            )
            archives_bytes = sum(a.stat().st_size for a in archives)
        except OSError:
            dirs, archives, logs_bytes, archives_bytes = [], [], 0, 0
        return {
            "pending_days": len(dirs),
            "archives": len(archives),
            "archives_bytes": archives_bytes,
            "logs_bytes": logs_bytes,
        }

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

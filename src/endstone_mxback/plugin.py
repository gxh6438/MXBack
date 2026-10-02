"""MxBack 主插件类：命令分发、权限门控、任务调度与模块装配。

性能设计：方块/事件日志先进内存缓冲，由定时任务批量落盘；
开启 performance.async_flush 后数据库写入与日志文件 IO 全部移交
后台线程，主线程只做入队。大区域回档由回档引擎分批执行。
"""

import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from endstone import ColorFormat, Player
from endstone.command import Command, CommandSender
from endstone.plugin import Plugin, PluginLoadOrder

from .config import ConfigManager
from .daily_log import DailyLog
from .database import Database, compress_archive
from .forms import Forms
from .i18n import Lang
from .listeners import Listeners
from .permissions import PermissionManager
from .rollback import RollbackEngine
from .selection import SelectionManager

HELP_TEXT = """§e【 MxBack 方块日志与回档 】
§f/mxback §7- 打开主菜单（全部功能）
§f/mxback start §7- 开始选区模式（选区工具生效）
§f/mxback stop §7- 停止选区模式（工具点击失效）
§f/mxback menu §7- 打开当前选区的操作选择（回档/查看日志）
§f/mxback undo [编号] §7- 撤销最近一次（或指定一次）回档
§f/mxback history §7- 查看回档记录并撤销任意一次
§f/mxback log §7- 日志中心（日志文件浏览 + 数据库查询）
§f/mxback lookup §7- 日志中心（同上，兼容旧命令）
§f/mxback config §7- 配置文件（所有配置项，热重载）
§f/mxback perm §7- 权限管理（全局默认 + 单玩家设置，OP）
§f/mxback status §7- 运行状态
§f/mxback compress [gzip|bz2|xz|auto] §7- 立即压缩旧日志
§f/mxback purge <天数> §7- 清理数据库中 N 天前的记录
§f/mxback db §7- 数据库管理（新建/归档列表/恢复）
§f/mxback reload §7- 从磁盘重载配置文件
§7选区：手持木斧§f右键§7依次选择第一/第二点；完成后木斧右键=改第一点，
§f木棍右键§7=改第二点，木斧§f左键§7=退出选区模式
§7需先 §f/mxback start §7开启选区模式；完成选区后弹出操作选择表单"""

# 子命令枚举（写入命令 usages，供客户端自动补全）
SUB_COMMANDS = (
    "start|stop|main|menu|help|undo|history|log|lookup|perm|"
    "config|settings|status|compress|purge|db|reload"
)


class MxBackPlugin(Plugin):
    api_version = "0.11"
    prefix = "MxBack"
    load = PluginLoadOrder.STARTUP  # 尽早加载，避免错过开服早期的方块日志

    commands = {
        "mxback": {
            "description": "MxBack 方块日志与区域回档系统",
            "usages": [
                "/mxback",
                f"/mxback ({SUB_COMMANDS})<cmd: Cmd> [arg: str]",
            ],
            "permissions": ["mxback.use"],
        },
    }

    permissions = {
        "mxback.use": {
            "description": "允许使用 /mxback 基础命令（具体功能另有门控）",
            "default": True,
        },
    }

    def on_load(self) -> None:
        self.logger.info("MxBack 正在加载……")

    def _check_runtime(self) -> None:
        """检测 Endstone 版本，标记已知平台崩溃缺陷。

        Endstone #469：<0.11.8 读取物品堆（item_stack）会段错误。
        掉落物清理与指纹采集都读 item_stack，旧版本自动退化为
        "仅按位置+指纹匹配"规避崩服；未知版本按旧版本保守处理。
        """
        ver = ""
        try:
            ver = str(self.server.version)
        except Exception:
            ver = ""
        if not ver:
            try:
                import endstone as _endstone

                ver = str(getattr(_endstone, "__version__", "") or "")
            except Exception:
                ver = ""

        def key(v: str) -> tuple:
            parts = []
            for p in v.strip().split(".")[:3]:
                p = p.split("+")[0].split("-")[0]
                parts.append(int(p) if p.isdigit() else 0)
            return tuple(parts)

        self._endstone_version = ver
        self._item_stack_safe = bool(ver) and key(ver) >= (0, 11, 8)
        if not self._item_stack_safe:
            self.logger.warning(
                f"检测到 Endstone {ver or '(未知版本)'} < 0.11.8："
                "该版本存在已知的物品堆读取段错误缺陷（Endstone #469），"
                "已自动关闭掉落物清理的类型校验（仅按位置+指纹匹配），"
                "建议尽快升级 Endstone 至 0.11.8 以上"
            )

    def on_enable(self) -> None:
        self._check_runtime()
        self.cfg = ConfigManager(self.data_folder)
        self.lang = Lang(self)
        self.permissions = PermissionManager(self.data_folder, self.cfg)
        self.db = Database(self.data_folder)
        # 上次关服若中断了"恢复归档"，清掉残留的解压临时文件
        #（切换本身是原子改名，残留文件不代表数据损坏）
        try:
            stale = Path(self.data_folder) / ".mxback_restore_tmp"
            if stale.exists():
                stale.unlink()
        except OSError:
            pass
        self.daily = DailyLog(self.data_folder)
        self.selection = SelectionManager(self)
        self.rollback = RollbackEngine(self)
        self.forms = Forms(self)
        self.listeners = Listeners(self)
        self.container_ids = frozenset(self.cfg.get("containers", default=[]))

        self._queue: list[dict] = []
        self._event_queue: list[dict] = []
        self._selecting: set[str] = set()
        # 停机标志：on_disable 一进来就置位，所有定时/延迟任务回调据此
        # 立即返回——关服流程中 BDS Level 可能已析构，此时任何
        # server.get_player()/online_players 都会踩悬空引用直接崩溃
        self._stopping: bool = False
        # 本运行期内见过的玩家名（每日日志按玩家分层归属判定用）。
        # 这里绝不能读 server.online_players：STARTUP 加载序的 on_enable
        # 发生在 EndstoneServer::init 阶段，Level 句柄尚未就绪，读取即
        # 段错误且不可捕获；改为首个服务器 tick 再补录快照（/reload 时
        # 在线玩家不再触发 join 事件，靠该快照补录归属）
        self._known_players: set[str] = set()

        # 后台写入线程（数据库 + 日志文件 IO 均在后台执行）
        self._write_q: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._writer_stop = threading.Event()
        self._writer: Optional[threading.Thread] = None
        self._flush_task: Any = None
        # 压缩互斥锁（xz 极限压缩可达分钟级，且防止两个压缩线程同时
        # 写同一个 .tmp 中间文件）
        self._compress_lock = threading.Lock()
        # 后台线程 -> 玩家的待发消息（Endstone API 非线程安全，
        # 由主线程定时任务代发）
        self._pending_notices: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._db_swapping: bool = False
        self._db_swap_lock = threading.Lock()
        if bool(self.cfg.get("performance", "async_flush", default=True)):
            self._writer = threading.Thread(
                target=self._writer_loop, name="mxback-writer", daemon=True
            )
            self._writer.start()
            self.logger.info("后台写入线程已启动（异步落盘，保护 TPS）")

        self.register_events(self.listeners)

        self._start_flush_task()
        self._start_particle_task()
        # 每 20 分钟检查一次每日自动压缩
        self._auto_compress_task = self.server.scheduler.run_task(
            self, self._auto_compress_tick, delay=1200, period=1200
        )
        self._players_task = self.server.scheduler.run_task(
            self, self._snapshot_online_players, delay=1
        )

        # 开服补漏：压缩之前漏掉的历史日志（长期关服等场景）
        try:
            if self.cfg.get("logs", "auto_compress", default=True):
                strategy = self.cfg.get("logs", "strategy", default="auto")
                gzip_days = int(
                    self.cfg.get("logs", "auto_gzip_days", default=7)
                )
                keep_days = int(
                    self.cfg.get("logs", "keep_archives_days", default=0)
                )
                self._start_bg_compress(strategy, gzip_days, keep_days)
        except Exception as e:
            self.logger.warning(f"开服自动压缩启动失败: {e}")

        self.logger.info("MxBack 已启用：方块日志记录与区域回档就绪")

    def on_disable(self) -> None:
        # 1) 立即停止一切定时/延迟任务回调，赶在其余清理逻辑之前
        #    （后续清理只碰 db/文件/队列，绝不碰 server）
        self._stopping = True
        self._cancel_all_tasks()
        try:
            # 2) 通知后台线程收尾并等待退出（它退出前会处理完已入队数据）
            if self._writer is not None and self._writer.is_alive():
                self._writer_stop.set()
                self._writer.join(timeout=15)
            # 3) 剩余内存缓冲同步写库
            blocks, events = self._drain_buffers()
            self._write_now(blocks, events, True)
            # 4) 后台线程可能遗留未消费的队列项：同步补写
            rest_b: list[dict] = []
            rest_e: list[dict] = []
            rest_daily = False
            while True:
                try:
                    kind, payload = self._write_q.get_nowait()
                except queue.Empty:
                    break
                if kind == "block":
                    rest_b.append(payload)
                elif kind == "event":
                    rest_e.append(payload)
                elif kind == "daily":
                    rest_daily = True
                elif kind == "barrier":
                    try:
                        payload.set()
                    except Exception:
                        pass
                else:
                    self._apply_db_write(kind, payload)
            self._write_now(rest_b, rest_e, rest_daily)
            self.db.close()
        except Exception as e:
            # 关服落盘失败必须留下线索（静默会丢失最后几秒的日志数据）
            try:
                self.logger.error(f"卸载时落盘失败: {e}")
            except Exception:
                pass
        self.logger.info("MxBack 已卸载")

    # 日志记录入口（监听器调用；只在主线程做内存入队，落盘交给定时/后台）
    def note_player(self, name: str) -> None:
        self._known_players.add(name)

    def _snapshot_online_players(self) -> None:
        """一次性任务（on_enable 后 1 tick）：补录在线玩家名快照。"""
        if self._stopping:
            return
        try:
            self._known_players.update(
                p.name for p in self.server.online_players
            )
        except Exception:
            pass

    # 已知的非玩家日志来源（归全局分类文件，不建玩家目录）
    _NON_PLAYER_ACTORS = ("自然", "活塞", "控制台", "服务器", "未知")

    def _log_actor(self, actor: Optional[str]) -> Optional[str]:
        """每日日志行的归属：玩家 -> 玩家名目录；否则 -> 全局。"""
        if not bool(self.cfg.get("logs", "per_player_files", default=True)):
            return None
        if not actor:
            return None
        if actor in self._NON_PLAYER_ACTORS or actor.startswith("爆炸("):
            return None
        return actor if actor in self._known_players else None

    def record(self, *, action: str, actor: str, block_type: str,
               block_states: str, x: int, y: int, z: int, dimension: str,
               replaced_type: Optional[str] = None,
               replaced_states: Optional[str] = None,
               daily_label: Optional[str] = None) -> None:
        """方块日志：内存缓冲，定时批量写数据库 + 每日日志文件。

        daily_label：每日日志里动作的显示文案（骨粉催熟/灌水等复合
        场景用），不传则按 action 的默认词条显示。
        """
        self._queue.append({
            "ts": time.time(),
            "actor": actor,
            "action": action,
            "block_type": block_type,
            "block_states": block_states or "{}",
            "replaced_type": replaced_type,
            "replaced_states": replaced_states,
            "x": x, "y": y, "z": z,
            "dimension": dimension,
        })

        if self.cfg.get("logs", "daily_files", default=True):
            now = datetime.now().strftime("%H:%M:%S")
            dim_cn = self.lang.dimension_name(dimension)
            block_cn = self.lang.block_name(block_type)
            if action == "break":
                line = f"[{now}] {actor} 破坏了 {block_cn} 于{dim_cn} ({x}, {y}, {z})"
            elif action == "place":
                replaced_cn = (
                    self.lang.block_name(replaced_type)
                    if replaced_type else "空气"
                )
                line = (
                    f"[{now}] {actor} 放置了 {block_cn}（原为 {replaced_cn}）"
                    f" 于{dim_cn} ({x}, {y}, {z})"
                )
            elif action == "explode":
                line = f"[{now}] {actor} 摧毁了 {block_cn} 于{dim_cn} ({x}, {y}, {z})"
            elif action == "container_open":
                line = f"[{now}] {actor} 打开了 {block_cn} 于{dim_cn} ({x}, {y}, {z})"
            else:
                action_cn = daily_label or self.lang.action_name(action)
                line = (
                    f"[{now}] {actor} {action_cn} {block_cn}"
                    f" 于{dim_cn} ({x}, {y}, {z})"
                )
            self.daily.write(action, line, actor=self._log_actor(actor))

    def record_event(self, *, action: str, actor: str, detail: str = "",
                    x: int = 0, y: int = 0, z: int = 0,
                    dimension: str = "-",
                    daily: bool = True) -> None:
        """玩家行为/世界事件日志：另一张表，同样走内存缓冲批量落盘。

        无坐标语义的事件（天气/广播/控制台命令）用默认 dimension="-"，
        每日日志行中省略坐标后缀。daily=False 不写每日日志文件（内部
        结构化数据用，如掉落物指纹快照）。
        """
        self._event_queue.append({
            "ts": time.time(),
            "actor": actor,
            "action": action,
            "detail": detail or "",
            "x": x, "y": y, "z": z,
            "dimension": dimension,
        })

        if daily and self.cfg.get("logs", "daily_files", default=True):
            now = datetime.now().strftime("%H:%M:%S")
            action_cn = self.lang.action_name(action)
            line = f"[{now}] {actor} {action_cn}"
            if detail:
                line += f"：{detail}"
            if dimension != "-":
                dim_cn = self.lang.dimension_name(dimension)
                line += f" 于{dim_cn} ({x}, {y}, {z})"
            self.daily.write(action, line, actor=self._log_actor(actor))

    def write_daily(self, action: str, line: str,
                    actor: Optional[str] = None) -> None:
        """供回档引擎等模块直接写每日日志行（尊重 daily_files 开关）。"""
        if self.cfg.get("logs", "daily_files", default=True):
            self.daily.write(
                action, line,
                actor=self._log_actor(actor) if actor else None,
            )

    # 缓冲落盘（定时任务 + 可选后台线程）
    def _start_flush_task(self) -> None:
        """（重新）启动批量落盘定时任务，间隔取 flush_interval_ticks。"""
        old = getattr(self, "_flush_task", None)
        if old is not None:
            try:
                old.cancel()
            except Exception:
                pass
            self._flush_task = None
        interval = max(
            1, int(self.cfg.get("performance", "flush_interval_ticks", default=100))
        )
        self._flush_task = self.server.scheduler.run_task(
            self, self._flush, delay=interval, period=interval
        )

    def _drain_buffers(self) -> tuple[list[dict], list[dict]]:
        blocks = self._queue
        self._queue = []
        events = self._event_queue
        self._event_queue = []
        return blocks, events

    def _cancel_all_tasks(self) -> None:
        """取消本插件注册的全部定时任务。

        Endstone 在 disablePlugin 时也会 cancelTasks，但那发生在
        on_disable 返回之后；关服流程中 BDS Level 可能先于插件 disable
        析构，窗口期内周期任务一旦调用 server.get_player() 即崩溃，
        必须主动提前取消。
        """
        for name in (
            "_flush_task", "_particle_task", "_auto_compress_task",
            "_players_task",
        ):
            task = getattr(self, name, None)
            if task is None:
                continue
            try:
                task.cancel()
            except Exception:
                pass
            setattr(self, name, None)

    def _flush(self) -> None:
        """定时任务：把内存缓冲交给后台写入线程（或直接同步写库）。"""
        if self._stopping:
            return
        self._deliver_notices()
        blocks, events = self._drain_buffers()
        if self._writer is not None:
            for rec in blocks:
                self._write_q.put(("block", rec))
            for rec in events:
                self._write_q.put(("event", rec))
            self._write_q.put(("daily", None))
        else:
            self._write_now(blocks, events, flush_daily=True)

    def _post_notice(self, player_name: str, message: str) -> None:
        """后台线程投递给玩家的消息（由 _flush 在主线程代发）。"""
        self._pending_notices.put((player_name, message))

    def _deliver_notices(self) -> None:
        if self._stopping:
            return
        while True:
            try:
                name, msg = self._pending_notices.get_nowait()
            except queue.Empty:
                return
            try:
                p = self.server.get_player(name)
                if p is not None:
                    p.send_message(
                        f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} {msg}"
                    )
            except Exception:
                pass

    def _write_now(self, blocks: list[dict], events: list[dict],
                   flush_daily: bool) -> None:
        """真正写数据库 + 落盘日志文件（可能由后台线程调用）。"""
        try:
            if blocks:
                self.db.insert_records(blocks)
            if events:
                self.db.insert_event_records(events)
            if flush_daily:
                self.daily.flush()
        except Exception as e:
            self.logger.error(f"日志落盘失败: {e}")

    def _writer_is_running(self) -> bool:
        return self._writer is not None and self._writer.is_alive()

    def _writer_loop(self) -> None:
        """后台写入线程：批量消费写队列，主线程零 IO。

        队列项：("block", rec) / ("event", rec) 批量写库；
        ("daily", None) 落盘日志文件；("barrier", Event) FIFO 屏障
        （wait_db_flush 用）；其余为回档增量（session_logs / undo_rows
        / finalize_*），必须保持 FIFO——批次一定先于对应 finalize。
        """
        while True:
            try:
                item = self._write_q.get(timeout=0.5)
            except queue.Empty:
                if self._writer_stop.is_set():
                    return
                continue
            # 尽量把当前积压一次性取完，合并为更少的事务
            batch = [item]
            while True:
                try:
                    batch.append(self._write_q.get_nowait())
                except queue.Empty:
                    break
            blocks: list[dict] = []
            events: list[dict] = []
            db_ops: list[tuple[str, Any]] = []
            barriers: list[threading.Event] = []
            flush_daily = False
            for kind, payload in batch:
                if kind == "block":
                    blocks.append(payload)
                elif kind == "event":
                    events.append(payload)
                elif kind == "daily":
                    flush_daily = True
                elif kind == "barrier":
                    barriers.append(payload)
                else:
                    db_ops.append((kind, payload))
            self._write_now(blocks, events, flush_daily)
            for kind, payload in db_ops:
                try:
                    self._apply_db_write(kind, payload)
                except Exception as e:
                    self.logger.error(f"回档增量落库失败({kind}): {e}")
            # 屏障最后放行：等待方据此确认先于屏障的任务已全部完成
            for ev in barriers:
                try:
                    ev.set()
                except Exception:
                    pass

    # 回档增量落库（回档引擎 -> 后台队列）
    def submit_db(self, kind: str, payload: Any) -> None:
        """把回档相关数据库写任务排入后台写队列（FIFO）。

        kind: session_logs (session_id, log_ids)
              undo_rows     [(session_id, x, y, z, dim, type, states), ...]
              finalize_session (session_id, applied)
              finalize_undo   session_id
        同步模式（async_flush=false 无后台线程）时立即执行。
        """
        if self._stopping:
            return
        if self._writer is None:
            try:
                self._apply_db_write(kind, payload)
            except Exception as e:
                self.logger.error(f"回档增量落库失败({kind}): {e}")
            return
        self._write_q.put((kind, payload))

    def wait_db_flush(self, timeout: float = 10.0) -> bool:
        """阻塞等待写队列中已入队任务全部落库（FIFO 屏障）。

        回档/撤销启动前调用：排空上一会话的收尾写，避免新会话读到
        未落库的 rolled_back 标记 / undo_log 快照。同步模式恒 True；
        超时返回 False 由调用方放弃本次操作。
        """
        writer = self._writer
        if writer is None:
            return True
        if not writer.is_alive():
            return self._write_q.empty()
        ev = threading.Event()
        self._write_q.put(("barrier", ev))
        return ev.wait(timeout)

    def _apply_db_write(self, kind: str, payload: Any) -> None:
        if kind == "session_logs":
            session_id, log_ids = payload
            self.db.insert_session_logs(session_id, log_ids)
        elif kind == "undo_rows":
            self.db.insert_undo_rows(payload)
        elif kind == "finalize_session":
            session_id, applied = payload
            self.db.finalize_session(session_id, applied)
        elif kind == "finalize_undo":
            self.db.finalize_undo(payload)

    # 数据库轮换（/mxback db）
    def db_new(self) -> dict:
        """归档当前数据库并从空库开始（主线程执行，毫秒级完成）。"""
        with self._db_swap_lock:
            if self._db_swapping:
                return {"error": "数据库切换正在进行，请稍候"}
            self._db_swapping = True
            try:
                if self.rollback.is_busy():
                    return {
                        "error": "有回档/撤销正在进行，"
                                 "请等它结束再新建数据库"
                    }
                if not self.wait_db_flush(10.0):
                    return {
                        "error": "写队列排空超时，为保数据安全已取消本次操作"
                    }
                path, info = self.db.archive_current()
            except Exception as e:
                self.logger.error(f"新建数据库失败: {e}")
                return {"error": f"新建失败：{e}"}
            finally:
                self._db_swapping = False
        # 归档压缩移到后台线程（大库可达数秒，不卡主线程）
        if bool(self.cfg.get("database", "archive_compress", default=True)):
            algo = str(
                self.cfg.get("database", "archive_algorithm", default="gzip")
            )
            threading.Thread(
                target=self._compress_db_archive,
                args=(path, algo),
                daemon=True,
                name="mxback-db-compress",
            ).start()
        return {"archive": path.name, "info": info}

    def _compress_db_archive(self, path: Path, algo: str) -> None:
        try:
            final = compress_archive(path, algo)
            self.db.update_sidecar(
                final.name[: final.name.rfind(".db")],
                {"compressed": algo, "compressed_size": final.stat().st_size},
            )
            self.logger.info(f"归档库已压缩: {final.name}")
        except Exception as e:
            # 压缩失败不影响功能：归档保持未压缩形态
            self.logger.warning(f"归档库压缩失败（保留未压缩文件）: {e}")

    def db_restore(self, actor: str, key: str) -> dict:
        """把归档库恢复为现行库（后台执行，完成后 _post_notice 通知）。

        key 为归档文件名或列表序号。当前库会先转归档，数据不丢。
        """
        try:
            entry = self.db.find_archive(key)
        except Exception as e:
            return {"error": f"读取归档列表失败：{e}"}
        if entry is None:
            return {"error": f"找不到归档 {key}（用 /mxback db list 查看）"}
        with self._db_swap_lock:
            if self._db_swapping:
                return {"error": "数据库切换正在进行，请稍候"}
            self._db_swapping = True
        try:
            threading.Thread(
                target=self._db_restore_bg,
                args=(actor, entry),
                daemon=True,
                name="mxback-db-restore",
            ).start()
        except Exception:
            self._db_swapping = False
            raise
        return {"started": True, "name": entry["name"]}

    def _db_restore_bg(self, actor: str, entry: dict) -> None:
        """后台线程：解压归档 -> 秒级切换库文件 -> 重开连接。"""
        tmp: Optional[Path] = None
        try:
            if self.rollback.is_busy():
                self._post_notice(actor, "有回档/撤销正在进行，恢复已取消")
                return
            if not self.wait_db_flush(10.0):
                self._post_notice(actor, "写队列排空超时，恢复已取消")
                return
            self._post_notice(actor, "正在准备归档数据……")
            tmp = self.db.prepare_restore(entry)
            self.db.commit_restore(tmp, entry)
            tmp = None  # 已被 rename 消费，避免误清理
            self._post_notice(
                actor,
                f"数据库已切换为归档 {entry['name']}，"
                f"可继续回档/查询其中的记录",
            )
        except Exception as e:
            self.logger.error(f"恢复归档失败: {e}")
            self._post_notice(actor, f"恢复失败：{e}")
            # 善后：不留孤儿临时文件；未压缩归档物归原主
            if tmp is not None and tmp.exists():
                try:
                    if entry["compressed"]:
                        tmp.unlink()
                    else:
                        tmp.rename(self.db.archive_dir / entry["name"])
                except OSError:
                    pass
        finally:
            self._db_swapping = False

    # 选区模式
    def is_selecting(self, name: str) -> bool:
        return name in self._selecting

    def selection_on(self, name: str) -> None:
        self._selecting.add(name)

    def selection_off(self, name: str) -> None:
        """停止选区模式：工具点击失效，并清除选区与粒子边框。"""
        self._selecting.discard(name)
        self.selection.clear(name)

    # 粒子渲染
    def _start_particle_task(self) -> None:
        # 先取消旧任务，避免 /mxback reload 后叠加重复渲染任务
        old = getattr(self, "_particle_task", None)
        if old is not None:
            try:
                old.cancel()
            except Exception:
                pass
            self._particle_task = None
        cfg = self.cfg
        if not cfg.get("particles", "enabled", default=True):
            return
        interval = int(cfg.get("particles", "interval_ticks", default=10))
        self._particle_task = self.server.scheduler.run_task(
            self, self._render_tick, delay=interval, period=interval
        )

    def _render_tick(self) -> None:
        if self._stopping:
            return
        try:
            self.selection.render_all()
        except Exception as e:
            self.logger.warning(f"粒子渲染失败: {e}")

    def render_selection_once(self, player_name: str) -> None:
        """选完两个点后立即渲染一次边框。"""
        try:
            if self.cfg.get("particles", "enabled", default=True):
                self.selection.render_all()
        except Exception:
            pass

    # 每日自动压缩（主线程只做时间门控，压缩在后台线程执行）
    def _auto_compress_tick(self) -> None:
        if self._stopping:
            return
        try:
            if not self.cfg.get("logs", "auto_compress", default=True):
                return
            hour = int(self.cfg.get("logs", "compress_hour", default=4))
            strategy = self.cfg.get("logs", "strategy", default="auto")
            gzip_days = int(self.cfg.get("logs", "auto_gzip_days", default=7))
            keep_days = int(
                self.cfg.get("logs", "keep_archives_days", default=0)
            )
            due = self.daily.maybe_auto_compress(
                hour, strategy, gzip_days, keep_days
            )
            if due:
                self._start_bg_compress(*due)
        except Exception as e:
            self.logger.warning(f"每日自动压缩检查失败: {e}")

    def _start_bg_compress(self, strategy: str, gzip_days: int,
                           keep_days: int,
                           notify_name: Optional[str] = None) -> bool:
        """在后台线程压缩历史日志；已有压缩任务时返回 False。"""
        if not self._compress_lock.acquire(blocking=False):
            if notify_name:
                self._post_notice(notify_name, "已有压缩任务正在进行，请稍候")
            return False

        def run() -> None:
            try:
                done = self.daily.compress_old(strategy, gzip_days, keep_days)
                if not done:
                    if notify_name:
                        self._post_notice(
                            notify_name, "没有需要压缩的历史日志（仅压缩今天之前的）"
                        )
                    return
                names = ", ".join(d["day"] for d in done[:5])
                self.logger.info(
                    f"后台压缩完成：{len(done)} 天日志已归档: {names}"
                )
                if notify_name:
                    total_kb = sum(d["size"] for d in done) // 1024
                    detail = "，".join(
                        f"{d['day']}({d['strategy']})" for d in done[:8]
                    )
                    if len(done) > 8:
                        detail += " …"
                    self._post_notice(
                        notify_name,
                        f"压缩完成：{len(done)} 天日志共 {total_kb} KB\n"
                        f"{ColorFormat.GRAY}{detail}",
                    )
            except Exception as e:
                self.logger.warning(f"后台压缩失败: {e}")
                if notify_name:
                    self._post_notice(notify_name, f"压缩失败: {e}")
            finally:
                self._compress_lock.release()

        threading.Thread(
            target=run, name="mxback-compress", daemon=True
        ).start()
        return True

    # 权限门控
    def _is_op_or_console(self, sender: CommandSender) -> bool:
        if not isinstance(sender, Player):
            return True
        return bool(sender.is_op)

    def _can(self, sender: CommandSender, key: str) -> bool:
        """玩家生效权限：OP/控制台恒真，其余按 单独设置 > 全局默认。"""
        if self._is_op_or_console(sender):
            return True
        return self.permissions.has(sender.name, key)

    def _can_any(self, sender: CommandSender, *keys: str) -> bool:
        """任一权限命中即通过（用于组合入口，如日志中心）。"""
        return any(self._can(sender, k) for k in keys)

    # 命令分发
    def on_command(
        self, sender: CommandSender, command: Command, args: list[str]
    ) -> bool:
        if command.name != "mxback":
            return False

        sub = args[0].lower() if args else ""
        arg = args[1] if len(args) > 1 else None
        player = sender if isinstance(sender, Player) else None

        if sub in ("", "main"):
            if player is None:
                sender.send_message(HELP_TEXT)
                return True
            self.forms.show_main_menu(player)
            return True

        if sub == "help":
            sender.send_message(HELP_TEXT)
            return True

        if sub == "start":
            if player is None:
                sender.send_message("该命令只能由玩家执行")
                return True
            if not self._can(sender, "selection"):
                sender.send_error_message("你没有权限使用选区功能")
                return True
            self.selection_on(player.name)
            wand1 = self.cfg.get("wand_item", default="minecraft:wooden_axe")
            wand2 = self.cfg.get(
                "selection", "wand_item_2", default="minecraft:stick"
            )
            player.play_sound(player.location, "random.orb")
            player.send_toast("MxBack", "选区模式已开启")
            player.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
                f"{ColorFormat.BOLD}选区模式已开启{ColorFormat.RESET}"
            )
            player.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                f"手持 §f{wand1}§r §e右键§r 依次选择第一点、第二点\n"
                f"{ColorFormat.GRAY}选区完成后：§f{wand1}§r右键=改第一点，"
                f"§f{wand2}§r右键=改第二点，§f{wand1}§r左键=退出选区\n"
                f"{ColorFormat.GRAY}完成后弹出操作选择（回档/查看选区内日志）；"
                f"输入 /mxback stop 停止选区"
            )
            return True

        if sub == "stop":
            if player is None:
                sender.send_message("该命令只能由玩家执行")
                return True
            if not self._can(sender, "selection"):
                sender.send_error_message("你没有权限使用选区功能")
                return True
            was = self.is_selecting(player.name)
            self.selection_off(player.name)
            if was:
                player.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.RED} "
                    f"{ColorFormat.BOLD}选区模式已停止{ColorFormat.RESET}"
                    f"{ColorFormat.WHITE}：工具点击不再生效，选区与边框已清除"
                )
            else:
                player.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                    f"当前并未处于选区模式"
                )
            return True

        if sub == "undo":
            if not self._can(sender, "undo") and not self._can(sender, "undo_others"):
                sender.send_error_message("你没有权限使用撤销功能")
                return True
            session_id: Optional[int] = None
            if arg:
                try:
                    session_id = int(arg)
                except ValueError:
                    sender.send_error_message("回档编号必须为整数（见 /mxback history）")
                    return True
            stats = self.rollback.undo(
                sender.name,
                any_player=(player is None),
                session_id=session_id,
                # OP/控制台/被授权者可撤销任意会话；其余仅限自己的
                allow_any=self._can(sender, "undo_others"),
            )
            if stats is None:
                sender.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                    f"没有可撤销的回档记录"
                )
                return True
            self._report_undo(sender, stats)
            return True

        if sub == "history":
            if player is None:
                sender.send_message("该命令只能由玩家执行（游戏内通过表单查看与撤销）")
                return True
            if not self._can_any(
                sender, "history", "undo", "undo_others"
            ):
                sender.send_error_message("你没有权限查看回档记录")
                return True
            self.forms.show_history(player)
            return True

        if sub == "menu":
            if player is None:
                sender.send_message("该命令只能由玩家执行")
                return True
            if not self._can_any(sender, "rollback", "selection_lookup"):
                sender.send_error_message("你没有权限使用选区操作功能")
                return True
            self.forms.show_selection_menu(player)
            return True

        if sub in ("log", "lookup"):
            if player is None:
                sender.send_message("该命令只能由玩家执行（游戏内通过表单查看）")
                return True
            if not self._can_any(sender, "lookup_files", "lookup_db"):
                sender.send_error_message("你没有权限查看日志")
                return True
            self.forms.show_log_center(player)
            return True

        if sub == "perm":
            if not self._is_op_or_console(sender):
                sender.send_error_message("只有管理员可以管理玩家权限")
                return True
            if player is None:
                sender.send_message(
                    "请在游戏内输入 /mxback perm 打开权限管理界面；"
                    "或直接编辑 config.json（player_permissions）"
                    "与 permissions.json（单玩家设置）"
                )
                return True
            self.forms.show_perm_menu(player)
            return True

        if sub in ("settings", "config"):
            if not self._is_op_or_console(sender):
                sender.send_error_message("只有管理员可以修改配置")
                return True
            if player is None:
                sender.send_message(
                    "请在游戏内使用 /mxback config 打开配置菜单；"
                    "或直接编辑 config.json 后 /mxback reload"
                )
                return True
            self.forms.show_config_menu(player)
            return True

        if sub == "status":
            if not self._can(sender, "status"):
                sender.send_error_message("你没有权限查看运行状态")
                return True
            self._cmd_status(sender)
            return True

        if sub == "compress":
            if not self._is_op_or_console(sender):
                sender.send_error_message("只有管理员可以压缩日志")
                return True
            strategy = (arg or "").lower() or None
            if strategy and strategy not in ("gzip", "bz2", "xz", "auto"):
                sender.send_error_message(
                    f"无效策略 {strategy}，可选：gzip / bz2 / xz / auto"
                )
                return True
            self._cmd_compress(sender, strategy)
            return True

        if sub == "purge":
            if not self._is_op_or_console(sender):
                sender.send_error_message("只有管理员可以清理数据库")
                return True
            if not arg:
                sender.send_error_message("用法：/mxback purge <天数>（清理 N 天前的记录）")
                return True
            try:
                days = int(arg)
            except ValueError:
                sender.send_error_message("天数必须为正整数")
                return True
            if days <= 0:
                sender.send_error_message("天数必须为正整数")
                return True
            result = self.db.purge(days)
            sender.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                f"已清理 {result['logs']} 条方块日志、"
                f"{result['events']} 条事件日志、"
                f"{result['sessions']} 个回档会话（{days} 天前）"
            )
            return True

        if sub == "db":
            if not self._is_op_or_console(sender):
                sender.send_error_message("只有管理员可以管理数据库")
                return True
            db_sub = (arg or "").lower()
            if db_sub in ("", "menu"):
                if player is None:
                    self._cmd_db_status(sender)
                else:
                    self.forms.show_db_menu(player)
                return True
            if db_sub == "new":
                # 玩家走表单二次确认，控制台直接执行
                if player is not None:
                    self.forms.show_db_new_confirm(player)
                else:
                    self._cmd_db_new_direct(sender)
                return True
            if db_sub in ("list", "archives"):
                if player is None:
                    self._cmd_db_list_console(sender)
                else:
                    self.forms.show_db_archives(player)
                return True
            if db_sub == "restore":
                if player is None:
                    self._cmd_db_restore_console(sender)
                else:
                    self.forms.show_db_archives(player)
                return True
            sender.send_message(
                f"{ColorFormat.GOLD}用法：/mxback db [new|list|restore]"
            )
            return True

        if sub == "reload":
            if not self._is_op_or_console(sender):
                sender.send_error_message("只有管理员可以重载配置")
                return True
            try:
                self.cfg.load()
                # permissions.json 可能被直接编辑：一并重载
                self.permissions = PermissionManager(self.data_folder, self.cfg)
                self.container_ids = frozenset(
                    self.cfg.get("containers", default=[])
                )
                self.lang = Lang(self)
                # 落盘间隔 / 粒子配置可能改变：重启相关任务
                self._start_flush_task()
                self._start_particle_task()
                sender.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
                    f"配置已从磁盘重载并生效"
                )
            except Exception as e:
                sender.send_error_message(f"重载失败: {e}")
            return True

        sender.send_message(HELP_TEXT)
        return True

    def _report_undo(self, sender: CommandSender, stats: dict) -> None:
        player = sender if isinstance(sender, Player) else None
        if "error" in stats:
            sender.send_error_message(stats["error"])
            return
        if stats.get("busy"):
            sender.send_error_message("已有回档/撤销任务正在进行，请稍候")
            return
        if "started" in stats:
            sender.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                f"撤销已启动：会话 #{stats['session_id']}，"
                f"共 {stats['expected']} 个方块，分批执行中……"
            )
            return
        if stats.get("no_snapshot"):
            sender.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                f"该回档没有产生实际的方块变化，无需撤销；"
                f"相关日志已恢复为未回档状态，可再次回档。"
            )
            return
        restored = stats.get("restored", 0)
        failed = stats.get("failed", 0)
        if player is not None:
            player.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
                f"已撤销回档：恢复 {restored} 个方块（失败 {failed}）。"
                f"相关日志已恢复为未回档状态，可再次回档。"
            )
        else:
            sender.send_message(
                f"[MxBack] 已撤销回档：恢复 {restored} 个方块（失败 {failed}）"
            )

    # 状态与压缩输出
    def _cmd_status(self, sender: CommandSender) -> None:
        stats = self.db.stats()
        log_stats = self.daily.stats()
        cats = self.cfg.get("logs", "categories", default={})
        lines = [
            f"{ColorFormat.GOLD}【 MxBack 运行状态 】",
            f"{ColorFormat.WHITE}方块日志：{stats['total']} 条"
            f"（已回档 {stats['rolled_back']} 条）",
            f"事件日志：{stats['events']} 条",
            f"回档会话：{stats['sessions']} 次",
        ]
        on_off = {True: "开", False: "关"}
        enabled_summary = "，".join(
            k for k, v in sorted(cats.items()) if v
        )
        lines.append(f"已开启分类：{enabled_summary or '无'}")
        if stats["oldest_ts"]:
            oldest = datetime.fromtimestamp(stats["oldest_ts"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            lines.append(f"最早记录：{oldest}")
        lines.append(
            f"日志文件：待归档 {log_stats['pending_days']} 天"
            f"（{log_stats['logs_bytes'] // 1024} KB），"
            f"压缩包 {log_stats['archives']} 个"
            f"（{log_stats['archives_bytes'] // 1024} KB）"
        )
        lines.append(
            f"异步落盘：{on_off[bool(self.cfg.get('performance', 'async_flush', default=True))]}"
            f"，分批回档：{self.cfg.get('rollback', 'blocks_per_batch', default=400)} 个/批"
        )
        per = stats["per_action"]
        if per:
            top = sorted(per.items(), key=lambda kv: -kv[1])[:8]
            detail = "，".join(f"{self.lang.action_name(k)} {v}" for k, v in top)
            lines.append(f"{ColorFormat.GRAY}分类条数：{detail}")
        sender.send_message("\n".join(lines))

    # 数据库管理：控制台输出与直接执行（游戏内为表单）
    @staticmethod
    def _fmt_size(n: int) -> str:
        n = max(0, int(n))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n}{unit}" if unit == "B" else f"{n:.1f}{unit}"
            n /= 1024
        return f"{n:.1f}TB"

    def _cmd_db_status(self, sender: CommandSender) -> None:
        stats = self.db.stats()
        archives = self.db.list_archives()
        oldest = (
            datetime.fromtimestamp(stats["oldest_ts"]).strftime("%Y-%m-%d %H:%M")
            if stats["oldest_ts"] else "无记录"
        )
        lines = [
            f"{ColorFormat.GOLD}【 MxBack 数据库管理 】",
            f"{ColorFormat.WHITE}现行库：{stats['total']} 条方块日志 · "
            f"{stats['events']} 条事件 · {stats['sessions']} 次回档",
            f"库文件：{self._fmt_size(self.db.db_file_size())} · "
            f"最早记录 {oldest}",
            f"归档库：{len(archives)} 个"
            f"（共 {self._fmt_size(sum(a['size'] for a in archives))}）",
            f"{ColorFormat.GRAY}命令：/mxback db new（归档当前库） · "
            f"/mxback db list · /mxback db restore <序号>",
            f"{ColorFormat.GRAY}游戏内可用 /mxback db 打开图形化管理界面",
        ]
        sender.send_message("\n".join(lines))

    def _cmd_db_list_console(self, sender: CommandSender) -> None:
        archives = self.db.list_archives()
        if not archives:
            sender.send_message("暂无归档数据库（用 /mxback db new 创建）")
            return
        lines = [f"{ColorFormat.GOLD}【 归档数据库（新 -> 旧）】"]
        for i, e in enumerate(archives):
            comp = f"{e['compressed']} 压缩" if e["compressed"] else "未压缩"
            info = e["info"] or {}
            n_blocks = info.get("total", "?")
            n_ev = info.get("events", "?")
            lines.append(
                f"{ColorFormat.WHITE}[{i}] {e['name']}"
                f"{ColorFormat.GRAY} {self._fmt_size(e['size'])} · {comp}"
                f" · 方块日志 {n_blocks} 条 · 事件 {n_ev} 条"
            )
        lines.append(
            f"{ColorFormat.GRAY}恢复：/mxback db restore <序号或文件名>"
            f"（当前库会自动转归档，数据不丢）"
        )
        sender.send_message("\n".join(lines))

    def _cmd_db_new_direct(self, sender: CommandSender) -> None:
        result = self.db_new()
        if "error" in result:
            sender.send_error_message(result["error"])
            return
        info = result["info"]
        sender.send_message(
            f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
            f"已新建数据库。原库已归档为 {result['archive']}"
            f"（{info.get('total', 0)} 条方块日志 · "
            f"{self._fmt_size(info.get('size_bytes', 0))}）"
        )

    def _cmd_db_restore_console(self, sender: CommandSender) -> None:
        # 命令参数长度只有 2 段，带序号无法输入：引导去游戏内表单操作
        self._cmd_db_list_console(sender)
        sender.send_message(
            f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GRAY} "
            f"恢复需要指定归档，命令行参数放不下："
            f"请在游戏内输入 /mxback db 用表单操作恢复"
        )

    def _cmd_compress(self, sender: CommandSender, strategy: Optional[str]) -> None:
        strategy = strategy or self.cfg.get("logs", "strategy", default="auto")
        gzip_days = int(self.cfg.get("logs", "auto_gzip_days", default=7))
        keep_days = int(self.cfg.get("logs", "keep_archives_days", default=0))
        # xz 极限压缩耗时可达分钟级：后台执行，结果稍后反馈
        notify_name = sender.name if isinstance(sender, Player) else None
        started = self._start_bg_compress(
            strategy, gzip_days, keep_days, notify_name=notify_name
        )
        if started:
            sender.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                f"压缩已在后台启动（{strategy}），完成后将通知结果，"
                f"不会影响服务器运行"
            )

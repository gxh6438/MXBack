"""表单 UI：主菜单、回档、回档记录撤销、配置编辑（热重载）、
日志文件浏览与数据库查询。"""

import json
import time
from datetime import datetime
from typing import Optional

from endstone import ColorFormat, Player
from endstone.form import (
    ActionForm,
    Dropdown,
    ModalForm,
    TextInput,
    Toggle,
)

from .database import ROLLBACK_ACTIONS
from .i18n import Lang
from .permissions import PERMISSION_ITEMS, PERM_KEYS
from .rollback import parse_block_ids

PAGE_SIZE = 10
TIME_UNITS = [("分钟", 60), ("小时", 3600), ("天", 86400)]
TIME_WINDOWS = [
    ("10分钟", 600), ("1小时", 3600), ("6小时", 21600),
    ("24小时", 86400), ("7天", 604800), ("30天", 2592000),
]

# 图标均为基岩版原版贴图路径
ICONS = {
    "start": "textures/items/wood_axe",
    "stop": "textures/blocks/barrier",
    "rollback": "textures/items/ender_pearl",
    "history": "textures/items/recovery_compass_item",
    "logs": "textures/items/book_writable",
    "lookup": "textures/items/paper",
    "config": "textures/ui/settings_glyph_color_2x",
    "status": "textures/items/clock_item",
    "archive": "textures/items/fireworks",
    "help": "textures/items/map_filled",
    "db": "textures/items/ender_eye",
    "selection": "textures/items/wood_axe",
    "performance": "textures/items/netherite_ingot",
    "particle": "textures/items/glowstone_dust",
    "category": "textures/items/book_normal",
    "access": "textures/items/gold_ingot",
    "language": "textures/items/name_tag",
    "search": "textures/ui/magnifyingGlass",
    "player": "textures/ui/icon_steve",
    "global": "textures/items/book_normal",
    "refresh": "textures/items/compass_item",
    "undo": "textures/items/recovery_compass_item",
    "back": "textures/items/arrow",
}

# 日志文件分类视图：key -> (显示名, 文件列表)；None = 全部分类
LOG_CATEGORY_VIEWS = {
    "all": ("全部", None),
    "break": ("玩家破坏", ["break.log"]),
    "place": ("玩家放置", ["place.log"]),
    "explode": ("爆炸摧毁", ["explosion.log"]),
    "container_open": ("容器交互", ["container.log"]),
    "click": ("方块交互", ["click.log"]),
    "world": ("世界事件", ["world.log"]),
    "chat": ("聊天消息", ["chat.log"]),
    "command": ("命令执行", ["command.log"]),
    "session": ("上下线", ["session.log"]),
    "kill": ("击杀死亡", ["kill.log"]),
    "item": ("物品操作", ["item.log"]),
    "player": ("玩家行为", ["player.log"]),
    "rollback": ("回档记录", ["rollback.log"]),
}

LOG_VIEW_ICONS = {
    "all": "textures/items/book_writable",
    "break": "textures/items/wood_pickaxe",
    "place": "textures/blocks/crafting_table_top",
    "explode": "textures/items/fireball",
    "container_open": "textures/items/hopper",
    "click": "textures/items/lever",
    "world": "textures/items/wheat",
    "chat": "textures/items/sign",
    "command": "textures/items/minecart_command_block",
    "session": "textures/items/door_spruce",
    "kill": "textures/items/wood_sword",
    "item": "textures/items/apple",
    "player": "textures/items/name_tag",
    "rollback": "textures/items/recovery_compass_item",
}

# 日志分类开关：key -> 显示名（顺序即表单控件顺序）
LOG_CATEGORY_TOGGLES = [
    ("block_break", "记录：玩家破坏方块"),
    ("block_place", "记录：玩家放置方块"),
    ("explosion", "记录：爆炸（TNT/苦力怕/凋灵/床）"),
    ("leaves_decay", "记录：树叶自然枯萎（可回档）"),
    ("block_grow", "记录：作物/竹子自然生长（可回档）"),
    ("block_form", "记录：液体凝固（黑曜石/圆石，可回档）"),
    ("liquid_flow", "记录：液体流动（可回档，量大慎开）"),
    ("container_open", "记录：容器交互（打开箱子等）"),
    ("click", "记录：门/按钮/拉杆交互"),
    ("entity_interact", "记录：右键实体（村民/盔甲架/船/展示框等）"),
    ("bone_meal", "记录：骨粉催熟（可回档：树消失/作物退回/树苗恢复）"),
    ("chat", "记录：聊天消息"),
    ("command", "记录：命令执行（含控制台）"),
    ("session", "记录：加入/退出/被踢"),
    ("kill", "记录：玩家死亡/生物被击杀"),
    ("item_drop", "记录：丢弃物品"),
    ("item_pickup", "记录：拾取物品"),
    ("item_consume", "记录：吃食物/喝药水"),
    ("gamemode", "记录：切换游戏模式"),
    ("teleport", "记录：传送（量大）"),
    ("bed", "记录：上床/起床"),
    ("piston", "记录：活塞推动（量大，慎开）"),
    ("block_cook", "记录：熔炉/营火烤制"),
    ("weather", "记录：天气/雷暴变化"),
    ("broadcast", "记录：服务器广播消息"),
    ("plugin", "记录：插件启用/禁用（管理审计）"),
    ("dimension", "记录：玩家跨越维度"),
    ("respawn", "记录：玩家重生"),
    ("emote", "记录：播放表情动作"),
]

BLOCK_QUERY_LABELS = [
    ("all", "全部"), ("break", "破坏"), ("place", "放置"),
    ("explode", "爆炸"), ("container_open", "容器交互"),
    ("click", "方块交互"), ("grow", "枯萎/生长/凝固"),
    ("liquid", "液体流动"), ("piston", "活塞"), ("cook", "烤制"),
]
BLOCK_QUERY_ACTIONS = {
    "all": list(ROLLBACK_ACTIONS) + ["container_open", "click"],
    "break": ["break"],
    "place": ["place"],
    "explode": ["explode"],
    "container_open": ["container_open"],
    "click": ["click"],
    "grow": ["leaves_decay", "block_grow", "block_form"],
    "liquid": ["liquid_flow"],
    "piston": ["piston"],
    "cook": ["block_cook"],
}
EVENT_QUERY_LABELS = [
    ("all", "全部"), ("chat", "聊天"), ("command", "命令"),
    ("session", "上下线"), ("kill", "死亡/击杀"), ("item", "物品操作"),
    ("player", "玩家行为"), ("plugin", "插件"),
    ("broadcast", "广播"),
]
_EVENT_ALL = [
    "chat", "command", "broadcast", "join", "quit", "kick", "kill",
    "entity_kill", "item_drop", "item_pickup", "item_consume",
    "gamemode", "teleport", "bed_enter", "bed_leave",
    "dimension_change", "respawn", "emote",
    "entity_interact", "plugin_enable", "plugin_disable",
]
EVENT_QUERY_ACTIONS = {
    "all": _EVENT_ALL,
    "chat": ["chat"],
    "command": ["command"],
    "session": ["join", "quit", "kick"],
    "kill": ["kill", "entity_kill"],
    "item": ["item_drop", "item_pickup", "item_consume"],
    "player": [
        "gamemode", "teleport", "bed_enter", "bed_leave",
        "dimension_change", "respawn", "emote", "entity_interact",
    ],
    "plugin": ["plugin_enable", "plugin_disable"],
    "broadcast": ["broadcast"],
}


def _btn(color: str, title: str, desc: str) -> str:
    return (
        f"{ColorFormat.BOLD}{color}{title}{ColorFormat.RESET}"
        f"\n{ColorFormat.YELLOW}{desc}"
    )


def _form_values(result: str, min_len: int) -> Optional[list]:
    """解析表单返回的 JSON 列表；失败或长度不足返回 None。"""
    try:
        values = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(values, list) or len(values) < min_len:
        return None
    return values


def _idx(raw, length: int) -> int:
    """下拉框索引钳制后作为数组下标。"""
    i = int(raw) if isinstance(raw, (int, float)) else 0
    return max(0, min(i, length - 1))


def _to_int(raw, current: int, lo=None, hi=None) -> int:
    try:
        v = int(str(raw).strip())
    except (ValueError, TypeError):
        return current
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _to_float(raw, current: float, lo=None, hi=None) -> float:
    try:
        v = float(str(raw).strip())
    except (ValueError, TypeError):
        return current
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _parse_xyz(raw) -> tuple[int, int, int]:
    """解析 "X, Y, Z"（中英文逗号均可）；失败抛 ValueError。"""
    parts = [s.strip() for s in str(raw).replace("，", ",").split(",")]
    if len(parts) != 3:
        raise ValueError(f"{raw!r} 需要 3 个以逗号分隔的整数")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


class Forms:
    def __init__(self, plugin):
        self.plugin = plugin

    def _can(self, player: Player, key: str) -> bool:
        if bool(player.is_op):
            return True
        return self.plugin.permissions.has(player.name, key)

    def _can_any(self, player: Player, *keys: str) -> bool:
        return any(self._can(player, k) for k in keys)

    def _is_op(self, player: Player) -> bool:
        return bool(player.is_op)

    def _save_cfg(self, p: Player, what: str) -> None:
        try:
            self.plugin.cfg.save()
            p.play_sound(p.location, "random.orb")
            p.send_toast("MxBack", f"{what}已保存并实时生效")
            p.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
                f"{what}已保存并实时生效（已写回 config.json）"
            )
        except OSError:
            p.send_error_message("配置写回磁盘失败，但本次修改已实时生效")

    def _cmd(self, player: Player, sub: str) -> None:
        from endstone.command import Command

        self.plugin.on_command(player, Command(name="mxback"), [sub])

    # 主菜单
    def show_main_menu(self, player: Player) -> None:
        plugin = self.plugin
        can_sel = self._can(player, "selection")
        can_rb = self._can(player, "rollback")
        can_selq = self._can(player, "selection_lookup")
        can_undo = self._can_any(player, "undo", "undo_others", "history")
        can_look = self._can_any(player, "lookup_files", "lookup_db")
        can_status = self._can(player, "status")
        is_op = self._is_op(player)

        selecting = plugin.is_selecting(player.name)
        sel = plugin.selection.get(player.name)
        lines = [
            f"{ColorFormat.BOLD}{ColorFormat.GOLD}【 MxBack 主菜单 】"
            f"{ColorFormat.RESET}",
            f"{ColorFormat.GRAY}方块日志 · 区域回档 · 撤销 · 查询 · 配置",
            "",
        ]
        if selecting:
            lines.append(
                f"{ColorFormat.GREEN}{ColorFormat.BOLD}● 选区模式：开启中"
                f"{ColorFormat.RESET}"
            )
            if sel is not None:
                lines.append(
                    f"{ColorFormat.GRAY}第一点 {sel.pos1 or '待选'}"
                    f"   第二点 {sel.pos2 or '待选'}"
                )
        else:
            lines.append(
                f"{ColorFormat.GRAY}○ 选区模式：未开启（/mxback start）"
            )
        if sel is not None and sel.complete():
            lines.append(f"{ColorFormat.GRAY}已选体积：{sel.volume()} 方块")

        form = ActionForm(
            title="MxBack 主菜单",
            content="\n".join(lines),
            on_close=lambda p: p.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GRAY} "
                f"菜单已关闭，输入 /mxback 重新打开"
            ),
        )
        if can_sel:
            if selecting:
                form.add_button(
                    _btn(ColorFormat.RED, "停止选区", "/mxback stop · 工具点击失效"),
                    ICONS["stop"],
                    on_click=lambda p: self._cmd(p, "stop"),
                )
            else:
                form.add_button(
                    _btn(ColorFormat.GREEN, "开始选区", "/mxback start · 工具点击生效"),
                    ICONS["start"],
                    on_click=lambda p: self._cmd(p, "start"),
                )
        if can_rb or can_selq:
            form.add_button(
                _btn(ColorFormat.AQUA, "选区操作", "/mxback menu · 回档/查看选区内日志"),
                ICONS["rollback"],
                on_click=lambda p: self.show_selection_menu(p),
            )
        if can_undo:
            form.add_button(
                _btn(ColorFormat.LIGHT_PURPLE, "撤销操作", "回档记录 · 可撤销任意一次"),
                ICONS["history"],
                on_click=lambda p: self.show_history(p),
            )
        if can_look:
            form.add_button(
                _btn(ColorFormat.YELLOW, "日志中心",
                     "日志文件（任意日期）· 数据库查询"),
                ICONS["logs"],
                on_click=lambda p: self.show_log_center(p),
            )
        if can_status:
            form.add_button(
                _btn(ColorFormat.MINECOIN_GOLD, "运行状态", "/mxback status"),
                ICONS["status"],
                on_click=lambda p: self.plugin._cmd_status(p),
            )
        if is_op:
            form.add_button(
                _btn(ColorFormat.MATERIAL_REDSTONE, "配置文件", "所有配置项 · 热重载"),
                ICONS["config"],
                on_click=lambda p: self.show_config_menu(p),
            )
            form.add_button(
                _btn(ColorFormat.MATERIAL_GOLD, "权限管理",
                     "全局默认 · 单玩家权限设置"),
                ICONS["access"],
                on_click=lambda p: self.show_perm_menu(p),
            )
            form.add_button(
                _btn(ColorFormat.MATERIAL_EMERALD, "日志归档", "立即压缩旧日志文件"),
                ICONS["archive"],
                on_click=lambda p: self.plugin._cmd_compress(p, None),
            )
            form.add_button(
                _btn(ColorFormat.MATERIAL_DIAMOND, "数据库管理",
                     "新建数据库 · 归档列表 · 恢复"),
                ICONS["db"],
                on_click=lambda p: self.show_db_menu(p),
            )
        form.add_button(
            _btn(ColorFormat.BLUE, "命令帮助", "/mxback help"),
            ICONS["help"],
            on_click=lambda p: self._cmd(p, "help"),
        )
        player.send_form(form)

    # 数据库管理
    def show_db_menu(self, player: Player) -> None:
        plugin = self.plugin
        stats = plugin.db.stats()
        size = plugin._fmt_size(plugin.db.db_file_size())
        archives = plugin.db.list_archives()
        oldest = (
            datetime.fromtimestamp(stats["oldest_ts"]).strftime("%Y-%m-%d %H:%M")
            if stats["oldest_ts"] else "无记录"
        )
        lines = [
            f"{ColorFormat.BOLD}{ColorFormat.GOLD}【 数据库管理 】{ColorFormat.RESET}",
            f"{ColorFormat.GRAY}现行库 {size} · 最早记录 {oldest}",
            f"{ColorFormat.GRAY}方块日志 {stats['total']} 条 · "
            f"事件 {stats['events']} 条",
            f"{ColorFormat.GRAY}回档会话 {stats['sessions']} 次 · "
            f"已回档 {stats['rolled_back']} 条",
            f"{ColorFormat.GRAY}归档库 {len(archives)} 个",
            "",
            f"{ColorFormat.YELLOW}新建数据库 = 当前库整体转归档并从空库开始；",
            f"{ColorFormat.YELLOW}回档/撤销/查询将只针对新库（旧数据可随时恢复）",
        ]
        form = ActionForm(title="MxBack 数据库管理", content="\n".join(lines))
        form.add_button(
            _btn(ColorFormat.GREEN, "新建数据库", "当前库转归档 · 从空库开始"),
            ICONS["db"],
            on_click=lambda p: self.show_db_new_confirm(p),
        )
        form.add_button(
            _btn(ColorFormat.AQUA, "归档库列表",
                 f"共 {len(archives)} 个 · 查看详情并恢复"),
            ICONS["archive"],
            on_click=lambda p: self.show_db_archives(p),
        )
        form.add_button(
            _btn(ColorFormat.BLUE, "返回主菜单", "回到 MxBack 主菜单"),
            ICONS["back"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    def show_db_new_confirm(self, player: Player) -> None:
        plugin = self.plugin
        if plugin._db_swapping or plugin.rollback.is_busy():
            player.send_error_message("数据库切换或回档任务进行中，请稍候再试")
            return
        content = "\n".join([
            f"{ColorFormat.BOLD}{ColorFormat.GOLD}【 新建数据库 】{ColorFormat.RESET}",
            "",
            f"{ColorFormat.WHITE}确认后将立即执行：",
            f"{ColorFormat.GREEN}1. 当前数据库整体转存为归档（数据不丢，可随时恢复）",
            f"{ColorFormat.GREEN}2. 归档完成后后台压缩，磁盘占用大幅下降",
            f"{ColorFormat.GREEN}3. 插件从全新的空数据库开始记录",
            "",
            f"{ColorFormat.YELLOW}注意：回档、撤销与查询此后只针对新库；",
            f"{ColorFormat.YELLOW}需要历史数据时先在归档列表中恢复。",
        ])
        form = ActionForm(title="确认新建数据库", content=content)
        form.add_button(
            _btn(ColorFormat.GREEN, "确认新建", "当前库转归档 · 从空库开始"),
            ICONS["db"],
            on_click=lambda p: self._do_db_new(p),
        )
        form.add_button(
            _btn(ColorFormat.GRAY, "取消", "返回数据库管理"),
            ICONS["back"],
            on_click=lambda p: self.show_db_menu(p),
        )
        player.send_form(form)

    def _do_db_new(self, player: Player) -> None:
        plugin = self.plugin
        result = plugin.db_new()
        if "error" in result:
            player.send_error_message(result["error"])
            return
        info = result["info"]
        try:
            player.play_sound(player.location, "random.orb")
            player.send_toast("MxBack", "数据库已轮换")
        except Exception:
            pass
        player.send_message(
            f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
            f"已新建数据库。原库归档为 {result['archive']}"
            f"（{info.get('total', 0)} 条方块日志 · "
            f"{plugin._fmt_size(info.get('size_bytes', 0))}），"
            f"归档压缩将在后台完成"
        )

    def show_db_archives(self, player: Player) -> None:
        plugin = self.plugin
        entries = plugin.db.list_archives()
        lines = [
            f"{ColorFormat.BOLD}{ColorFormat.GOLD}【 归档数据库列表 】{ColorFormat.RESET}",
            f"{ColorFormat.GRAY}点击任意归档查看详情并恢复",
        ]
        form = ActionForm(title="MxBack 归档数据库", content="\n".join(lines))
        if not entries:
            form.add_button(
                _btn(ColorFormat.GRAY, "暂无归档", "用「新建数据库」创建归档"),
                ICONS["archive"],
                on_click=lambda p: self.show_db_menu(p),
            )
        for e in entries:
            info = e["info"] or {}
            when = datetime.fromtimestamp(
                info.get("archived_at", e["mtime"])
            ).strftime("%Y-%m-%d %H:%M")
            comp = f"{e['compressed']} 压缩" if e["compressed"] else "未压缩"
            desc = f"{when} · {plugin._fmt_size(e['size'])} · {comp}"
            if "total" in info:
                desc += f" · {info['total']} 条记录"
            form.add_button(
                _btn(ColorFormat.WHITE, e["base"], desc),
                ICONS["archive"],
                on_click=lambda p, name=e["name"]: self.show_db_archive_detail(
                    p, name
                ),
            )
        form.add_button(
            _btn(ColorFormat.BLUE, "返回数据库管理", "回到上一页"),
            ICONS["back"],
            on_click=lambda p: self.show_db_menu(p),
        )
        player.send_form(form)

    def show_db_archive_detail(self, player: Player, name: str) -> None:
        plugin = self.plugin
        entry = plugin.db.find_archive(name)
        if entry is None:
            player.send_error_message(f"归档 {name} 不存在或已被恢复")
            self.show_db_archives(player)
            return
        info = entry["info"] or {}
        when = datetime.fromtimestamp(
            info.get("archived_at", entry["mtime"])
        ).strftime("%Y-%m-%d %H:%M:%S")
        comp = f"{entry['compressed']} 压缩 · " if entry["compressed"] else ""
        lines = [
            f"{ColorFormat.BOLD}{ColorFormat.GOLD}【 归档详情 】{ColorFormat.RESET}",
            f"{ColorFormat.WHITE}{entry['name']}",
            f"{ColorFormat.GRAY}归档时间 {when} · {comp}"
            f"文件 {plugin._fmt_size(entry['size'])}",
        ]
        if info:
            oldest = (
                datetime.fromtimestamp(info["oldest_ts"]).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if info.get("oldest_ts") else "无"
            )
            lines += [
                f"{ColorFormat.GRAY}方块日志 {info.get('total', 0)} 条"
                f"（已回档 {info.get('rolled_back', 0)}）· "
                f"事件 {info.get('events', 0)} 条",
                f"{ColorFormat.GRAY}回档会话 {info.get('sessions', 0)} 次 · "
                f"最早记录 {oldest}",
            ]
        lines += [
            "",
            f"{ColorFormat.YELLOW}恢复 = 把它换回来作为现行库；",
            f"{ColorFormat.YELLOW}当前库会自动转归档，数据不丢。",
        ]
        form = ActionForm(title="MxBack 归档详情", content="\n".join(lines))
        form.add_button(
            _btn(ColorFormat.GREEN, "恢复此数据库", "当前库转归档 · 它成为现行库"),
            ICONS["undo"],
            on_click=lambda p: self.show_db_restore_confirm(p, entry["name"]),
        )
        form.add_button(
            _btn(ColorFormat.BLUE, "返回列表", "选择其它归档"),
            ICONS["back"],
            on_click=lambda p: self.show_db_archives(p),
        )
        player.send_form(form)

    def show_db_restore_confirm(self, player: Player, name: str) -> None:
        plugin = self.plugin
        if plugin._db_swapping:
            player.send_error_message("数据库切换正在进行，请稍候")
            return
        if plugin.rollback.is_busy():
            player.send_error_message("有回档/撤销正在进行，请等它结束再恢复")
            return
        content = "\n".join([
            f"{ColorFormat.BOLD}{ColorFormat.GOLD}【 确认恢复 】{ColorFormat.RESET}",
            "",
            f"{ColorFormat.WHITE}把归档 {name} 恢复为现行数据库：",
            f"{ColorFormat.GREEN}1. 当前库自动转归档（数据不丢）",
            f"{ColorFormat.GREEN}2. 解压与切换在后台完成，完成后消息通知",
            f"{ColorFormat.YELLOW}回档/撤销/查询将切换到这份历史数据上。",
        ])
        form = ActionForm(title="确认恢复归档", content=content)
        form.add_button(
            _btn(ColorFormat.GREEN, "确认恢复", name),
            ICONS["undo"],
            on_click=lambda p: self._do_db_restore(p, name),
        )
        form.add_button(
            _btn(ColorFormat.GRAY, "取消", "返回归档详情"),
            ICONS["back"],
            on_click=lambda p: self.show_db_archive_detail(p, name),
        )
        player.send_form(form)

    def _do_db_restore(self, player: Player, name: str) -> None:
        plugin = self.plugin
        result = plugin.db_restore(player.name, name)
        if "error" in result:
            player.send_error_message(result["error"])
            return
        player.send_message(
            f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
            f"恢复已启动：正在后台准备 {result['name']}，完成后会通知你"
        )

    # 选区操作
    def show_selection_menu(self, player: Player) -> None:
        can_rb = self._can(player, "rollback")
        can_selq = self._can(player, "selection_lookup")
        if not can_rb and not can_selq:
            player.send_error_message("你没有权限使用选区操作功能")
            return
        sel = self.plugin.selection.get(player.name)
        if sel is None or not sel.complete():
            player.send_error_message(
                "尚未选好两个点：请先 /mxback start，再手持选区工具"
                "右键点击方块依次选择两点"
            )
            return
        content = "\n".join([
            f"{ColorFormat.BOLD}{ColorFormat.GOLD}选区已就绪{ColorFormat.RESET}",
            f"维度：{self.plugin.lang.dimension_name(sel.dimension)}",
            f"第一点：{sel.pos1}",
            f"第二点：{sel.pos2}",
            f"体积：{sel.volume()} 方块",
            "",
            f"{ColorFormat.GRAY}选择要执行的操作：",
        ])
        form = ActionForm(
            title="选区操作",
            content=content,
            on_close=lambda p: p.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GRAY} "
                f"已取消（选区保留，可用 /mxback menu 重新打开）"
            ),
        )
        if can_rb:
            form.add_button(
                _btn(ColorFormat.AQUA, "选区回档", "恢复区域内的方块变更"),
                ICONS["rollback"],
                on_click=lambda p: self.show_rollback(p),
            )
        if can_selq:
            form.add_button(
                _btn(ColorFormat.GOLD, "查看选区内日志", "按分类查看此区域内的变更记录"),
                ICONS["logs"],
                on_click=lambda p: self.show_selection_logs(p),
            )
        form.add_button(
            _btn(ColorFormat.BLUE, "返回主菜单", "回到 MxBack 主菜单"),
            ICONS["back"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    # 选区内日志查询
    def show_selection_logs(self, player: Player) -> None:
        if not self._can(player, "selection_lookup"):
            player.send_error_message("你没有权限查询选区内日志")
            return
        sel = self.plugin.selection.get(player.name)
        if sel is None or not sel.complete():
            player.send_error_message(
                "尚未选好两个点：请先 /mxback start，再手持选区工具"
                "右键点击方块依次选择两点"
            )
            return

        def on_submit(p: Player, result: str):
            values = _form_values(result, 2)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            self._show_selection_log_results(
                p, int(values[0] or 0), int(values[1] or 0), 1
            )

        form = ModalForm(
            title="查看选区内日志",
            controls=[
                Dropdown("分类", [lab for _, lab in BLOCK_QUERY_LABELS]),
                Dropdown(
                    "时间范围",
                    [w[0] for w in TIME_WINDOWS],
                    default_index=3,
                ),
            ],
            submit_button="查询",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

    def _show_selection_log_results(
        self, player: Player, cat_idx: int, win_idx: int, page: int,
    ) -> None:
        plugin = self.plugin
        sel = plugin.selection.get(player.name)
        if sel is None or not sel.complete():
            player.send_error_message("选区已失效，请重新选择两点")
            return
        cat_key = BLOCK_QUERY_LABELS[_idx(cat_idx, len(BLOCK_QUERY_LABELS))][0]
        actions = BLOCK_QUERY_ACTIONS[cat_key]
        win_name, window = TIME_WINDOWS[_idx(win_idx, len(TIME_WINDOWS))]
        since_ts = time.time() - window
        lo, hi = sel.bounds()
        rows, total = plugin.db.query_region_block_log(
            lo, hi, sel.dimension, actions, since_ts, page, PAGE_SIZE
        )
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        # 页码越界（记录被清理/回档后总数变化）时回退到末页重查
        if page > total_pages:
            page = total_pages
            rows, total = plugin.db.query_region_block_log(
                lo, hi, sel.dimension, actions, since_ts, page, PAGE_SIZE
            )
        lang = plugin.lang
        cat_label = dict(BLOCK_QUERY_LABELS)[cat_key]
        if not rows:
            content = f"选区内最近 {win_name}内没有「{cat_label}」记录"
        else:
            lines = [f"共 {total} 条 · 第 {page}/{total_pages} 页", ""]
            for row in rows:
                t = datetime.fromtimestamp(row["ts"]).strftime("%m-%d %H:%M:%S")
                flag = "（已回档）" if row["rolled_back"] else ""
                lines.append(
                    f"{t} {row['actor']} {lang.action_name(row['action'])} "
                    f"{lang.block_name(row['block_type'])}{flag}"
                    f" @ ({row['x']}, {row['y']}, {row['z']})"
                )
            content = "\n".join(lines)

        form = ActionForm(
            title=f"选区内日志 · {cat_label}",
            content=content,
            on_close=lambda p: None,
        )
        if page > 1:
            form.add_button(
                "上一页", ICONS["back"],
                on_click=lambda p: self._show_selection_log_results(
                    p, cat_idx, win_idx, page - 1
                ),
            )
        if page < total_pages:
            form.add_button(
                "下一页", ICONS["back"],
                on_click=lambda p: self._show_selection_log_results(
                    p, cat_idx, win_idx, page + 1
                ),
            )
        form.add_button(
            "重新查询（改条件）", ICONS["refresh"],
            on_click=lambda p: self.show_selection_logs(p),
        )
        form.add_button(
            "返回选区操作", ICONS["back"],
            on_click=lambda p: self.show_selection_menu(p),
        )
        form.add_button(
            "返回主菜单", ICONS["help"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    # 回档表单
    def show_rollback(self, player: Player) -> None:
        if not self._can(player, "rollback"):
            player.send_error_message("你没有权限执行回档")
            return
        sel = self.plugin.selection.get(player.name)
        if sel is None or not sel.complete():
            player.send_error_message(
                "尚未选好两个点：请先 /mxback start，再手持选区工具"
                "右键点击方块依次选择两点"
            )
            return

        p1, p2 = sel.pos1, sel.pos2
        dim_name = self.plugin.lang.dimension_name(sel.dimension)
        cfg = self.plugin.cfg

        def on_submit(p: Player, result: str):
            values = _form_values(result, 8)
            if values is None:
                p.send_error_message("表单数据不完整，请重试")
                return
            try:
                pos1 = _parse_xyz(values[0])
                pos2 = _parse_xyz(values[1])
            except (ValueError, TypeError) as e:
                p.send_error_message(f"坐标格式错误：{e}（如 100, 64, -20）")
                return
            try:
                amount = float(str(values[2]).strip())
            except (ValueError, TypeError):
                p.send_error_message("回档时间必须为数字")
                return
            unit_name, multiplier = TIME_UNITS[_idx(values[3], len(TIME_UNITS))]
            seconds = amount * multiplier
            max_days = float(
                self.plugin.cfg.get("rollback", "max_time_days", default=30)
            )
            if seconds <= 0:
                p.send_error_message("回档时间必须大于 0")
                return
            if seconds > max_days * 86400:
                p.send_error_message(f"回档时间窗最大为 {int(max_days)} 天")
                return
            # 排除与仅回档互斥，两者都填以排除为准
            exclude = parse_block_ids(str(values[4]))
            only = parse_block_ids(str(values[5]))
            if exclude and only:
                only = set()
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.YELLOW} "
                    f"排除方块与仅回档方块同时填写，已按「排除方块」处理"
                )
            water = bool(values[6])
            lava = bool(values[7])
            cfg = self.plugin.cfg
            max_volume = int(cfg.get("selection", "max_volume", default=32768))
            min_y = int(cfg.get("selection", "min_y", default=-64))
            max_y = int(cfg.get("selection", "max_y", default=319))
            lo = tuple(min(a, b) for a, b in zip(pos1, pos2))
            hi = tuple(max(a, b) for a, b in zip(pos1, pos2))
            volume = (
                (hi[0] - lo[0] + 1) * (hi[1] - lo[1] + 1) * (hi[2] - lo[2] + 1)
            )
            if volume > max_volume:
                p.send_error_message(f"选区体积过大（{volume} > {max_volume}）")
                return
            lo = (lo[0], max(lo[1], min_y), lo[2])
            hi = (hi[0], min(hi[1], max_y), hi[2])
            sel_now = self.plugin.selection.get(p.name)
            if sel_now is None or not sel_now.complete():
                p.send_error_message("选区已失效，请重新选择两点")
                return
            stats = self.plugin.rollback.execute(
                p.name, lo, hi, sel_now.dimension, seconds, notify_name=p.name,
                exclude_blocks=exclude, only_blocks=only,
                rollback_water=water, rollback_lava=lava,
            )
            if "error" in stats:
                p.send_error_message(stats["error"])
                return
            if stats.get("busy"):
                p.send_error_message("已有回档/撤销任务正在进行，请稍候再试")
                return
            if stats.get("selected", 0) == 0:
                p.send_toast("MxBack", "区域内该时间段没有需要恢复的记录")
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                    f"区域内最近 {amount:g} {unit_name} 内没有可恢复的记录"
                    + ("（过滤条件排除了全部记录）" if stats.get("filtered") else "")
                )
                return
            note = "（达到单次上限，已截断）" if stats.get("truncated") else ""
            p.play_sound(p.location, "random.orb")
            p.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
                f"回档已启动{note}：{stats['selected']} 条记录，分批执行中"
                f"（会话 #{stats['session_id']}）\n"
                f"{ColorFormat.GRAY}完成后会自动通知；如需撤销，输入 /mxback undo"
                f"{ColorFormat.GRAY} 或在主菜单打开回档记录"
            )

        form = ModalForm(
            title=f"回档 · {dim_name}",
            controls=[
                TextInput(
                    "第一个点（X, Y, Z）",
                    default_value=f"{p1[0]}, {p1[1]}, {p1[2]}",
                ),
                TextInput(
                    "第二个点（X, Y, Z）",
                    default_value=f"{p2[0]}, {p2[1]}, {p2[2]}",
                ),
                TextInput("回档时间（数值）", default_value="30"),
                Dropdown("时间单位", [u[0] for u in TIME_UNITS]),
                TextInput(
                    "回档排除方块（逗号分隔，这些方块不会被回档）",
                    default_value=str(
                        cfg.get("rollback", "exclude_blocks", default="")
                    ),
                ),
                TextInput(
                    "仅回档方块（只回档这些方块，与上面互斥）",
                    default_value=str(
                        cfg.get("rollback", "only_blocks", default="")
                    ),
                ),
                Toggle(
                    "回档水（关闭后不会恢复任何水）",
                    bool(cfg.get("rollback", "rollback_water", default=True)),
                ),
                Toggle(
                    "回档岩浆（关闭后不会恢复任何岩浆）",
                    bool(cfg.get("rollback", "rollback_lava", default=True)),
                ),
            ],
            submit_button="确认回档",
            on_submit=on_submit,
            on_close=lambda p: p.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GRAY} "
                f"已取消（选区保留，可用 /mxback menu 重新打开表单）"
            ),
        )
        player.send_form(form)

    # 回档记录与撤销
    def show_history(self, player: Player, page: int = 1) -> None:
        if not self._can_any(player, "history", "undo", "undo_others"):
            player.send_error_message("你没有权限查看回档记录")
            return
        plugin = self.plugin
        # OP 与被授权撤销他人者可看全部记录；其余仅看自己的
        owner = (
            None
            if self._can(player, "undo_others")
            else player.name
        )
        sessions = plugin.db.list_sessions(player=owner, limit=60)
        if not sessions:
            form = ActionForm(
                title="回档记录",
                content="暂无回档记录",
                on_close=lambda p: None,
            )
            form.add_button(
                "返回主菜单", ICONS["back"],
                on_click=lambda p: self.show_main_menu(p),
            )
            player.send_form(form)
            return

        total_pages = (len(sessions) + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(1, min(page, total_pages))
        chunk = sessions[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

        form = ActionForm(
            title=f"回档记录（{page}/{total_pages}）",
            content=f"{ColorFormat.GRAY}点击任意一条记录查看详情，可撤销该次回档",
            on_close=lambda p: None,
        )
        lang = plugin.lang
        for s in chunk:
            t = datetime.fromtimestamp(s["ts"]).strftime("%m-%d %H:%M")
            dim_cn = lang.dimension_name(s["dimension"])
            state_txt = (
                f"{ColorFormat.DARK_GRAY}已撤销" if s["undone"]
                else f"{ColorFormat.GREEN}可撤销"
            )
            label = (
                f"{ColorFormat.BOLD}{ColorFormat.LIGHT_PURPLE}#{s['id']}"
                f" {t} {s['player']}{ColorFormat.RESET}\n"
                f"{ColorFormat.GRAY}{s['block_count']} 方块 · {dim_cn} · {state_txt}"
            )
            form.add_button(
                label, ICONS["history"],
                on_click=lambda p, sid=s["id"]: self.show_session_detail(p, sid),
            )
        if page > 1:
            form.add_button(
                "上一页", ICONS["back"],
                on_click=lambda p: self.show_history(p, page - 1),
            )
        if page < total_pages:
            form.add_button(
                "下一页", ICONS["back"],
                on_click=lambda p: self.show_history(p, page + 1),
            )
        form.add_button(
            "刷新", ICONS["refresh"],
            on_click=lambda p: self.show_history(p, page),
        )
        form.add_button(
            "返回主菜单", ICONS["help"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    def show_session_detail(self, player: Player, session_id: int) -> None:
        plugin = self.plugin
        s = plugin.db.get_session(session_id)
        if s is None:
            player.send_error_message(f"找不到回档会话 #{session_id}")
            return
        if (
            s["player"] != player.name
            and not self._can(player, "undo_others")
        ):
            player.send_error_message("你只能查看自己的回档记录")
            return
        lang = plugin.lang
        t = datetime.fromtimestamp(s["ts"]).strftime("%Y-%m-%d %H:%M:%S")
        secs = float(s["seconds"])
        if secs >= 86400:
            window = f"{secs / 86400:g} 天"
        elif secs >= 3600:
            window = f"{secs / 3600:g} 小时"
        else:
            window = f"{secs / 60:g} 分钟"
        state = (
            f"{ColorFormat.GREEN}未撤销（可撤销）" if not s["undone"]
            else f"{ColorFormat.GRAY}已撤销"
        )
        content = "\n".join([
            f"{ColorFormat.BOLD}{ColorFormat.LIGHT_PURPLE}回档会话 #{s['id']}",
            f"操作者：{s['player']}",
            f"时间：{t}",
            f"维度：{lang.dimension_name(s['dimension'])}",
            f"区域：({s['x1']}, {s['y1']}, {s['z1']}) 至 ({s['x2']}, {s['y2']}, {s['z2']})",
            f"时间窗：{window}",
            f"恢复方块数：{s['block_count']}",
            f"状态：{state}",
        ])
        form = ActionForm(
            title=f"回档会话 #{session_id}",
            content=content,
            on_close=lambda p: None,
        )
        if not s["undone"] and self._can_any(player, "undo", "undo_others"):
            form.add_button(
                _btn(ColorFormat.RED, "撤销这次回档", "恢复该次回档前的方块"),
                ICONS["undo"],
                on_click=lambda p: self._confirm_undo(p, session_id),
            )
        form.add_button(
            "返回记录列表", ICONS["back"],
            on_click=lambda p: self.show_history(p),
        )
        form.add_button(
            "返回主菜单", ICONS["help"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    def _confirm_undo(self, player: Player, session_id: int) -> None:
        plugin = self.plugin

        def on_submit(p: Player, result: str):
            values = _form_values(result, 1)
            if values is None or not values[0]:
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GRAY} 已取消撤销"
                )
                return
            stats = plugin.rollback.undo(
                p.name, session_id=session_id, notify_name=p.name,
                # OP/被授权撤销他人者可撤销任意会话
                allow_any=self._can(p, "undo_others"),
            )
            if stats is None:
                p.send_error_message(f"找不到回档会话 #{session_id}")
                return
            if "error" in stats:
                p.send_error_message(stats["error"])
                return
            if stats.get("busy"):
                p.send_error_message("已有回档/撤销任务正在进行，请稍候")
                return
            if "started" in stats:
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                    f"撤销已启动：会话 #{session_id}，"
                    f"共 {stats['expected']} 个方块，分批执行中……"
                )
            elif stats.get("no_snapshot"):
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                    f"回档 #{session_id} 没有产生实际的方块变化，无需撤销；"
                    f"日志已恢复为未回档状态，可再次回档"
                )
            else:
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
                    f"已撤销回档 #{session_id}：恢复 {stats.get('restored', 0)} 个方块"
                )

        form = ModalForm(
            title=f"确认撤销回档 #{session_id}？",
            controls=[
                Toggle("我确认撤销这次回档（方块将恢复到回档前）", False),
            ],
            submit_button="确认撤销",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

    # 日志中心
    def show_log_center(self, player: Player) -> None:
        can_files = self._can(player, "lookup_files")
        can_db = self._can(player, "lookup_db")
        if not can_files and not can_db:
            player.send_error_message("你没有权限查看日志")
            return
        form = ActionForm(
            title="MxBack 日志中心",
            content="\n".join([
                f"{ColorFormat.BOLD}{ColorFormat.GOLD}【 日志中心 】"
                f"{ColorFormat.RESET}",
                f"{ColorFormat.GRAY}· 日志文件：按玩家/分类分层的中文日志，"
                f"{ColorFormat.GRAY}  可选择任意历史日期浏览",
                f"{ColorFormat.GRAY}· 数据库查询：按分类/玩家/时间窗"
                f"{ColorFormat.GRAY}  筛选原始记录（方块 + 玩家事件）",
            ]),
            on_close=lambda p: None,
        )
        if can_files:
            form.add_button(
                _btn(ColorFormat.AQUA, "浏览日志文件", "选日期 · 全局/玩家 · 分类分页"),
                ICONS["logs"],
                on_click=lambda p: self._pick_log_date(p),
            )
        if can_db:
            form.add_button(
                _btn(ColorFormat.WHITE, "数据库查询", "分类/玩家/时间窗 · 方块与事件"),
                ICONS["lookup"],
                on_click=lambda p: self.show_lookup_menu(p),
            )
        form.add_button(
            "返回主菜单", ICONS["help"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    def _pick_log_date(self, player: Player) -> None:
        if not self._can(player, "lookup_files"):
            player.send_error_message("你没有权限浏览日志文件")
            return
        days = self.plugin.daily.list_days()
        today = time.strftime("%Y-%m-%d")
        if not days:
            form = ActionForm(
                title="选择日期",
                content="还没有任何日志文件（刚启用插件或日志已被清理）",
                on_close=lambda p: None,
            )
            form.add_button(
                "返回日志中心", ICONS["back"],
                on_click=lambda p: self.show_log_center(p),
            )
            player.send_form(form)
            return
        form = ActionForm(
            title="选择日期",
            content="\n".join([
                f"{ColorFormat.GRAY}共 {len(days)} 天日志，最新在最上面。",
                f"{ColorFormat.GRAY}已压缩归档的日期需解压后才能浏览。",
            ]),
            on_close=lambda p: None,
        )
        week = ["一", "二", "三", "四", "五", "六", "日"]
        for d in days[:36]:
            try:
                wd = week[datetime.strptime(d, "%Y-%m-%d").weekday()]
            except ValueError:
                wd = ""
            label = f"{d} · 今天（周{wd}）" if d == today else f"{d} · 周{wd}"
            form.add_button(
                label, ICONS["refresh"],
                on_click=lambda p, day=d: self.show_log_menu(p, day),
            )
        if len(days) > 36:
            form.add_button(
                f"……更早还有 {len(days) - 36} 天（稍早日期已省略）",
                ICONS["help"],
                on_click=lambda p: None,
            )
        form.add_button(
            "返回日志中心", ICONS["back"],
            on_click=lambda p: self.show_log_center(p),
        )
        player.send_form(form)

    # 日志文件浏览
    def _log_player_names(self, day: str) -> list[str]:
        today = day == time.strftime("%Y-%m-%d")
        if today:
            # 浏览今天时同步落盘，保证读到最新行
            try:
                self.plugin._flush()
                self.plugin.daily.flush()
            except Exception:
                pass
        logged = self.plugin.daily.list_players(day)
        if today:
            try:
                online = [p.name for p in self.plugin.server.online_players]
            except Exception:
                online = []
            return sorted(set(logged) | set(online))
        return sorted(set(logged))

    def _day_label(self, day: str) -> str:
        today = time.strftime("%Y-%m-%d")
        if day == today:
            return "今天"
        try:
            yesterday = datetime.fromordinal(
                datetime.strptime(today, "%Y-%m-%d").toordinal() - 1
            ).strftime("%Y-%m-%d")
            if day == yesterday:
                return "昨天"
        except ValueError:
            pass
        return day

    def show_log_menu(self, player: Player, day: str) -> None:
        if not self._can(player, "lookup_files"):
            player.send_error_message("你没有权限浏览日志文件")
            return
        players = self._log_player_names(day)
        content = "\n".join([
            f"{ColorFormat.GRAY}正在浏览 {self._day_label(day)} 的日志。",
            f"{ColorFormat.GRAY}每个玩家的日志独立分类存放，支持模糊搜索；",
            f"{ColorFormat.GRAY}自然事件 / 爆炸 / 管理审计等非玩家日志",
            f"{ColorFormat.GRAY}在「全局日志」中。",
        ])
        form = ActionForm(
            title=f"日志 · {self._day_label(day)}",
            content=content,
            on_close=lambda p: None,
        )
        form.add_button(
            _btn(ColorFormat.AQUA, "搜索玩家", "输入部分名字模糊查找"),
            ICONS["search"],
            on_click=lambda p: self._show_player_search(p, day),
        )
        for name in players[:50]:
            form.add_button(
                name, ICONS["player"],
                on_click=lambda p, n=name: self.show_player_categories(p, day, n),
            )
        if len(players) > 50:
            form.add_button(
                f"……共 {len(players)} 名玩家，请用「搜索玩家」查找",
                ICONS["search"],
                on_click=lambda p: self._show_player_search(p, day),
            )
        form.add_button(
            _btn(ColorFormat.WHITE, "全局日志", "自然事件 / 爆炸 / 管理审计"),
            ICONS["global"],
            on_click=lambda p: self.show_player_categories(p, day, None),
        )
        form.add_button(
            "返回日期选择", ICONS["back"],
            on_click=lambda p: self._pick_log_date(p),
        )
        player.send_form(form)

    def _show_player_search(self, player: Player, day: str) -> None:
        if not self._can(player, "lookup_files"):
            player.send_error_message("你没有权限浏览日志文件")
            return

        def on_submit(p: Player, result: str):
            values = _form_values(result, 1)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            query = str(values[0]).strip()
            if not query:
                self.show_log_menu(p, day)
                return
            self._show_player_matches(p, day, query)

        form = ModalForm(
            title=f"搜索玩家 · {self._day_label(day)}",
            controls=[
                TextInput(
                    "玩家名（输入部分名字即可，不区分大小写）",
                    placeholder="如 abc",
                ),
            ],
            submit_button="搜索",
            on_submit=on_submit,
            on_close=lambda p: self.show_log_menu(p, day),
        )
        player.send_form(form)

    def _show_player_matches(self, player: Player, day: str, query: str) -> None:
        players = self._log_player_names(day)
        q = query.lower()
        matches = [n for n in players if q in n.lower()]
        if not matches:
            content = (
                f"没有找到包含「{query}」的玩家名。\n"
                f"{ColorFormat.GRAY}搜索规则：输入的名字片段需为玩家名的"
                f"连续一段（如 abc123 可搜 abc、bc12、123），不区分大小写。"
            )
        else:
            content = f"找到 {len(matches)} 名玩家（含「{query}」）："
        form = ActionForm(
            title=f"搜索结果 · {query}",
            content=content,
            on_close=lambda p: None,
        )
        for name in matches[:50]:
            form.add_button(
                name, ICONS["player"],
                on_click=lambda p, n=name: self.show_player_categories(p, day, n),
            )
        form.add_button(
            "重新搜索", ICONS["search"],
            on_click=lambda p: self._show_player_search(p, day),
        )
        form.add_button(
            "返回玩家列表", ICONS["back"],
            on_click=lambda p: self.show_log_menu(p, day),
        )
        player.send_form(form)

    def show_player_categories(
        self, player: Player, day: str, actor: Optional[str]
    ) -> None:
        if not self._can(player, "lookup_files"):
            player.send_error_message("你没有权限浏览日志文件")
            return
        who = actor if actor else "全局（自然 / 爆炸 / 管理审计）"
        form = ActionForm(
            title=f"日志 · {self._day_label(day)} · {actor or '全局'}",
            content=f"{ColorFormat.GRAY}正在查看：{who}\n请选择日志分类：",
            on_close=lambda p: None,
        )
        for key, (label, _files) in LOG_CATEGORY_VIEWS.items():
            form.add_button(
                label,
                LOG_VIEW_ICONS.get(key, ICONS["logs"]),
                on_click=lambda p, k=key: self.show_day_log(
                    p, day, 1, k, actor
                ),
            )
        form.add_button(
            "返回玩家选择", ICONS["back"],
            on_click=lambda p: self.show_log_menu(p, day),
        )
        player.send_form(form)

    def show_day_log(
        self, player: Player, day: str, page: int = 1, category: str = "all",
        actor: Optional[str] = None,
    ) -> None:
        label, files = LOG_CATEGORY_VIEWS.get(
            category, LOG_CATEGORY_VIEWS["all"]
        )
        today = day == time.strftime("%Y-%m-%d")
        if today:
            try:
                self.plugin._flush()
                self.plugin.daily.flush()
            except Exception:
                pass
        total = self.plugin.daily.count_day(day, categories=files, actor=actor)
        day_cn = self._day_label(day)
        title = f"日志 · {day_cn} · {label}" + (f" · {actor}" if actor else "")
        if not total:
            form = ActionForm(
                title=title,
                content=f"{day_cn}「{label}」暂无日志记录",
                on_close=lambda p: None,
            )
            form.add_button(
                "返回分类选择", ICONS["back"],
                on_click=lambda p: self.show_player_categories(p, day, actor),
            )
            player.send_form(form)
            return
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(1, min(page, total_pages))
        # 流式分页：只读当前页窗口（O(页大小) 内存）
        lines = self.plugin.daily.read_day_page(
            day, categories=files, actor=actor,
            offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE,
        )

        form = ActionForm(
            title=title,
            content=f"第 {page}/{total_pages} 页，共 {total} 条\n\n"
                     + "\n".join(lines),
            on_close=lambda p: None,
        )
        if page > 1:
            form.add_button(
                "上一页", ICONS["back"],
                on_click=lambda p: self.show_day_log(p, day, page - 1, category, actor),
            )
        if page < total_pages:
            form.add_button(
                "下一页", ICONS["back"],
                on_click=lambda p: self.show_day_log(p, day, page + 1, category, actor),
            )
        if today:
            form.add_button(
                "刷新", ICONS["refresh"],
                on_click=lambda p: self.show_day_log(p, day, page, category, actor),
            )
        form.add_button(
            "返回分类选择", ICONS["back"],
            on_click=lambda p: self.show_player_categories(p, day, actor),
        )
        player.send_form(form)

    # 数据库查询
    def show_lookup_menu(self, player: Player) -> None:
        if not self._can(player, "lookup_db"):
            player.send_error_message("你没有权限查询数据库日志")
            return
        form = ActionForm(
            title="MxBack 数据库查询",
            content=f"{ColorFormat.GRAY}选择要查询的日志类型：",
            on_close=lambda p: None,
        )
        form.add_button(
            _btn(ColorFormat.GOLD, "方块日志查询", "破坏/放置/爆炸/世界事件等"),
            ICONS["logs"],
            on_click=lambda p: self._show_query_filter(p, "block"),
        )
        form.add_button(
            _btn(ColorFormat.WHITE, "事件日志查询", "聊天/命令/物品/玩家行为等"),
            ICONS["lookup"],
            on_click=lambda p: self._show_query_filter(p, "event"),
        )
        form.add_button(
            "返回日志中心", ICONS["help"],
            on_click=lambda p: self.show_log_center(p),
        )
        player.send_form(form)

    def _show_query_filter(self, player: Player, kind: str) -> None:
        if not self._can(player, "lookup_db"):
            player.send_error_message("你没有权限查询数据库日志")
            return
        labels = (
            BLOCK_QUERY_LABELS if kind == "block" else EVENT_QUERY_LABELS
        )

        def on_submit(p: Player, result: str):
            values = _form_values(result, 3)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            actor = str(values[1]).strip() or None
            self._show_query_results(
                p, kind, int(values[0] or 0), actor, int(values[2] or 0), 1
            )

        form = ModalForm(
            title="查询条件",
            controls=[
                Dropdown("分类", [lab for _, lab in labels]),
                TextInput("玩家名（留空 = 所有人）"),
                Dropdown(
                    "时间范围",
                    [w[0] for w in TIME_WINDOWS],
                    default_index=3,
                ),
            ],
            submit_button="查询",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

    def _show_query_results(
        self, player: Player, kind: str, cat_idx: int,
        actor: str, win_idx: int, page: int,
    ) -> None:
        plugin = self.plugin
        labels = (
            BLOCK_QUERY_LABELS if kind == "block" else EVENT_QUERY_LABELS
        )
        actions_map = (
            BLOCK_QUERY_ACTIONS if kind == "block" else EVENT_QUERY_ACTIONS
        )
        cat_key = labels[_idx(cat_idx, len(labels))][0]
        actions = actions_map[cat_key]
        win_name, window = TIME_WINDOWS[_idx(win_idx, len(TIME_WINDOWS))]
        since_ts = time.time() - window

        def query(pg: int):
            if kind == "block":
                return plugin.db.query_block_log(
                    actions, since_ts, actor, pg, PAGE_SIZE
                )
            return plugin.db.query_events(
                actions, since_ts, actor, pg, PAGE_SIZE
            )

        rows, total = query(page)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        # 页码越界（记录被清理）时回退到末页重查
        if page > total_pages:
            page = total_pages
            rows, total = query(page)
        lang = plugin.lang
        if not rows:
            content = "没有符合条件的记录，试试放宽时间范围或清空玩家名"
        else:
            lines = [f"共 {total} 条 · 第 {page}/{total_pages} 页", ""]
            for row in rows:
                t = datetime.fromtimestamp(row["ts"]).strftime("%m-%d %H:%M:%S")
                action_cn = lang.action_name(row["action"])
                if kind == "block":
                    flag = "（已回档）" if row["rolled_back"] else ""
                    lines.append(
                        f"{t} {row['actor']} {action_cn} "
                        f"{lang.block_name(row['block_type'])}{flag}"
                        f" @ ({row['x']}, {row['y']}, {row['z']})"
                    )
                else:
                    detail = f"：{row['detail']}" if row["detail"] else ""
                    pos = (
                        f" @ ({row['x']}, {row['y']}, {row['z']})"
                        if row["dimension"] != "-" else ""
                    )
                    lines.append(f"{t} {row['actor']} {action_cn}{detail}{pos}")
            content = "\n".join(lines)

        cat_label = labels[_idx(cat_idx, len(labels))][1]
        form = ActionForm(
            title=f"{'方块' if kind == 'block' else '事件'}日志 · {cat_label}",
            content=content,
            on_close=lambda p: None,
        )
        if page > 1:
            form.add_button(
                "上一页", ICONS["back"],
                on_click=lambda p: self._show_query_results(
                    p, kind, cat_idx, actor, win_idx, page - 1
                ),
            )
        if page < total_pages:
            form.add_button(
                "下一页", ICONS["back"],
                on_click=lambda p: self._show_query_results(
                    p, kind, cat_idx, actor, win_idx, page + 1
                ),
            )
        form.add_button(
            "重新查询（改条件）", ICONS["refresh"],
            on_click=lambda p: self._show_query_filter(p, kind),
        )
        form.add_button(
            "返回主菜单", ICONS["help"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    # 配置菜单
    def show_config_menu(self, player: Player) -> None:
        if not self._is_op(player):
            player.send_error_message("只有管理员可以修改配置")
            return
        form = ActionForm(
            title="MxBack 配置文件",
            content=(
                f"{ColorFormat.GRAY}所有配置项均可在此修改，"
                f"保存后立即生效（热重载）并写回 config.json"
            ),
            on_close=lambda p: None,
        )
        form.add_button(
            _btn(ColorFormat.GOLD, "选区设置", "选区工具/体积上限/Y 范围/模式开关"),
            ICONS["selection"],
            on_click=lambda p: self.show_config_selection(p),
        )
        form.add_button(
            _btn(ColorFormat.WHITE, "回档与性能", "单次上限/分批大小/异步落盘"),
            ICONS["performance"],
            on_click=lambda p: self.show_config_rollback(p),
        )
        form.add_button(
            _btn(ColorFormat.YELLOW, "粒子设置", "开关/粒子 ID/间隔/密度/上限"),
            ICONS["particle"],
            on_click=lambda p: self.show_config_particles(p),
        )
        form.add_button(
            _btn(ColorFormat.AQUA, "日志分类开关", "全部分类日志逐一开关"),
            ICONS["category"],
            on_click=lambda p: self.show_config_categories(p),
        )
        form.add_button(
            _btn(ColorFormat.GREEN, "日志文件与压缩", "每日文件/压缩策略/保留天数"),
            ICONS["archive"],
            on_click=lambda p: self.show_config_files(p),
        )
        form.add_button(
            _btn(ColorFormat.MINECOIN_GOLD, "玩家权限",
                 "全局默认 · 单玩家单独设置（以单独为准）"),
            ICONS["access"],
            on_click=lambda p: self.show_perm_menu(p),
        )
        form.add_button(
            _btn(ColorFormat.BLUE, "语言设置", "方块/实体名称翻译语言"),
            ICONS["language"],
            on_click=lambda p: self.show_config_language(p),
        )
        form.add_button(
            "返回主菜单", ICONS["help"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    def show_config_selection(self, player: Player) -> None:
        cfg = self.plugin.cfg

        def on_submit(p: Player, result: str):
            values = _form_values(result, 8)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            wand1 = str(values[0]).strip() or "minecraft:wooden_axe"
            wand2 = str(values[1]).strip() or "minecraft:stick"
            menu_item = str(values[2]).strip() or wand1
            sel = cfg.data.setdefault("selection", {})
            old_vol = int(cfg.get("selection", "max_volume", default=32768))
            old_min = int(cfg.get("selection", "min_y", default=-64))
            old_max = int(cfg.get("selection", "max_y", default=319))
            min_y = _to_int(values[6], old_min)
            max_y = _to_int(values[7], old_max)
            if min_y > max_y:
                min_y, max_y = max_y, min_y
            cfg.data["wand_item"] = wand1
            sel.update({
                "wand_item_2": wand2,
                "menu_open_item": menu_item,
                "require_start": bool(values[3]),
                "ground_click_menu": bool(values[4]),
                "max_volume": _to_int(values[5], old_vol, lo=1),
                "min_y": min_y,
                "max_y": max_y,
            })
            self._save_cfg(p, "选区设置")

        form = ModalForm(
            title="选区设置",
            controls=[
                TextInput(
                    "选区工具（右键依次选择第一/第二点；完成后右键=改第一点）",
                    default_value=str(cfg.get("wand_item", default="minecraft:wooden_axe")),
                ),
                TextInput(
                    "第二点修改工具（选区完成后右键=修改第二点，如木棍）",
                    default_value=str(cfg.get("selection", "wand_item_2", default="minecraft:stick")),
                ),
                TextInput(
                    "打开主菜单的物品（未开启选区模式时右键点击方块打开主菜单，"
                    "配合下方开关使用）",
                    default_value=str(cfg.get("selection", "menu_open_item", default="minecraft:wooden_axe")),
                ),
                Toggle(
                    "需要 /mxback start 开启选区模式后工具才生效",
                    bool(cfg.get("selection", "require_start", default=True)),
                ),
                Toggle(
                    "未开启选区模式时，手持主菜单物品右键点击方块打开主菜单",
                    bool(cfg.get("selection", "ground_click_menu", default=False)),
                ),
                TextInput(
                    "选区最大体积（方块数，防误选过大区域）",
                    default_value=str(cfg.get("selection", "max_volume", default=32768)),
                ),
                TextInput(
                    "选区最小 Y",
                    default_value=str(cfg.get("selection", "min_y", default=-64)),
                ),
                TextInput(
                    "选区最大 Y",
                    default_value=str(cfg.get("selection", "max_y", default=319)),
                ),
            ],
            submit_button="保存并生效",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

    def show_config_rollback(self, player: Player) -> None:
        cfg = self.plugin.cfg

        def on_submit(p: Player, result: str):
            values = _form_values(result, 13)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            rb = cfg.data.setdefault("rollback", {})
            perf = cfg.data.setdefault("performance", {})
            rb["max_records"] = _to_int(
                values[0], int(rb.get("max_records", 5000)), lo=1
            )
            rb["max_time_days"] = _to_int(
                values[1], int(rb.get("max_time_days", 30)), lo=1
            )
            rb["blocks_per_batch"] = _to_int(
                values[2], int(rb.get("blocks_per_batch", 400)), lo=1
            )
            rb["batch_interval_ticks"] = _to_int(
                values[3], int(rb.get("batch_interval_ticks", 1)), lo=1
            )
            perf["async_flush"] = bool(values[4])
            perf["flush_interval_ticks"] = _to_int(
                values[5], int(perf.get("flush_interval_ticks", 100)), lo=1
            )
            rb["cleanup_drops"] = bool(values[6])
            rb["exclude_blocks"] = str(values[7]).strip()
            rb["only_blocks"] = str(values[8]).strip()
            rb["rollback_water"] = bool(values[9])
            rb["rollback_lava"] = bool(values[10])
            rb["auto_teleport"] = bool(values[11])
            rb["teleport_wait_ticks"] = _to_int(
                values[12], int(rb.get("teleport_wait_ticks", 200)), lo=20
            )
            self.plugin._start_flush_task()
            self._save_cfg(p, "回档与性能设置")
            # 后台写线程随服务器启动创建，开关变更需重启才完全生效
            if bool(values[4]) != self.plugin._writer_is_running():
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.YELLOW} "
                    f"异步落盘开关已变更，重启服务器后完全生效"
                )

        form = ModalForm(
            title="回档与性能设置",
            controls=[
                TextInput(
                    "单次回档最多记录条数",
                    default_value=str(cfg.get("rollback", "max_records", default=5000)),
                ),
                TextInput(
                    "回档时间窗最大（天）",
                    default_value=str(cfg.get("rollback", "max_time_days", default=30)),
                ),
                TextInput(
                    "分批回档：每批应用方块数（防止单 tick 卡顿）",
                    default_value=str(cfg.get("rollback", "blocks_per_batch", default=400)),
                ),
                TextInput(
                    "分批回档：批次间隔（tick，1=每 tick 一批）",
                    default_value=str(cfg.get("rollback", "batch_interval_ticks", default=1)),
                ),
                Toggle(
                    "异步落盘（后台线程写数据库，保护 TPS，改动重启后生效）",
                    bool(cfg.get("performance", "async_flush", default=True)),
                ),
                TextInput(
                    "日志落盘间隔（tick，100 = 5 秒）",
                    default_value=str(cfg.get("performance", "flush_interval_ticks", default=100)),
                ),
                Toggle(
                    "回档后清理区域内的残留掉落物（按破坏时指纹匹配，"
                    "宁少清勿误清）",
                    bool(cfg.get("rollback", "cleanup_drops", default=True)),
                ),
                TextInput(
                    "回档排除方块（逗号分隔，如 minecraft:tnt,minecraft:obsidian；"
                    "这些方块不会被回档）",
                    default_value=str(cfg.get("rollback", "exclude_blocks", default="")),
                ),
                TextInput(
                    "仅回档方块（只回档这些方块；与排除互斥，都填以排除为准）",
                    default_value=str(cfg.get("rollback", "only_blocks", default="")),
                ),
                Toggle(
                    "回档水（关闭后水与流水不会被恢复）",
                    bool(cfg.get("rollback", "rollback_water", default=True)),
                ),
                Toggle(
                    "回档岩浆（关闭后岩浆与流岩浆不会被恢复）",
                    bool(cfg.get("rollback", "rollback_lava", default=True)),
                ),
                Toggle(
                    "区块未加载时自动传送（把发起者传送到未加载区块触发加载，"
                    "加载后继续回档）",
                    bool(cfg.get("rollback", "auto_teleport", default=True)),
                ),
                TextInput(
                    "传送后等待区块加载的 tick 上限（20 = 1 秒）",
                    default_value=str(cfg.get("rollback", "teleport_wait_ticks", default=200)),
                ),
            ],
            submit_button="保存并生效",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

    def show_config_particles(self, player: Player) -> None:
        cfg = self.plugin.cfg

        def on_submit(p: Player, result: str):
            values = _form_values(result, 5)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            part = cfg.data.setdefault("particles", {})
            part["enabled"] = bool(values[0])
            ptype = str(values[1]).strip()
            part["type"] = ptype or "minecraft:basic_flame_particle"
            part["interval_ticks"] = _to_int(
                values[2], int(part.get("interval_ticks", 10)), lo=1
            )
            part["density"] = _to_float(
                values[3], float(part.get("density", 0.75)), lo=0.05
            )
            part["max_points"] = _to_int(
                values[4], int(part.get("max_points", 600)), lo=1
            )
            self.plugin._start_particle_task()
            self._save_cfg(p, "粒子设置")

        form = ModalForm(
            title="粒子设置",
            controls=[
                Toggle(
                    "用粒子显示选区边框",
                    bool(cfg.get("particles", "enabled", default=True)),
                ),
                TextInput(
                    "粒子 ID（基岩版粒子标识，如 minecraft:basic_flame_particle）",
                    default_value=str(cfg.get("particles", "type", default="minecraft:basic_flame_particle")),
                ),
                TextInput(
                    "粒子刷新间隔（tick，10 = 0.5 秒）",
                    default_value=str(cfg.get("particles", "interval_ticks", default=10)),
                ),
                TextInput(
                    "边框粒子密度（每多少格一个点，越小越密）",
                    default_value=str(cfg.get("particles", "density", default=0.75)),
                ),
                TextInput(
                    "单次刷新粒子总数上限",
                    default_value=str(cfg.get("particles", "max_points", default=600)),
                ),
            ],
            submit_button="保存并生效",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

    def show_config_categories(self, player: Player) -> None:
        cfg = self.plugin.cfg
        cats = cfg.get("logs", "categories", default={})

        def on_submit(p: Player, result: str):
            values = _form_values(result, 1)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            data = cfg.data.setdefault("logs", {}).setdefault("categories", {})
            for i, (key, _) in enumerate(LOG_CATEGORY_TOGGLES):
                if i < len(values):
                    data[key] = bool(values[i])
            self._save_cfg(p, "日志分类开关")

        form = ModalForm(
            title="日志分类开关",
            controls=[
                Toggle(label, bool(cats.get(key, False)))
                for key, label in LOG_CATEGORY_TOGGLES
            ],
            submit_button="保存并生效",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

    def show_config_files(self, player: Player) -> None:
        cfg = self.plugin.cfg
        strategies = ["auto", "gzip", "bz2", "xz"]
        cur_strategy = str(cfg.get("logs", "strategy", default="auto"))
        try:
            strat_idx = strategies.index(cur_strategy)
        except ValueError:
            strat_idx = 0

        def on_submit(p: Player, result: str):
            values = _form_values(result, 6)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            logs = cfg.data.setdefault("logs", {})
            logs["daily_files"] = bool(values[0])
            logs["auto_compress"] = bool(values[1])
            idx = int(values[2]) if isinstance(values[2], (int, float)) else 0
            logs["strategy"] = strategies[max(0, min(idx, len(strategies) - 1))]
            logs["compress_hour"] = _to_int(
                values[3], int(logs.get("compress_hour", 4)), lo=0, hi=23
            )
            logs["auto_gzip_days"] = _to_int(
                values[4], int(logs.get("auto_gzip_days", 7)), lo=0
            )
            logs["keep_archives_days"] = _to_int(
                values[5], int(logs.get("keep_archives_days", 0)), lo=0
            )
            self._save_cfg(p, "日志文件与压缩设置")

        form = ModalForm(
            title="日志文件与压缩",
            controls=[
                Toggle(
                    "生成每日分类日志文件（人类可读中文文本）",
                    bool(cfg.get("logs", "daily_files", default=True)),
                ),
                Toggle(
                    "每日自动压缩旧日志",
                    bool(cfg.get("logs", "auto_compress", default=True)),
                ),
                Dropdown(
                    "压缩策略（auto=近期gzip/更早xz 极限压缩）",
                    strategies,
                    default_index=strat_idx,
                ),
                TextInput(
                    "自动压缩触发小时（0-23，服务器本地时间）",
                    default_value=str(cfg.get("logs", "compress_hour", default=4)),
                ),
                TextInput(
                    "auto 策略：N 天内用 gzip（超出用 xz）",
                    default_value=str(cfg.get("logs", "auto_gzip_days", default=7)),
                ),
                TextInput(
                    "压缩包保留天数（0 = 永久保留）",
                    default_value=str(cfg.get("logs", "keep_archives_days", default=0)),
                ),
            ],
            submit_button="保存并生效",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

    # 权限管理（OP）：全局默认 + 单玩家设置
    def show_perm_menu(self, player: Player) -> None:
        if not self._is_op(player):
            player.send_error_message("只有管理员可以管理玩家权限")
            return
        plugin = self.plugin
        perms = plugin.permissions
        online: list[str] = []
        try:
            for p in plugin.server.online_players:
                if not bool(p.is_op):
                    online.append(p.name)
            online.sort()
        except Exception:
            online = []
        overridden = perms.overridden_players()
        # 列表：有单独设置的玩家 + 在线普通玩家
        listed = list(overridden)
        for name in online:
            if name not in listed:
                listed.append(name)
        form = ActionForm(
            title="MxBack 权限管理",
            content="\n".join([
                f"{ColorFormat.BOLD}{ColorFormat.GOLD}【 玩家权限管理 】"
                f"{ColorFormat.RESET}",
                f"{ColorFormat.GRAY}判定规则：玩家单独设置 > 全局默认；",
                f"{ColorFormat.GRAY}未单独设置的项跟随全局默认，OP 恒为允许。",
                f"{ColorFormat.GRAY}点击玩家进入单独设置；「全局默认」作用于",
                f"{ColorFormat.GRAY}所有未单独设置的普通玩家。",
            ]),
            on_close=lambda p: None,
        )
        form.add_button(
            _btn(ColorFormat.MATERIAL_GOLD, "全局默认权限",
                 "所有普通玩家的默认权限（config.json）"),
            ICONS["global"],
            on_click=lambda p: self.show_perm_defaults(p),
        )
        for name in listed:
            n_ov = len(perms.players.get(name, {}))
            desc = f"单独设置 {n_ov} 项 · 点击修改" if n_ov else "跟随全局 · 点击单独设置"
            form.add_button(
                f"{name}\n{ColorFormat.GRAY}{desc}",
                ICONS["player"],
                on_click=lambda p, n=name: self.show_player_perms(p, n),
            )
            if n_ov:
                form.add_button(
                    f"{name}\n{ColorFormat.RED}清除全部单独设置（恢复跟随全局）",
                    ICONS["refresh"],
                    on_click=lambda p, n=name: self._confirm_clear_perms(p, n),
                )
        form.add_button(
            _btn(ColorFormat.GRAY, "按名字添加玩家", "输入玩家名设置单独权限"),
            ICONS["search"],
            on_click=lambda p: self._prompt_perm_player(p),
        )
        form.add_button(
            "返回主菜单", ICONS["back"],
            on_click=lambda p: self.show_main_menu(p),
        )
        player.send_form(form)

    def _prompt_perm_player(self, player: Player) -> None:
        def on_submit(p: Player, result: str):
            values = _form_values(result, 1)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            name = str(values[0]).strip()
            if not name:
                self.show_perm_menu(p)
                return
            self.show_player_perms(p, name)

        form = ModalForm(
            title="按名字添加玩家",
            controls=[
                TextInput(
                    "玩家名（不区分大小写，离线玩家亦可）",
                    placeholder="如 Steve",
                ),
            ],
            submit_button="进入权限设置",
            on_submit=on_submit,
            on_close=lambda p: self.show_perm_menu(p),
        )
        player.send_form(form)

    def show_perm_defaults(self, player: Player) -> None:
        """全局默认权限：写 config.json player_permissions。"""
        if not self._is_op(player):
            player.send_error_message("只有管理员可以管理玩家权限")
            return
        cfg = self.plugin.cfg
        data = cfg.data.setdefault("player_permissions", {})

        def on_submit(p: Player, result: str):
            values = _form_values(result, len(PERM_KEYS))
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            for i, key in enumerate(PERM_KEYS):
                data[key] = bool(values[i])
            self._save_cfg(p, "全局默认权限")

        form = ModalForm(
            title="全局默认权限（普通玩家）",
            controls=[
                Toggle(
                    f"{name} — {desc}"
                    if desc else name,
                    bool(data.get(key, False)),
                )
                for key, name, desc in PERMISSION_ITEMS
            ],
            submit_button="保存并生效",
            on_submit=on_submit,
            on_close=lambda p: self.show_perm_menu(p),
        )
        player.send_form(form)

    def show_player_perms(self, player: Player, target: str) -> None:
        """单玩家权限：仅记录与生效值不同的项为单独设置。"""
        if not self._is_op(player):
            player.send_error_message("只有管理员可以管理玩家权限")
            return
        plugin = self.plugin
        perms = plugin.permissions
        effective = perms.effective(target)
        overrides = perms.players.get(target, {})
        # ModalForm 无 content 参数：当前状态先发聊天消息
        name_of = {k: n for k, n, _ in PERMISSION_ITEMS}
        on_off = {
            True: f"{ColorFormat.GREEN}允许", False: f"{ColorFormat.RED}拒绝",
        }
        lines = [f"{ColorFormat.GOLD}【 {target} 当前权限 】"]
        lines.append(
            f"{ColorFormat.GRAY}提交时：仅与当前生效值不同的项会记为单独设置；"
            f"未单独设置的项跟随全局默认"
        )
        for k in PERM_KEYS:
            tag = "（单独设置）" if k in overrides else ""
            lines.append(
                f"{ColorFormat.WHITE}· {name_of[k]}："
                f"{on_off[effective[k]]}{ColorFormat.GRAY}{tag}"
            )
        player.send_message("\n".join(lines))

        def on_submit(p: Player, result: str):
            values = _form_values(result, len(PERM_KEYS))
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            changed = 0
            for i, key in enumerate(PERM_KEYS):
                new = bool(values[i])
                if new != effective[key]:
                    # 与提交前生效值不同 → 记为单独设置（以单独为准）
                    perms.set_override(target, key, new)
                    changed += 1
            p.play_sound(p.location, "random.orb")
            if changed:
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
                    f"{target} 的单独权限已保存（{changed} 项），立即生效"
                )
            else:
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                    f"{target} 的权限无变化（与提交前生效值相同），"
                    f"未产生新的单独设置"
                )
            self.show_player_perms(p, target)

        form = ModalForm(
            title=f"单独权限 · {target}",
            controls=[
                Toggle(f"{name} — {desc}", effective[key])
                for key, name, desc in PERMISSION_ITEMS
            ],
            submit_button="保存单独设置",
            on_submit=on_submit,
            on_close=lambda p: self.show_perm_menu(p),
        )
        player.send_form(form)

    def _confirm_clear_perms(self, player: Player, target: str) -> None:
        plugin = self.plugin

        def on_submit(p: Player, result: str):
            values = _form_values(result, 1)
            if values is None or not values[0]:
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GRAY} 已取消清除"
                )
                return
            if plugin.permissions.clear_player(target):
                p.play_sound(p.location, "random.orb")
                p.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GREEN} "
                    f"已清除 {target} 的全部单独设置，恢复跟随全局默认"
                )
            self.show_perm_menu(p)

        n = len(plugin.permissions.players.get(target, {}))
        form = ModalForm(
            title=f"清除 {target} 的单独设置？",
            controls=[
                Toggle(
                    f"确认清除（共 {n} 项单独设置，之后跟随全局默认）",
                    False,
                ),
            ],
            submit_button="确认清除",
            on_submit=on_submit,
            on_close=lambda p: self.show_perm_menu(p),
        )
        player.send_form(form)

    def show_config_language(self, player: Player) -> None:
        cfg = self.plugin.cfg

        def on_submit(p: Player, result: str):
            values = _form_values(result, 1)
            if values is None:
                p.send_error_message("表单数据解析失败")
                return
            locale = str(values[0]).strip() or "zh_CN"
            cfg.data["language"] = locale
            self.plugin.lang = Lang(self.plugin)
            self._save_cfg(p, "语言设置")

        form = ModalForm(
            title="语言设置",
            controls=[
                TextInput(
                    "服务器端翻译语言（如 zh_CN / en_US / ja_JP）",
                    default_value=str(cfg.get("language", default="zh_CN")),
                ),
            ],
            submit_button="保存并生效",
            on_submit=on_submit,
            on_close=lambda p: None,
        )
        player.send_form(form)

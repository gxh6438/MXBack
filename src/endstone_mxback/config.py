"""配置管理：JSON 配置文件的加载、深合并与保存。"""

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "language": "zh_CN",
    "wand_item": "minecraft:wooden_axe",
    "selection": {
        "wand_item_2": "minecraft:stick",
        "require_start": True,       # 须先 /mxback start 工具才生效
        "ground_click_menu": False, # 未开启选区模式时主菜单物品右键开菜单
        "menu_open_item": "minecraft:wooden_axe",
        "max_volume": 32768,
        "min_y": -64,
        "max_y": 319,
    },
    "rollback": {
        "max_records": 5000,
        "max_time_days": 30,
        "blocks_per_batch": 400,     # 单批方块数（防单 tick 卡顿）
        "batch_interval_ticks": 1,
        "cleanup_drops": True,
        "drop_verify_type": True,   # <0.11.8 有物品堆读取缺陷时自动关闭
        "rollback_water": True,
        "rollback_lava": True,
        "exclude_blocks": "",
        "only_blocks": "",
        # 区块未加载时把发起者传送到目标区块触发加载，加载后继续回档
        "auto_teleport": True,
        "teleport_wait_ticks": 200,  # 每次传送后等待区块加载的 tick 上限
    },
    "performance": {
        "async_flush": True,        # 后台线程写库，重启后生效
        "flush_interval_ticks": 100,
    },
    "database": {
        "archive_compress": True,
        "archive_algorithm": "gzip",
    },
    "particles": {
        "enabled": True,
        "interval_ticks": 10,
        "type": "minecraft:basic_flame_particle",
        "density": 0.75,
        "max_points": 600,
    },
    "logs": {
        "categories": {
            # 方块事件（可回档）
            "block_break": True,
            "block_place": True,
            "explosion": True,
            "leaves_decay": False,
            "block_grow": False,
            "block_form": True,
            "liquid_flow": True,
            # 玩家行为（仅查询）
            "container_open": True,
            "click": False,
            "entity_interact": False,
            "bone_meal": True,
            "chat": True,
            "command": True,
            "session": True,
            "kill": True,
            "item_drop": True,
            "item_pickup": True,
            "item_consume": False,
            "gamemode": False,
            "teleport": False,
            "bed": False,
            # 世界事件（仅查询）
            "piston": False,
            "block_cook": False,
            "weather": False,
            "broadcast": False,
            # 服务器管理
            "plugin": True,
            # 玩家杂项
            "dimension": False,
            "respawn": False,
            "emote": False,
        },
        "daily_files": True,
        "per_player_files": True,
        "auto_compress": True,
        "compress_hour": 4,
        "strategy": "auto",   # gzip / bz2 / xz / auto（近期gzip、更早xz）
        "auto_gzip_days": 7,
        "keep_archives_days": 0,
    },
    # 普通玩家（非 OP）权限全局默认；单玩家覆盖见 permissions.json
    "player_permissions": {
        "selection": False,
        "rollback": False,
        "selection_lookup": False,
        "undo": False,
        "undo_others": False,
        "history": False,
        "lookup_files": False,
        "lookup_db": False,
        "status": False,
    },
    # 容器交互日志识别用；容器内容因 API 限制无法记录与恢复
    "containers": [
        "minecraft:chest",
        "minecraft:trapped_chest",
        "minecraft:barrel",
        "minecraft:furnace",
        "minecraft:lit_furnace",
        "minecraft:blast_furnace",
        "minecraft:lit_blast_furnace",
        "minecraft:smoker",
        "minecraft:lit_smoker",
        "minecraft:dispenser",
        "minecraft:dropper",
        "minecraft:hopper",
        "minecraft:brewing_stand",
        "minecraft:shulker_box",
        "minecraft:undyed_shulker_box",
        "minecraft:ender_chest",
        "minecraft:beacon",
        "minecraft:campfire",
        "minecraft:soul_campfire",
        "minecraft:lectern",
        "minecraft:decorated_pot",
    ],
}


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 覆盖 base，缺失键沿用默认值。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigManager:
    """data_folder/config.json 的读取与保存。"""

    def __init__(self, data_folder: str):
        self.path = Path(data_folder) / "config.json"
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.data = copy.deepcopy(DEFAULT_CONFIG)
            self.save()
            return
        try:
            user_cfg = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise RuntimeError(f"配置文件解析失败: {e}") from e
        self.data = deep_merge(DEFAULT_CONFIG, user_cfg)

    def save(self) -> None:
        # 原子写入：写临时文件后替换，避免写一半断电产生损坏的配置
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def get(self, *keys: str, default=None):
        node: Any = self.data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

"""玩家权限管理：全局默认（config.json）+ 单玩家覆盖（permissions.json）。

判定优先级：玩家单独设置 > 全局默认；未单独设置的项沿用全局默认。
OP / 控制台不经过本模块（命令与表单层恒为允许）。
"""

import json
from pathlib import Path

# 权限目录：(键, 名称, 说明)；顺序即表单展示顺序
PERMISSION_ITEMS = [
    ("selection", "选区模式", "选区工具选点与粒子边框（/mxback start、stop）"),
    ("rollback", "选区回档", "对已选区域执行方块回档"),
    ("selection_lookup", "选区日志查询", "查看选区内的方块变更记录"),
    ("undo", "撤销自己的回档", "/mxback undo 撤销自己的回档会话"),
    ("undo_others", "撤销他人的回档", "普通玩家额外授权：可撤销任何人的回档"),
    ("history", "查看回档记录", "/mxback history 回档历史列表"),
    ("lookup_files", "日志文件浏览", "按日期/玩家/分类浏览每日日志文件"),
    ("lookup_db", "数据库查询", "按分类/玩家/时间窗查询数据库记录"),
    ("status", "运行状态", "/mxback status 运行统计"),
]

PERM_KEYS = tuple(k for k, _, _ in PERMISSION_ITEMS)


class PermissionManager:
    """玩家权限：单玩家覆盖优先，缺省项回落全局默认。"""

    def __init__(self, data_folder: str, cfg):
        self.cfg = cfg
        self.path = Path(data_folder) / "permissions.json"
        # {"Steve": {"rollback": True, ...}, ...}
        self.players: dict[str, dict[str, bool]] = {}
        self.load()

    # ------------------------------------------------------------- 持久化
    def load(self) -> None:
        self.players = {}
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return  # 损坏时按空处理，不挡插件启动
        raw = data.get("players") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            return
        for name, overrides in raw.items():
            if not isinstance(overrides, dict):
                continue
            clean = {
                k: bool(v)
                for k, v in overrides.items()
                if k in PERM_KEYS
            }
            if clean:
                self.players[str(name)] = clean

    def save(self) -> None:
        # 原子写入：写临时文件后替换
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {"players": self.players},
                    ensure_ascii=False, indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except OSError:
            pass  # 只影响跨重启持久化，当前运行期判定不受影响

    # ------------------------------------------------------------- 判定
    def default(self, key: str) -> bool:
        """全局默认值（config.json player_permissions）。"""
        return bool(self.cfg.get("player_permissions", key, default=False))

    def has(self, name: str, key: str) -> bool:
        """玩家生效权限：单独设置优先，缺省回落全局默认。"""
        if key not in PERM_KEYS:
            return False
        overrides = self.players.get(name)
        if overrides is not None and key in overrides:
            return bool(overrides[key])
        return self.default(key)

    def override(self, name: str, key: str):
        """单独设置值；None 表示该项未单独设置（跟随全局）。"""
        overrides = self.players.get(name)
        if overrides is not None and key in overrides:
            return bool(overrides[key])
        return None

    def effective(self, name: str) -> dict[str, bool]:
        """玩家全部权限的生效值（用于表单展示）。"""
        return {k: self.has(name, k) for k in PERM_KEYS}

    # ------------------------------------------------------------- 修改
    def set_override(self, name: str, key: str, value: bool) -> None:
        if key not in PERM_KEYS:
            return
        self.players.setdefault(name, {})[key] = bool(value)
        self.save()

    def clear_override(self, name: str, key: str) -> None:
        """清除单项单独设置（该项回到跟随全局）。"""
        overrides = self.players.get(name)
        if overrides is None or key not in overrides:
            return
        del overrides[key]
        if not overrides:
            self.players.pop(name, None)
        self.save()

    def clear_player(self, name: str) -> bool:
        """清除该玩家全部单独设置；有设置返回 True。"""
        if name not in self.players:
            return False
        del self.players[name]
        self.save()
        return True

    def overridden_players(self) -> list[str]:
        """存在单独设置的玩家名列表。"""
        return sorted(self.players.keys())

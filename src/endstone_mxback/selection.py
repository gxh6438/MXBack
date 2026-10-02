"""选区管理 + 粒子边框渲染（仅选区本人可见）。"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple

Pos = Tuple[int, int, int]


@dataclass
class Selection:
    pos1: Optional[Pos] = None
    pos2: Optional[Pos] = None
    dimension: str = ""

    def bounds(self) -> Optional[Tuple[Pos, Pos]]:
        """规范化后的 (最小角, 最大角)；两点齐全才有值。"""
        if self.pos1 is None or self.pos2 is None:
            return None
        return (
            (min(self.pos1[0], self.pos2[0]), min(self.pos1[1], self.pos2[1]),
             min(self.pos1[2], self.pos2[2])),
            (max(self.pos1[0], self.pos2[0]), max(self.pos1[1], self.pos2[1]),
             max(self.pos1[2], self.pos2[2])),
        )

    def volume(self) -> int:
        b = self.bounds()
        if b is None:
            return 0
        (x1, y1, z1), (x2, y2, z2) = b
        return (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1)

    def complete(self) -> bool:
        return self.pos1 is not None and self.pos2 is not None


# 立方体 12 条边：(角点A, 角点B)，A、B 用 (dx, dy, dz) ∈ {0,1}^3 表示
_EDGES = [
    ((0, 0, 0), (1, 0, 0)), ((0, 1, 0), (1, 1, 0)),
    ((0, 0, 1), (1, 0, 1)), ((0, 1, 1), (1, 1, 1)),
    ((0, 0, 0), (0, 1, 0)), ((1, 0, 0), (1, 1, 0)),
    ((0, 0, 1), (0, 1, 1)), ((1, 0, 1), (1, 1, 1)),
    ((0, 0, 0), (0, 0, 1)), ((1, 0, 0), (1, 0, 1)),
    ((0, 1, 0), (0, 1, 1)), ((1, 1, 0), (1, 1, 1)),
]


class SelectionManager:
    """按玩家名维护选区状态，并用粒子渲染选区边框。"""

    def __init__(self, plugin):
        self.plugin = plugin
        self.selections: dict[str, Selection] = {}

    def select_point(self, player, x: int, y: int, z: int, which: int) -> Selection:
        """which=1 设置第一个点，which=2 设置第二个点；跨维度时重置选区。"""
        sel = self.selections.get(player.name)
        if sel is None or sel.dimension != player.dimension.name:
            sel = Selection()
            sel.dimension = player.dimension.name
            self.selections[player.name] = sel
        if which == 1:
            sel.pos1 = (x, y, z)
        else:
            sel.pos2 = (x, y, z)
        return sel

    def get(self, player_name: str) -> Optional[Selection]:
        return self.selections.get(player_name)

    def clear(self, player_name: str) -> None:
        self.selections.pop(player_name, None)

    def volume_exceeds(self, sel: Selection, max_volume: int) -> bool:
        return sel.complete() and sel.volume() > max_volume

    def render_all(self) -> None:
        """给所有已完整选区的玩家刷新粒子边框（定时任务调用）。"""
        # 关服窗口：get_player 会踩已析构的 Level 句柄（SIGSEGV 不可捕获）
        if self.plugin._stopping:
            return
        cfg = self.plugin.cfg
        if not cfg.get("particles", "enabled", default=True):
            return
        ptype = cfg.get("particles", "type", default="minecraft:basic_flame_particle")
        for name, sel in self.selections.items():
            if not sel.complete():
                continue
            player = self.plugin.server.get_player(name)
            if player is not None:
                self._render_for(player, sel, ptype)

    def _render_for(self, player, sel: Selection, ptype: str) -> None:
        cfg = self.plugin.cfg
        density = float(cfg.get("particles", "density", default=0.75))
        max_points = int(cfg.get("particles", "max_points", default=600))
        (x1, y1, z1), (x2, y2, z2) = sel.bounds()

        # 按需加大步距，保证单次刷新粒子数不超上限
        total = self._edge_points_count(x1, y1, z1, x2, y2, z2, density)
        if total > max_points and total > 0:
            density *= total / max_points

        for (a, b) in _EDGES:
            ax = x1 + a[0] * (x2 - x1)
            ay = y1 + a[1] * (y2 - y1)
            az = z1 + a[2] * (z2 - z1)
            bx = x1 + b[0] * (x2 - x1)
            by = y1 + b[1] * (y2 - y1)
            bz = z1 + b[2] * (z2 - z1)
            steps = max(1, math.ceil(math.dist((ax, ay, az), (bx, by, bz)) / density))
            for i in range(steps + 1):
                t = i / steps
                player.spawn_particle(
                    ptype,
                    ax + (bx - ax) * t,
                    ay + (by - ay) * t + 0.5,  # 方块中心高度更醒目
                    az + (bz - az) * t,
                )

    @staticmethod
    def _edge_points_count(x1, y1, z1, x2, y2, z2, density: float) -> int:
        dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
        edges_len = [dx] * 4 + [dy] * 4 + [dz] * 4
        return sum(int(l / density) + 1 if l > 0 else 1 for l in edges_len)

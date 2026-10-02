"""事件监听：方块/世界/玩家行为日志、选区工具。

方块事件（可回档）: break / place / explode / leaves_decay /
    block_grow / block_form / liquid_flow
世界事件（仅查询）: piston / block_cook / weather / plugin 启停
玩家行为（仅查询）: container_open / click / entity_interact / chat /
    command / join / quit / kick / kill / item_* / gamemode / teleport /
    bed / dimension / respawn / emote / broadcast

PlayerMoveEvent 等高频事件刻意排除，避免每 tick 刷记录拖垮 TPS。
"""

import json
import time
from typing import Optional

from endstone import ColorFormat, Player
from endstone.actor import Actor
from endstone.block import BlockFace
from endstone.event import (
    ActorDeathEvent,
    ActorExplodeEvent,
    BlockBreakEvent,
    BlockCookEvent,
    BlockExplodeEvent,
    BlockFormEvent,
    BlockFromToEvent,
    BlockGrowEvent,
    BlockPistonExtendEvent,
    BlockPistonRetractEvent,
    BlockPlaceEvent,
    BroadcastMessageEvent,
    LeavesDecayEvent,
    PlayerBedEnterEvent,
    PlayerBedLeaveEvent,
    PlayerChatEvent,
    PlayerCommandEvent,
    PlayerDeathEvent,
    PlayerDimensionChangeEvent,
    PlayerDropItemEvent,
    PlayerEmoteEvent,
    PlayerGameModeChangeEvent,
    PlayerInteractActorEvent,
    PlayerInteractEvent,
    PlayerItemConsumeEvent,
    PlayerKickEvent,
    PlayerJoinEvent,
    PlayerPickupItemEvent,
    PlayerQuitEvent,
    PlayerRespawnEvent,
    PlayerTeleportEvent,
    PluginDisableEvent,
    PluginEnableEvent,
    ServerCommandEvent,
    ThunderChangeEvent,
    WeatherChangeEvent,
    event_handler,
)

from .database import states_to_json

# 动作 -> 配置开关 key
_ACTION_CATEGORY = {
    "break": "block_break",
    "place": "block_place",
    "explode": "explosion",
    "leaves_decay": "leaves_decay",
    "block_grow": "block_grow",
    "block_form": "block_form",
    "liquid_flow": "liquid_flow",
    "piston": "piston",
    "block_cook": "block_cook",
    "container_open": "container_open",
    "click": "click",
    "entity_interact": "entity_interact",
    "chat": "chat",
    "command": "command",
    "broadcast": "broadcast",
    "plugin_enable": "plugin",
    "plugin_disable": "plugin",
    "join": "session",
    "quit": "session",
    "kick": "session",
    "kill": "kill",
    "entity_kill": "kill",
    "item_drop": "item_drop",
    "item_pickup": "item_pickup",
    "item_consume": "item_consume",
    "gamemode": "gamemode",
    "teleport": "teleport",
    "bed_enter": "bed",
    "bed_leave": "bed",
    "dimension_change": "dimension",
    "respawn": "respawn",
    "emote": "emote",
    "weather": "weather",
    "thunder": "weather",
}

# 可点击交互方块的 ID 关键词（门/按钮/拉杆等，click 分类）
_CLICK_KEYWORDS = (
    "door", "gate", "button", "lever", "trapdoor", "bed", "bell",
    "daylight_detector", "repeater", "comparator", "jukebox",
    "note_block", "dragon_egg", "respawn_anchor", "cake", "flower_pot",
)


def _normalize_liquid(block_id: str) -> str:
    """液体规范化：BDS 内部 flowing_ 前缀 -> 标准 ID（回档放置需要）。"""
    if block_id == "minecraft:flowing_water":
        return "minecraft:water"
    if block_id == "minecraft:flowing_lava":
        return "minecraft:lava"
    return block_id


# 桶物品 -> 放置的液体。水源/岩浆源头必须记录：Endstone 无桶事件，
# 不记录则回档会误把"堵住水源的方块"的替换前状态（水）当作目标恢复，
# 导致水复活且重新灌满
_BUCKET_LIQUIDS = {
    "minecraft:water_bucket": "minecraft:water",
    "minecraft:lava_bucket": "minecraft:lava",
    "minecraft:powder_snow_bucket": "minecraft:powder_snow",
}

_SCOOPABLE = (
    "minecraft:water", "minecraft:lava",
    "minecraft:flowing_water", "minecraft:flowing_lava",
    "minecraft:powder_snow",
)

_FACE_OFFSETS = {
    BlockFace.DOWN: (0, -1, 0),
    BlockFace.UP: (0, 1, 0),
    BlockFace.NORTH: (0, 0, -1),
    BlockFace.SOUTH: (0, 0, 1),
    BlockFace.WEST: (-1, 0, 0),
    BlockFace.EAST: (1, 0, 0),
}

_ITEM_ENTITY_TYPE = "minecraft:item"
_BONE_MEAL = "minecraft:bone_meal"

# 待验证任务上限：防恶意连点骨粉/桶造成快照内存堆积
_MAX_PENDING_TASKS = 64

# 桶 BlockPlaceEvent 守卫窗口（秒）：放置事件与桶交互同 tick 触发，
# 窗口只需覆盖调度抖动；过大会误跳过同位置的普通放置
_BUCKET_GUARD_WINDOW = 0.3

# 海绵吸水（无事件，快照对比兜底）：半径 7，吸除后周边流水渐进排空
# （约 5 tick/格，最远 7 格），首查后再复核一轮
_SPONGE_RADIUS = 7
_SPONGE_VERIFY_DELAY = 45
_SPONGE_RECHECK_DELAY = 45

# 可直接判定含水的白名单（BDS 对可含水方块倒水桶 = 灌入层 1，无事件
# 且层 0 状态不变）。仅收录"无右键交互"的可含水方块：有右键交互的
# 方块（栅栏门/告示牌/箱子等）水桶右键时交互优先于倒水，直接判定会
# 误报，而误报会让回档流水线对容器置 air 丢失内容，宁可漏给观察法兜底。
# 双层台阶是完整方块不可含水；地毯基岩版不可含水，均不收录
_WATERLOG_SAFE_SUFFIXES = (
    "_stairs", "_slab", "_fence", "_wall", "_leaves", "_banner",
    "_head", "_skull", "_pressure_plate",
)
_WATERLOG_SAFE_EXACT = frozenset((
    "leaves", "leaves2",
    "glass_pane", "iron_bars", "chain", "lantern", "soul_lantern",
    "bamboo", "sea_pickle", "end_rod", "lightning_rod",
    "tripwire", "tripwire_hook", "vine", "twisting_vines",
    "weeping_vines", "hanging_roots", "spore_blossom",
    "small_dripleaf", "mangrove_propagule",
))


def _is_waterlog_safe(btype: str) -> bool:
    """方块是否在"可直接判定含水"白名单（无右键交互的可含水方块）。"""
    name = btype.split(":", 1)[-1]
    if name.startswith("double_") and name.endswith("_slab"):
        return False
    return (
        name in _WATERLOG_SAFE_EXACT
        or name.endswith(_WATERLOG_SAFE_SUFFIXES)
    )


def _item_fingerprint(actor: Actor) -> Optional[tuple]:
    """掉落物实体 -> (物品ID, 数量)；非掉落物或已失效返回 None。

    is_valid 校验必须先行：对被合并/拾取/移除的实体继续操作是已知
    崩溃向量。
    """
    try:
        if actor.type != _ITEM_ENTITY_TYPE:
            return None
        if not actor.is_valid():
            return None
        item = actor.item_stack
        return (item.type.id, item.amount)
    except Exception:
        return None


def _loaded_chunks(dim) -> Optional[set]:
    """当前已加载区块坐标集合；API 不可用返回 None（调用方跳过检查）。

    延迟回调里 get_block_at 对未加载区块返回悬空引用，读取即段错误，
    必须现场复查（延迟窗口内区块可能被卸载）。
    """
    try:
        return {(c.x, c.z) for c in dim.loaded_chunks}
    except Exception:
        return None


def _chunk_ok(loaded: Optional[set], x: int, z: int) -> bool:
    return loaded is None or (x >> 4, z >> 4) in loaded


class Listeners:
    """统一注册到插件的监听器。"""

    def __init__(self, plugin):
        self.plugin = plugin
        # 交互去重：玩家 -> (坐标, 动作, 时间戳)
        self._last_interact: dict[str, tuple] = {}
        # 玩家最近一次安全读取的位置快照：join/quit/kick/respawn 等
        # 过渡窗口事件里绝不读 player.location/dimension——入服/离服/
        # 重生瞬间可能踩到未就绪或悬空的 WeakRef<Dimension>，SIGSEGV
        # 不可捕获（0.11.12 实测）。这些事件改用快照记日志
        self._last_seen: dict[str, tuple[int, int, int, str]] = {}
        # 已完成入服的玩家集合（join 起、quit 止）。登录窗口里 BDS
        # 恢复存档游戏模式会早于 join 触发 GameModeChangeEvent，此时
        # 读 player.location 必段错误（0.5.6 实测）；可能落在危险窗口
        # 的事件（gamemode/dimension_change/respawn）以此判定能否
        # 触碰 player 本体
        self._spawned: set[str] = set()
        self._pending_buckets: set[tuple] = set()
        # 桶触发的 BlockPlaceEvent 守卫：(玩家, x, y, z) -> 时间。
        # BDS 水桶倒向可含水方块触发的放置事件里 block_placed_state
        # 指向动态构造的 permutation，读取 .type/.data 解引用已失效的
        # 方块对象直接 SIGSEGV（-11 无日志）。命中守卫直接跳过，
        # 记录由桶的延迟验证兜底
        self._bucket_event_guard: dict[tuple, float] = {}
        self._pending_sponges: set[tuple] = set()
        # 掉落物扫描邻域去重：条目过多整体重置（只影响 1 秒去重窗口）
        self._last_drop_scan: dict[tuple, float] = {}

    # ------------------------------------------------------------------
    # 方块事件（可回档）
    # ------------------------------------------------------------------
    @event_handler
    def on_block_break(self, event: BlockBreakEvent):
        if event.is_cancelled:
            return
        if not self._enabled("break"):
            return
        block = event.block
        self.plugin.record(
            action="break",
            actor=event.player.name,
            block_type=block.type,
            block_states=states_to_json(block.data.block_states),
            x=block.x, y=block.y, z=block.z,
            dimension=block.dimension.name,
        )
        self._collect_drop_fingerprint(
            block.x, block.y, block.z, block.dimension.name, event.player.name
        )

    @event_handler
    def on_block_place(self, event: BlockPlaceEvent):
        if event.is_cancelled:
            return
        placed = event.block_placed_state
        # 守卫必须先于一切对 block_placed_state 的 .type/.data 读取
        #（桶-含水场景下是崩服向量；x/y/z 是自身成员，读取安全）
        g = self._bucket_event_guard.get(
            (event.player.name, placed.x, placed.y, placed.z)
        )
        if g is not None and time.monotonic() - g < _BUCKET_GUARD_WINDOW:
            return
        # 海绵吸水（无事件，快照对比兜底）：置于 place 门控之前——
        # 被吸的水记 break 类别，即便关闭放置日志吸水破坏仍可回档。
        # 湿海绵不吸水；海绵放置无含水 permutation，type 读取安全
        if placed.type == "minecraft:sponge":
            self._schedule_sponge_absorb(
                event.player, placed.x, placed.y, placed.z
            )
        if not self._enabled("place"):
            return
        replaced = event.block_replaced
        replaced_type = replaced.type if replaced is not None else "minecraft:air"
        replaced_states = (
            states_to_json(replaced.data.block_states)
            if replaced is not None else "{}"
        )
        self.plugin.record(
            action="place",
            actor=event.player.name,
            block_type=placed.type,
            block_states=states_to_json(placed.data.block_states),
            replaced_type=replaced_type,
            replaced_states=replaced_states,
            x=placed.x, y=placed.y, z=placed.z,
            dimension=event.player.dimension.name,
        )

    def _record_explode(self, blocks, actor: str) -> None:
        first = blocks[0] if blocks else None
        for block in blocks:
            self.plugin.record(
                action="explode",
                actor=actor,
                block_type=block.type,
                block_states=states_to_json(block.data.block_states),
                x=block.x, y=block.y, z=block.z,
                dimension=block.dimension.name,
            )
        # 掉落物指纹：以首个被炸方块为中心采集一次（邻域去重合并）
        if first is not None:
            self._collect_drop_fingerprint(
                first.x, first.y, first.z, first.dimension.name, actor,
                radius=4,
            )

    @event_handler
    def on_block_explode(self, event: BlockExplodeEvent):
        if event.is_cancelled:
            return
        if not self._enabled("explode"):
            return
        source = self.plugin.lang.block_name(event.block.type)
        self._record_explode(event.block_list, f"爆炸({source})")

    @event_handler
    def on_actor_explode(self, event: ActorExplodeEvent):
        if event.is_cancelled:
            return
        if not self._enabled("explode"):
            return
        entity = self.plugin.lang.entity_name(event.actor.type)
        self._record_explode(event.block_list, f"爆炸({entity})")

    # ------------------------------------------------------------------
    # 世界事件
    # ------------------------------------------------------------------
    @event_handler
    def on_leaves_decay(self, event: LeavesDecayEvent):
        if event.is_cancelled:
            return
        if not self._enabled("leaves_decay"):
            return
        block = event.block
        # 回档进行中：区域内枯萎多为回档物理副作用，不记录
        #（最终校验兜底，避免污染日志与放大后续回档范围）
        if self._in_rollback_region(
            block.x, block.y, block.z, block.dimension.name
        ):
            return
        self._record_natural(block, "leaves_decay")

    @event_handler
    def on_block_grow(self, event: BlockGrowEvent):
        if event.is_cancelled:
            return
        if not self._enabled("block_grow"):
            return
        block = event.block  # 生长前的方块（回档恢复它）
        if self._in_rollback_region(
            block.x, block.y, block.z, block.dimension.name
        ):
            return
        self._record_natural(block, "block_grow")

    @event_handler
    def on_block_form(self, event: BlockFormEvent):
        if event.is_cancelled:
            return
        if not self._enabled("block_form"):
            return
        block = event.block  # 凝固前的方块（回档恢复它）
        if self._in_rollback_region(
            block.x, block.y, block.z, block.dimension.name
        ):
            return
        self._record_natural(block, "block_form")

    def _record_natural(self, block, action: str) -> None:
        self.plugin.record(
            action=action,
            actor="自然",
            block_type=block.type,
            block_states=states_to_json(block.data.block_states),
            x=block.x, y=block.y, z=block.z,
            dimension=block.dimension.name,
        )

    @event_handler
    def on_block_from_to(self, event: BlockFromToEvent):
        if event.is_cancelled:
            return
        if not self._enabled("liquid_flow"):
            return
        to_block = event.to_block
        if self._in_rollback_region(
            to_block.x, to_block.y, to_block.z, to_block.dimension.name
        ):
            return
        replaced = to_block.type
        liquid = _normalize_liquid(event.block.type)
        # 目的地已是同类液体（汇流）不记录，避免海量无效记录
        if replaced in (liquid, "minecraft:flowing_water", "minecraft:flowing_lava"):
            return
        self.plugin.record(
            action="liquid_flow",
            actor="自然",
            block_type=liquid,
            block_states="{}",
            replaced_type=replaced,
            replaced_states=states_to_json(to_block.data.block_states),
            x=to_block.x, y=to_block.y, z=to_block.z,
            dimension=to_block.dimension.name,
        )

    @event_handler
    def on_piston_extend(self, event: BlockPistonExtendEvent):
        if not self._enabled("piston"):
            return
        block = event.block
        self.plugin.record(
            action="piston", actor="活塞",
            block_type=block.type, block_states="{}",
            x=block.x, y=block.y, z=block.z,
            dimension=block.dimension.name,
        )

    @event_handler
    def on_piston_retract(self, event: BlockPistonRetractEvent):
        if not self._enabled("piston"):
            return
        block = event.block
        self.plugin.record(
            action="piston", actor="活塞",
            block_type=block.type, block_states="{}",
            x=block.x, y=block.y, z=block.z,
            dimension=block.dimension.name,
        )

    @event_handler
    def on_block_cook(self, event: BlockCookEvent):
        if event.is_cancelled:
            return
        if not self._enabled("block_cook"):
            return
        block = event.block
        self.plugin.record(
            action="block_cook", actor="自然",
            block_type=block.type, block_states="{}",
            x=block.x, y=block.y, z=block.z,
            dimension=block.dimension.name,
        )

    @event_handler
    def on_weather_change(self, event: WeatherChangeEvent):
        if event.is_cancelled:
            return
        if not self._enabled("weather"):
            return
        self.plugin.record_event(
            action="weather", actor="自然",
            detail="开始下雨" if event.to_weather_state else "雨停了",
        )

    @event_handler
    def on_thunder_change(self, event: ThunderChangeEvent):
        if event.is_cancelled:
            return
        if not self._enabled("weather"):
            return
        self.plugin.record_event(
            action="thunder", actor="自然",
            detail="雷暴开启" if event.to_thunder_state else "雷暴停止",
        )

    @event_handler
    def on_broadcast(self, event: BroadcastMessageEvent):
        if event.is_cancelled:
            return
        if not self._enabled("broadcast"):
            return
        self.plugin.record_event(
            action="broadcast", actor="服务器",
            detail=str(event.message),
        )

    @event_handler
    def on_server_command(self, event: ServerCommandEvent):
        if event.is_cancelled:
            return
        if not self._enabled("command"):
            return
        self.plugin.record_event(
            action="command", actor="控制台",
            detail=event.command,
        )

    @event_handler
    def on_plugin_enable(self, event: PluginEnableEvent):
        if not self._enabled("plugin_enable"):
            return
        self.plugin.record_event(
            action="plugin_enable", actor="服务器",
            detail=str(getattr(event.plugin, "name", "?")),
        )

    @event_handler
    def on_plugin_disable(self, event: PluginDisableEvent):
        if not self._enabled("plugin_disable"):
            return
        self.plugin.record_event(
            action="plugin_disable", actor="服务器",
            detail=str(getattr(event.plugin, "name", "?")),
        )

    # ------------------------------------------------------------------
    # 玩家行为
    # ------------------------------------------------------------------
    @event_handler
    def on_chat(self, event: PlayerChatEvent):
        if not self._enabled("chat"):
            return
        loc = event.player.location
        self.plugin.record_event(
            action="chat", actor=event.player.name, detail=event.message,
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    @event_handler
    def on_command(self, event: PlayerCommandEvent):
        if not self._enabled("command"):
            return
        loc = event.player.location
        self.plugin.record_event(
            action="command", actor=event.player.name, detail=event.command,
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    @event_handler
    def on_join(self, event: PlayerJoinEvent):
        name = event.player.name
        # 危险窗口正式结束：必须最先执行且不受日志开关影响——
        # gamemode 等处理器靠 _spawned 判定能否触碰 player 本体
        self._spawned.add(name)
        # 登记玩家名：每日日志按玩家分层的归属判定用
        self.plugin.note_player(name)
        if not self._enabled("join"):
            return
        # 入服过渡窗口：不现场读位置，延后 40 tick
        self._log_join_later(name)

    def _log_join_later(self, name: str) -> None:
        def _log() -> None:
            if self.plugin._stopping:
                return
            try:
                p = self.plugin.server.get_player(name)
                if p is not None:
                    loc = p.location
                    dim = p.dimension.name
                    self._note_seen(name, loc.block_x, loc.block_y, loc.block_z, dim)
                    self.plugin.record_event(
                        action="join", actor=name, detail="",
                        x=loc.block_x, y=loc.block_y, z=loc.block_z,
                        dimension=dim,
                    )
                    return
            except Exception:
                pass
            # 玩家已离开：仍留审计行（位置未知）
            self.plugin.record_event(
                action="join", actor=name, detail="",
                x=0, y=0, z=0, dimension="未知",
            )
        try:
            self.plugin.server.scheduler.run_task(self.plugin, _log, delay=40)
        except Exception:
            # 调度器不可用（停服中）：绝不退回现场读取——那正是危险窗口
            self.plugin.record_event(
                action="join", actor=name, detail="",
                x=0, y=0, z=0, dimension="未知",
            )

    def _note_seen(self, name: str, x: int, y: int, z: int, dim: str) -> None:
        """更新玩家位置快照（仅在稳定窗口读取成功后调用）。"""
        self._last_seen[name] = (x, y, z, dim)

    def _snapshot_of(self, name: str) -> tuple[int, int, int, str]:
        return self._last_seen.get(name, (0, 0, 0, "未知"))

    @event_handler
    def on_quit(self, event: PlayerQuitEvent):
        name = event.player.name
        # 清理运行状态（离服后危险窗口重启）
        self._spawned.discard(name)
        self.plugin.selection.clear(name)
        self.plugin.selection_off(name)
        self._last_interact.pop(name, None)
        if not self._enabled("quit"):
            return
        # 离服过渡窗口：用最近快照记日志，不读正在拆卸的 Actor
        x, y, z, dim = self._last_seen.pop(name, (0, 0, 0, "未知"))
        self.plugin.record_event(
            action="quit", actor=name, detail="",
            x=x, y=y, z=z, dimension=dim,
        )

    @event_handler
    def on_kick(self, event: PlayerKickEvent):
        # 踢出后 Actor 即将拆卸，先行移出 _spawned 关闭危险窗口
        self._spawned.discard(event.player.name)
        if not self._enabled("kick"):
            return
        x, y, z, dim = self._snapshot_of(event.player.name)
        self.plugin.record_event(
            action="kick", actor=event.player.name,
            detail=str(event.reason) if event.reason else "",
            x=x, y=y, z=z, dimension=dim,
        )

    @event_handler
    def on_player_death(self, event: PlayerDeathEvent):
        if not self._enabled("kill"):
            return
        victim = event.player
        actor = victim.name
        try:
            ds = event.damage_source
            killer = getattr(ds, "damaging_actor", None) or getattr(ds, "actor", None)
            if killer is not None and not isinstance(killer, Player):
                actor = f"{self.plugin.lang.entity_name(killer.type)}"
            elif killer is not None:
                actor = killer.name
        except Exception:
            pass
        loc = victim.location
        self._note_seen(
            victim.name, loc.block_x, loc.block_y, loc.block_z,
            victim.dimension.name,
        )
        self.plugin.record_event(
            action="kill", actor=actor,
            detail=event.death_message or f"{victim.name} 死亡",
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=victim.dimension.name,
        )

    @event_handler
    def on_actor_death(self, event: ActorDeathEvent):
        if not self._enabled("entity_kill"):
            return
        victim = event.actor
        if isinstance(victim, Player):
            return  # 玩家死亡由 on_player_death 记录
        actor = "未知"
        try:
            ds = event.damage_source
            killer = getattr(ds, "damaging_actor", None) or getattr(ds, "actor", None)
            if killer is not None:
                actor = killer.name if isinstance(killer, Player) else (
                    self.plugin.lang.entity_name(killer.type)
                )
        except Exception:
            pass
        loc = victim.location
        self.plugin.record_event(
            action="entity_kill", actor=actor,
            detail=f"击杀了 {self.plugin.lang.entity_name(victim.type)}",
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=victim.dimension.name,
        )

    @event_handler
    def on_item_drop(self, event: PlayerDropItemEvent):
        if event.is_cancelled:
            return
        if not self._enabled("item_drop"):
            return
        loc = event.player.location
        self.plugin.record_event(
            action="item_drop", actor=event.player.name,
            detail=self._item_desc(event.item),
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    @event_handler
    def on_item_pickup(self, event: PlayerPickupItemEvent):
        if event.is_cancelled:
            return
        if not self._enabled("item_pickup"):
            return
        loc = event.player.location
        self.plugin.record_event(
            action="item_pickup", actor=event.player.name,
            detail=self._item_desc(event.item),
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    @event_handler
    def on_item_consume(self, event: PlayerItemConsumeEvent):
        if event.is_cancelled:
            return
        if not self._enabled("item_consume"):
            return
        loc = event.player.location
        self.plugin.record_event(
            action="item_consume", actor=event.player.name,
            detail=self._item_desc(event.item),
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    @event_handler
    def on_gamemode(self, event: PlayerGameModeChangeEvent):
        if not self._enabled("gamemode"):
            return
        name = event.player.name
        # 登录窗口（tryToLoadPlayer 恢复存档）也触发本事件，读 location
        # 必段错误（0.5.6 实测）；且那是服务器还原旧状态而非玩家操作，
        # 记录会误导滥用排查，直接跳过
        if name not in self._spawned:
            return
        loc = event.player.location
        mode = str(event.new_game_mode).rsplit(".", 1)[-1]
        self.plugin.record_event(
            action="gamemode", actor=name, detail=f"切换为 {mode}",
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    @event_handler
    def on_teleport(self, event: PlayerTeleportEvent):
        if not self._enabled("teleport"):
            return
        to = event.to_location
        # 维度名取目标位置的（事件自带引用，不经全图遍历），
        # 不读处于传送过渡中的 player 本体
        dim = to.dimension.name
        self._note_seen(event.player.name, to.block_x, to.block_y, to.block_z, dim)
        self.plugin.record_event(
            action="teleport", actor=event.player.name,
            detail=f"传送至 ({to.block_x}, {to.block_y}, {to.block_z})",
            x=to.block_x, y=to.block_y, z=to.block_z,
            dimension=dim,
        )

    @event_handler
    def on_bed_enter(self, event: PlayerBedEnterEvent):
        if not self._enabled("bed_enter"):
            return
        loc = event.player.location
        self.plugin.record_event(
            action="bed_enter", actor=event.player.name, detail="上床睡觉",
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    @event_handler
    def on_bed_leave(self, event: PlayerBedLeaveEvent):
        if not self._enabled("bed_leave"):
            return
        loc = event.player.location
        self.plugin.record_event(
            action="bed_leave", actor=event.player.name, detail="起床",
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    @event_handler
    def on_dimension_change(self, event: PlayerDimensionChangeEvent):
        if not self._enabled("dimension_change"):
            return
        name = event.player.name
        # 登录定位阶段也可能触发（存档位置在异维度），未入服直接跳过。
        # 维度切换是引用重绑定的过渡窗口：不读 player 本体，坐标用
        # 快照，维度名用事件自带的 to/from 对象（生命周期与事件绑定）
        if name not in self._spawned:
            return
        to_dim = event.to_dimension.name
        from_dim = event.from_dimension.name
        x, y, z, _ = self._snapshot_of(name)
        self.plugin.record_event(
            action="dimension_change", actor=name,
            detail=f"从{self.plugin.lang.dimension_name(from_dim)}"
                   f"前往{self.plugin.lang.dimension_name(to_dim)}",
            x=x, y=y, z=z,
            dimension=to_dim,
        )

    @event_handler
    def on_respawn(self, event: PlayerRespawnEvent):
        if not self._enabled("respawn"):
            return
        # 重生是 Actor 迁移窗口（可能跨维度）：延后 20 tick 待落位
        self._log_respawn_later(event.player.name)

    def _log_respawn_later(self, name: str) -> None:
        def _log() -> None:
            if self.plugin._stopping:
                return
            try:
                p = self.plugin.server.get_player(name)
                if p is not None:
                    loc = p.location
                    dim = p.dimension.name
                    self._note_seen(name, loc.block_x, loc.block_y, loc.block_z, dim)
                    self.plugin.record_event(
                        action="respawn", actor=name, detail="重生",
                        x=loc.block_x, y=loc.block_y, z=loc.block_z,
                        dimension=dim,
                    )
                    return
            except Exception:
                pass
            # 玩家已离线：用快照（死亡位置）记录
            x, y, z, dim = self._snapshot_of(name)
            self.plugin.record_event(
                action="respawn", actor=name, detail="重生",
                x=x, y=y, z=z, dimension=dim,
            )
        try:
            self.plugin.server.scheduler.run_task(self.plugin, _log, delay=20)
        except Exception:
            # 调度器不可用（停服中）：绝不现场读取，用快照记录
            x, y, z, dim = self._snapshot_of(name)
            self.plugin.record_event(
                action="respawn", actor=name, detail="重生",
                x=x, y=y, z=z, dimension=dim,
            )

    @event_handler
    def on_emote(self, event: PlayerEmoteEvent):
        if not self._enabled("emote"):
            return
        loc = event.player.location
        self.plugin.record_event(
            action="emote", actor=event.player.name,
            detail=f"播放表情 {event.emote_id}",
            x=loc.block_x, y=loc.block_y, z=loc.block_z,
            dimension=event.player.dimension.name,
        )

    # ------------------------------------------------------------------
    # 玩家交互：选区工具 / 桶与骨粉 / 容器与方块日志
    # ------------------------------------------------------------------
    @event_handler
    def on_player_interact(self, event: PlayerInteractEvent):
        if event.is_cancelled:
            return
        player = event.player
        if not event.has_block:
            return

        action = event.action
        is_left = action == PlayerInteractEvent.Action.LEFT_CLICK_BLOCK
        is_right = action == PlayerInteractEvent.Action.RIGHT_CLICK_BLOCK
        if not (is_left or is_right):
            return

        block = event.block

        # 1) 选区工具：木斧（wand_item）右键顺序选点（首点/次点/两点
        #    齐全后改首点）、左键退出选区；木棍（wand_item_2）右键
        #    仅在两点齐全后改第二点
        item_id = None
        if event.has_item:
            try:
                item_id = event.item.type.id
            except Exception:
                item_id = None
        cfg = self.plugin.cfg
        wand1 = cfg.get("wand_item", default="minecraft:wooden_axe")
        wand2 = cfg.get("selection", "wand_item_2", default="minecraft:stick")
        menu_item = cfg.get(
            "selection", "menu_open_item", default="minecraft:wooden_axe"
        )
        require_start = bool(cfg.get("selection", "require_start", default=True))
        selecting = self.plugin.is_selecting(player.name)
        is_wand1 = item_id == wand1
        is_wand2 = item_id == wand2 and not is_wand1  # 同 ID 时以 wand1 为准

        # 选区权限校验：授权被中途撤销时工具立即失效，
        # 并顺手清理残留的选区模式状态
        if selecting and not (
            bool(player.is_op)
            or self.plugin.permissions.has(player.name, "selection")
        ):
            selecting = False
            self.plugin.selection_off(player.name)

        # 1a) 左键木斧：退出选区模式
        if is_left and is_wand1 and selecting:
            event.cancel()
            self.plugin.selection_off(player.name)
            try:
                player.play_sound(player.location, "random.orb")
            except Exception:
                pass
            player.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.RED} "
                f"{ColorFormat.BOLD}选区模式已关闭{ColorFormat.RESET}"
                f"{ColorFormat.WHITE}（木斧左键）：选区与边框已清除"
            )
            return

        # 1b) 右键选区工具：选点 / 修改点
        if is_right and (is_wand1 or is_wand2):
            # 选区模式门控：未 /mxback start 时工具不生效
            if require_start and not selecting:
                if (
                    bool(cfg.get("selection", "ground_click_menu", default=False))
                    and item_id == menu_item
                ):
                    event.cancel()
                    self.plugin.forms.show_main_menu(player)
                return

            old_sel = self.plugin.selection.get(player.name)
            same_dim = (
                old_sel is not None
                and old_sel.dimension == player.dimension.name
            )

            if is_wand2:
                # 木棍仅在两点齐全后生效：修改第二点
                if not (same_dim and old_sel.complete()):
                    return
                which = 2
            else:
                # 木斧：无首点 -> 首点；有首点无次点 -> 次点；齐全 -> 改首点
                if not same_dim or old_sel.pos1 is None:
                    which = 1
                elif old_sel.pos2 is None:
                    which = 2
                else:
                    which = 1

            event.cancel()  # 防止顺手打开容器/放置方块
            max_volume = int(cfg.get("selection", "max_volume", default=32768))
            min_y = int(cfg.get("selection", "min_y", default=-64))
            max_y = int(cfg.get("selection", "max_y", default=319))
            y = min(max(block.y, min_y), max_y)
            was_complete = bool(same_dim and old_sel.complete())
            sel = self.plugin.selection.select_point(player, block.x, y, block.z, which)
            label = "第一个点" if which == 1 else "第二个点"
            verb = "已更新" if was_complete else "已选择"
            try:
                player.play_sound(player.location, "random.orb")
            except Exception:
                pass
            player.send_message(
                f"{ColorFormat.GOLD}[MxBack]{ColorFormat.WHITE} "
                f"{label} {verb}: ({block.x}, {y}, {block.z})"
            )
            if sel.complete():
                if self.plugin.selection.volume_exceeds(sel, max_volume):
                    player.send_error_message(
                        f"选区体积过大（{sel.volume()} > {max_volume}），请重新选择"
                    )
                    self.plugin.selection.clear(player.name)
                    return
                player.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GRAY} "
                    f"已选: {sel.pos1} -> {sel.pos2}（体积 {sel.volume()}）"
                )
                # 从不完整变为完整时：渲染边框并弹出操作表单
                if not was_complete:
                    self.plugin.render_selection_once(player.name)
                    self.plugin.forms.show_selection_menu(player)
            else:
                player.send_message(
                    f"{ColorFormat.GOLD}[MxBack]{ColorFormat.GRAY} "
                    f"已选: {sel.pos1} -> 待选（继续右键木斧选第二点）"
                )
            return

        # 1c) 主菜单物品：未开启选区模式时右键打开主菜单
        if (
            is_right
            and bool(cfg.get("selection", "ground_click_menu", default=False))
            and item_id == menu_item
            and require_start
            and not selecting
        ):
            event.cancel()
            self.plugin.forms.show_main_menu(player)
            return

        # 2) 桶液体记录（Endstone 无桶事件：交互时快照 + 延迟验证，
        #    防点击容器等误报）与骨粉催熟快照（结构生长无事件，兜底记录）
        if is_right and item_id:
            if item_id in _BUCKET_LIQUIDS:
                # 先登记 BlockPlaceEvent 守卫（放置事件与本次交互同 tick）
                self._guard_bucket_place(player.name, block, event.block_face)
                self._schedule_bucket_place(
                    player, block, event.block_face, _BUCKET_LIQUIDS[item_id]
                )
            elif item_id == "minecraft:bucket":
                self._schedule_bucket_scoop(player, block)
            elif item_id == _BONE_MEAL:
                self._schedule_bonemeal(player, block)

        # 3) 容器交互 / 可点击方块日志（右键）
        if is_right:
            block_id = block.type
            if self._enabled("container_open") and block_id in self.plugin.container_ids:
                if self._dedup_interact(
                    player.name, block.x, block.y, block.z, "container_open"
                ):
                    self.plugin.record(
                        action="container_open",
                        actor=player.name,
                        block_type=block_id,
                        block_states="{}",
                        x=block.x, y=block.y, z=block.z,
                        dimension=block.dimension.name,
                    )
            elif self._enabled("click") and self._is_clickable(block_id):
                if self._dedup_interact(
                    player.name, block.x, block.y, block.z, "click"
                ):
                    self.plugin.record(
                        action="click",
                        actor=player.name,
                        block_type=block_id,
                        block_states="{}",
                        x=block.x, y=block.y, z=block.z,
                        dimension=block.dimension.name,
                    )

    @event_handler
    def on_interact_actor(self, event: PlayerInteractActorEvent):
        if event.is_cancelled:
            return
        if not self._enabled("entity_interact"):
            return
        player = event.player
        target = event.actor
        if target is None:
            return
        try:
            loc = target.location
            # 同一玩家 1 秒内对同一实体的重复右键只记一次
            if not self._dedup_interact(
                player.name, loc.block_x, loc.block_y, loc.block_z,
                "entity_interact",
            ):
                return
            entity_cn = self.plugin.lang.entity_name(target.type)
            self.plugin.record_event(
                action="entity_interact",
                actor=player.name,
                detail=entity_cn,
                x=loc.block_x, y=loc.block_y, z=loc.block_z,
                dimension=target.dimension.name,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _item_desc(item) -> str:
        """物品 -> 可读描述。API 类型不对称：pickup 的 item 是 Item 实体，
        须经 item_stack 取真实物品，否则恒为 "minecraft:item x1"。"""
        try:
            stack = getattr(item, "item_stack", None)
            if stack is None:
                stack = item  # 本身就是 ItemStack
            if stack is None:
                return "未知物品"
            amount = getattr(stack, "amount", 1) or 1
            return f"{stack.type} x{amount}"
        except Exception:
            return "未知物品"

    @staticmethod
    def _is_clickable(block_id: str) -> bool:
        return any(k in block_id for k in _CLICK_KEYWORDS)

    def _dedup_interact(
        self, name: str, x: int, y: int, z: int, action: str,
    ) -> bool:
        """同一玩家 1 秒内对同一方块/实体的同类交互只记一次。"""
        key = (x, y, z)
        now = time.monotonic()
        last = self._last_interact.get(name)
        if last is not None and last[0] == key and last[1] == action and now - last[2] < 1.0:
            return False
        self._last_interact[name] = (key, action, now)
        return True

    def _enabled(self, action: str) -> bool:
        key = _ACTION_CATEGORY.get(action, action)
        return bool(
            self.plugin.cfg.get("logs", "categories", key, default=False)
        )

    def _in_rollback_region(self, x: int, y: int, z: int, dim_name: str) -> bool:
        try:
            return self.plugin.rollback.is_in_active_region(x, y, z, dim_name)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 掉落物指纹：破坏/爆炸 -> 2 tick 后扫描周边新生掉落物
    # ------------------------------------------------------------------
    def _collect_drop_fingerprint(
        self, x: int, y: int, z: int, dim_name: str, actor: str,
        radius: int = 2,
    ) -> None:
        """记录破坏产生的掉落物指纹，供回档后清理（cleanup_drops 开关）。

        延迟 2 tick（掉落物生成需 1-2 tick）；同一次爆炸的多个方块由
        邻域去重合并，全量 actors 只遍历一次。
        """
        if not bool(self.plugin.cfg.get(
            "rollback", "cleanup_drops", default=True
        )):
            return
        now = time.monotonic()
        key = (dim_name, x // 3, y // 3, z // 3)
        last = self._last_drop_scan.get(key)
        if last is not None and now - last < 1.0:
            return
        if len(self._last_drop_scan) > 8192:
            self._last_drop_scan.clear()
        self._last_drop_scan[key] = now

        def scan():
            if self.plugin._stopping:
                return
            dim = self._get_dimension(dim_name)
            if dim is None:
                return
            try:
                drops = []
                for act in dim.actors:
                    try:
                        if act.type != _ITEM_ENTITY_TYPE:
                            continue
                        # 先用安全字段（location）过滤：item_stack 读取
                        # 有平台段错误风险（<0.11.8），只对邻近掉落物读取
                        loc = act.location
                        if abs(loc.x - x) > radius + 1 or \
                           abs(loc.y - y) > radius + 1 or \
                           abs(loc.z - z) > radius + 1:
                            continue
                        fp = _item_fingerprint(act)
                        if fp is None:
                            continue
                        drops.append({"id": fp[0], "n": fp[1],
                                      "x": round(loc.x, 1),
                                      "y": round(loc.y, 1),
                                      "z": round(loc.z, 1)})
                    except Exception:
                        continue
                if drops:
                    self.plugin.record_event(
                        action="drop_snapshot",
                        actor=actor,
                        detail=json.dumps(drops, ensure_ascii=False),
                        x=x, y=y, z=z,
                        dimension=dim_name,
                        daily=False,
                    )
            except Exception:
                pass

        try:
            self.plugin.server.scheduler.run_task(self.plugin, scan, delay=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 骨粉催熟：结构生长不触发 BlockGrowEvent，快照+对比兜底
    # ------------------------------------------------------------------
    def _schedule_bonemeal(self, player, block) -> None:
        """交互时快照周围方块，3 tick 后把变化记为 block_grow（回档恢复
        催熟前状态：长出的树消失、作物退回、树苗恢复）。"""
        if not self._enabled("bone_meal"):
            return
        bx, by, bz = block.x, block.y, block.z
        key = (player.name, bx, by, bz, "bonemeal")
        if key in self._pending_buckets:
            return
        dim = block.dimension
        dim_name = dim.name
        # 回档进行中：对比会把回档变化误记为催熟记录，放弃
        if self._in_rollback_region(bx, by, bz, dim_name):
            return
        if len(self._pending_buckets) >= _MAX_PENDING_TASKS:
            return
        # 事件时骨粉尚未生效（事件可取消），同步快照：
        # x/z ±3、y 0..+9 覆盖树苗成树与农作物
        snapshot = {}
        try:
            loaded = _loaded_chunks(dim)
            for dx in range(-3, 4):
                for dz in range(-3, 4):
                    if not _chunk_ok(loaded, bx + dx, bz + dz):
                        continue
                    for dy in range(0, 10):
                        b = dim.get_block_at(bx + dx, by + dy, bz + dz)
                        snapshot[(bx + dx, by + dy, bz + dz)] = (
                            b.type, states_to_json(b.data.block_states)
                        )
        except Exception:
            return
        pname = player.name
        self._pending_buckets.add(key)

        def diff():
            self._pending_buckets.discard(key)
            if self.plugin._stopping:
                return
            if self._in_rollback_region(bx, by, bz, dim_name):
                return
            dim = self._get_dimension(dim_name)
            if dim is None:
                return
            try:
                loaded = _loaded_chunks(dim)
                for (x, y, z), (old_type, old_states) in snapshot.items():
                    if not _chunk_ok(loaded, x, z):
                        continue
                    b = dim.get_block_at(x, y, z)
                    if (
                        b.type == old_type
                        and states_to_json(b.data.block_states) == old_states
                    ):
                        continue
                    self.plugin.record(
                        action="block_grow",
                        actor=pname,
                        block_type=old_type,
                        block_states=old_states,
                        x=x, y=y, z=z,
                        dimension=dim_name,
                        daily_label="使用骨粉催熟",
                    )
            except Exception:
                pass

        try:
            self.plugin.server.scheduler.run_task(self.plugin, diff, delay=3)
        except Exception:
            self._pending_buckets.discard(key)

    def _get_dimension(self, name: str):
        """按名称现场获取维度（延迟回调内唯一安全的获取方式）。

        Dimension 包装只是视图，不延长 C++ 生命周期；闭包跨 tick 持有
        引用时维度若被析构（世界卸载/关服）就是悬空引用，调用任何方法
        都会读已释放的 WeakStorageSharePtr 控制块直接段错误且无法捕获。
        """
        try:
            return self.plugin.server.level.get_dimension(name)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 桶液体记录
    # ------------------------------------------------------------------
    def _guard_bucket_place(self, pname: str, block, face) -> None:
        """登记桶交互的目标位置，供 on_block_place 跳过崩服向量。

        登记点击方块与其相邻面两个位置（含水化时事件位置=方块本身，
        常规放置=相邻面）。
        """
        now = time.monotonic()
        if len(self._bucket_event_guard) > 512:
            self._bucket_event_guard = {
                k: v for k, v in self._bucket_event_guard.items()
                if now - v < _BUCKET_GUARD_WINDOW
            }
        self._bucket_event_guard[(pname, block.x, block.y, block.z)] = now
        off = _FACE_OFFSETS.get(face)
        if off is not None:
            self._bucket_event_guard[(
                pname, block.x + off[0], block.y + off[1], block.z + off[2]
            )] = now

    def _schedule_bucket_place(self, player, block, face, liquid: str) -> None:
        """满桶右键：按实际变化记录四种形态。

        面放置 -> place；点击方块被液体替换 -> place（replaced=原方块）；
        层 0 状态变化 -> liquid_flow；灌进层 1 的水（无事件、层 0 状态
        与干燥方块完全相同）-> 白名单直接判定或延迟观察邻居新出现的
        同类液体确认（含水方块是液体源会外溢，水约 5 tick/格）。
        """
        offset = _FACE_OFFSETS.get(face)
        if offset is None:
            return
        # block 是事件持有的临时包装（事件分发结束即析构），坐标必须
        # 同 tick 提取为 int，延迟回调跨 tick 访问会虚调用已释放对象
        bx, by, bz = block.x, block.y, block.z
        tx, ty, tz = bx + offset[0], by + offset[1], bz + offset[2]
        key = (player.name, tx, ty, tz, "place")
        if key in self._pending_buckets:
            return
        dimension = block.dimension
        dim_name = dimension.name
        # 回档进行中：延迟验证会把回档变化误记为玩家的放置/灌水
        if (
            self._in_rollback_region(tx, ty, tz, dim_name)
            or self._in_rollback_region(bx, by, bz, dim_name)
        ):
            return
        if len(self._pending_buckets) >= _MAX_PENDING_TASKS:
            return
        try:
            if not _chunk_ok(_loaded_chunks(dimension), tx, tz):
                return
            target = dimension.get_block_at(tx, ty, tz)
            pre_type = target.type
            pre_states = states_to_json(target.data.block_states)
        except Exception:
            return
        # 目标面已是同类液体：桶的水要么入水无变化，要么被灌进点击
        # 方块的层 1（密集灌水时后者整条丢失会残留含水方块）。
        # 携带标记继续走含水检测；verify 据此跳过面放置判定
        face_pre_liquid = (
            pre_type == liquid or pre_type.startswith("minecraft:flowing_")
        )
        try:
            self_pre = (
                block.type, states_to_json(block.data.block_states)
            )
        except Exception:
            self_pre = None
        # 含水检测基线：点击方块 6 邻居的同类液体快照（同 tick 采集）。
        # 灌进层 1 时唯一可见信号是含水方块作为源向外扩散
        neigh_liquid = None
        try:
            loaded0 = _loaded_chunks(dimension)
            snap = []
            for dx, dy, dz in (
                (1, 0, 0), (-1, 0, 0), (0, 1, 0),
                (0, -1, 0), (0, 0, 1), (0, 0, -1),
            ):
                nx, ny, nz = bx + dx, by + dy, bz + dz
                if not _chunk_ok(loaded0, nx, nz):
                    break  # 邻居区块未加载：基线不完整，放弃含水检测
                nt = dimension.get_block_at(nx, ny, nz).type
                snap.append((
                    (nx, ny, nz),
                    nt == liquid or str(nt).startswith("minecraft:flowing_"),
                ))
            else:
                neigh_liquid = snap
        except Exception:
            neigh_liquid = None
        pname = player.name
        # verify 阶段写入"水是否浇在了相邻面"，check_waterlog 据此排除
        # 面位置的观测证据（面上的水由浇灌本身解释，不能证明方块是源）
        waterlog_ctx = {"exclude_face": False}
        self._pending_buckets.add(key)

        def _record_waterlog() -> None:
            if self._enabled("liquid_flow"):
                self.plugin.record(
                    action="liquid_flow",
                    actor=pname,
                    block_type=liquid,
                    block_states="{}",
                    replaced_type=self_pre[0],
                    replaced_states=self_pre[1],
                    x=bx, y=by, z=bz,
                    dimension=dim_name,
                    daily_label="往方块里灌入液体",
                )

        def check_waterlog(final: bool = False):
            """延迟验证点击方块是否被灌成含水（层 1 水）。

            点击方块类型未变且某个"基线无同类液体"的邻居现在有了同类
            液体 -> 强证据记录。两阶段复查：密集灌水使液体更新排队，
            层 1 水外流可能尚未抵达邻居，首查（25 tick）不定论再等
            50 tick 终审。
            """
            if self.plugin._stopping:
                return
            if waterlog_ctx.get("confirmed"):
                return  # 已由放置事件确认并记录
            if self._in_rollback_region(bx, by, bz, dim_name):
                return
            dim = self._get_dimension(dim_name)
            if dim is None:
                return
            try:
                loaded = _loaded_chunks(dim)
                if not _chunk_ok(loaded, bx, bz):
                    return
                nb = dim.get_block_at(bx, by, bz)
                if nb.type != self_pre[0]:
                    return  # 之后被其他行为改动，无法归因
                # 观察能力受损标记：基线存在湿邻居（密集灌水把区域打湿）
                # 时"无新液体"无法证明不含水
                blocked = False
                exclude_face = waterlog_ctx["exclude_face"]
                for (nx, ny, nz), was_liquid in neigh_liquid:
                    if was_liquid:
                        blocked = True
                        continue
                    if not _chunk_ok(loaded, nx, nz):
                        continue
                    if exclude_face and (nx, ny, nz) == (tx, ty, tz):
                        # 面位置的液体由浇灌本身解释，不能作为证据
                        continue
                    nt = dim.get_block_at(nx, ny, nz).type
                    if nt == liquid or str(nt).startswith("minecraft:flowing_"):
                        # 层 0 无变化而邻居新出现同类液体——唯一来源是层 1 水
                        _record_waterlog()
                        return
                if blocked:
                    # 保守记录：宁可误报（回档流水线自行甄别，误报代价
                    # 只是一次往返），不可漏报（假死水源无法挽回）
                    _record_waterlog()
                elif not final:
                    # 全干基线且无新液体：暂不定论，再等 50 tick 终审
                    try:
                        self.plugin.server.scheduler.run_task(
                            self.plugin,
                            lambda: check_waterlog(True),
                            delay=50,
                        )
                    except Exception:
                        pass
            except Exception:
                pass

        def verify():
            self._pending_buckets.discard(key)
            if self.plugin._stopping:
                return
            if (
                self._in_rollback_region(tx, ty, tz, dim_name)
                or self._in_rollback_region(bx, by, bz, dim_name)
            ):
                return
            dim = self._get_dimension(dim_name)
            if dim is None:
                return
            loaded = _loaded_chunks(dim)
            if not (
                _chunk_ok(loaded, bx, bz)
                and _chunk_ok(loaded, tx, tz)
            ):
                return
            # 检测 1/2：点击方块自身的变化（灌水场景）
            self_changed = False
            if self_pre is not None:
                try:
                    nb = dim.get_block_at(bx, by, bz)
                    now_states = states_to_json(nb.data.block_states)
                    if nb.type != self_pre[0] and (
                        nb.type == liquid
                        or str(nb.type).startswith("minecraft:flowing_")
                    ):
                        # 方块本身被液体替换
                        self_changed = True
                        if self._enabled("block_place"):
                            self.plugin.record(
                                action="place",
                                actor=pname,
                                block_type=liquid,
                                block_states="{}",
                                replaced_type=self_pre[0],
                                replaced_states=self_pre[1],
                                x=bx, y=by, z=bz,
                                dimension=dim_name,
                            )
                    elif nb.type == self_pre[0] and now_states != self_pre[1]:
                        # 类型不变而状态变化：灌入方块的液体
                        self_changed = True
                        _record_waterlog()
                except Exception:
                    pass
            # 检测 3：相邻面常规放置（面已是同类液体时跳过——
            # 倒水入水只会产出脏记录）
            placed_at_face = False
            try:
                now_type = dim.get_block_at(tx, ty, tz).type
                if not face_pre_liquid and (
                    now_type == liquid or str(now_type).startswith(
                        "minecraft:flowing_"
                    )
                ):
                    placed_at_face = True
                    if self._enabled("block_place"):
                        self.plugin.record(
                            action="place",
                            actor=pname,
                            block_type=liquid,
                            block_states="{}",
                            replaced_type=pre_type,
                            replaced_states=pre_states,
                            x=tx, y=ty, z=tz,
                            dimension=dim_name,
                        )
            except Exception:
                pass
            had_wet_base = bool(neigh_liquid) and any(
                w for _, w in neigh_liquid
            )
            # 检测 3.5：白名单方块直接判定。BDS 对可含水方块倒水桶直接
            # 灌入层 1：无事件、层 0 不变、封闭方块的层 1 水永无外溢
            # （观察法失效）。"类型未变 + 面无水（或面水有歧义）"即记录
            # ——误报代价为零（流水线置 air 无归一化水会自行复原干燥方块）
            if (
                not self_changed
                and self_pre is not None
                and (not placed_at_face or had_wet_base)
                and not waterlog_ctx.get("confirmed")
                and _is_waterlog_safe(self_pre[0])
            ):
                waterlog_ctx["confirmed"] = True
                _record_waterlog()
            # 检测 4：白名单外的可含水方块兜底——交由延迟观察甄别。
            # placed_at_face 不能直接否决：+1 tick 面上的液体可能是
            # 点击方块层 1 水的外流或环境扩散；仅基线全干的常规面浇灌
            # （面的水只能是浇灌本身）跳过
            if (
                (not placed_at_face or had_wet_base)
                and not self_changed
                and self_pre is not None
                and neigh_liquid is not None
                and not waterlog_ctx.get("confirmed")
            ):
                waterlog_ctx["exclude_face"] = placed_at_face
                try:
                    self.plugin.server.scheduler.run_task(
                        self.plugin, check_waterlog,
                        delay=25 if liquid == "minecraft:water" else 85,
                    )
                except Exception:
                    pass

        try:
            self.plugin.server.scheduler.run_task(self.plugin, verify, delay=1)
        except Exception:
            self._pending_buckets.discard(key)

    def _schedule_bucket_scoop(self, player, block) -> None:
        """空桶右键液体：验证液体确实被舀走才记 break（回档可恢复）。"""
        pre_type = block.type
        if pre_type not in _SCOOPABLE:
            return
        # block 是事件持有的临时包装，坐标必须同 tick 提取
        bx, by, bz = block.x, block.y, block.z
        key = (player.name, bx, by, bz, "scoop")
        if key in self._pending_buckets:
            return
        dimension = block.dimension
        dim_name = dimension.name
        if self._in_rollback_region(bx, by, bz, dim_name):
            return
        if len(self._pending_buckets) >= _MAX_PENDING_TASKS:
            return
        pre_states = states_to_json(block.data.block_states)
        pre_type = _normalize_liquid(pre_type)  # 标准 ID，回档放置可用
        pname = player.name
        self._pending_buckets.add(key)

        def verify():
            self._pending_buckets.discard(key)
            if self.plugin._stopping:
                return
            if self._in_rollback_region(bx, by, bz, dim_name):
                return
            dim = self._get_dimension(dim_name)
            if dim is None:
                return
            if not _chunk_ok(_loaded_chunks(dim), bx, bz):
                return
            try:
                now_type = dim.get_block_at(bx, by, bz).type
                if now_type == pre_type or now_type.startswith(
                    "minecraft:flowing_"
                ):
                    return  # 液体没被舀走
                if not self._enabled("block_break"):
                    return
                self.plugin.record(
                    action="break",
                    actor=pname,
                    block_type=pre_type,
                    block_states=pre_states,
                    x=bx, y=by, z=bz,
                    dimension=dim_name,
                )
            except Exception:
                pass

        try:
            self.plugin.server.scheduler.run_task(self.plugin, verify, delay=1)
        except Exception:
            self._pending_buckets.discard(key)

    # ------------------------------------------------------------------
    # 海绵吸水：无事件，放置时快照 + 延迟对比
    # ------------------------------------------------------------------
    def _schedule_sponge_absorb(self, player, bx: int, by: int, bz: int) -> None:
        """干海绵放置：快照半径 7 内的水，延迟对比记被吸的水为 break。

        放置事件先于吸水执行（事件可取消），事件内同 tick 快照预吸水
        状态；周边流出的水随源消失渐进排空，故延迟对比 + 二轮复核。
        """
        dim_name = player.dimension.name
        key = (player.name, bx, by, bz, "sponge")
        if key in self._pending_sponges:
            return
        if self._in_rollback_region(bx, by, bz, dim_name):
            return
        if len(self._pending_sponges) >= _MAX_PENDING_TASKS:
            return
        dim = player.dimension
        loaded = _loaded_chunks(dim)
        # 预吸水快照：只收水的坐标（纯类型读取，海绵放置低频可接受）
        snapshot: list[tuple] = []
        r = _SPONGE_RADIUS
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    x, y, z = bx + dx, by + dy, bz + dz
                    if not _chunk_ok(loaded, x, z):
                        continue  # 区块未加载：读取是段错误向量
                    try:
                        t = dim.get_block_at(x, y, z).type
                    except Exception:
                        continue
                    if t in ("minecraft:water", "minecraft:flowing_water"):
                        snapshot.append((x, y, z))
        if not snapshot:
            return  # 附近无水，无需延迟任务
        pname = player.name

        def check(final: bool):
            if self.plugin._stopping:
                self._pending_sponges.discard(key)
                return
            dim = self._get_dimension(dim_name)
            if dim is None:
                self._pending_sponges.discard(key)
                return
            loaded = _loaded_chunks(dim)
            remaining = []
            for x, y, z in snapshot:
                if not _chunk_ok(loaded, x, z):
                    continue  # 区块卸载：宁漏勿误
                try:
                    t = dim.get_block_at(x, y, z).type
                except Exception:
                    continue
                if t != "minecraft:air":
                    if t in ("minecraft:water", "minecraft:flowing_water"):
                        remaining.append((x, y, z))
                    continue
                # 曾是水且现为空气 = 被吸除；回档区域内的清空是回档
                # 自身行为，跳过以免污染
                if self._in_rollback_region(x, y, z, dim_name):
                    continue
                if self._enabled("block_break"):
                    self.plugin.record(
                        action="break",
                        actor=pname,
                        block_type="minecraft:water",
                        block_states="{}",
                        x=x, y=y, z=z,
                        dimension=dim_name,
                        daily_label="海绵吸水",
                    )
            if remaining and not final:
                # 流水排空是渐进的，未排空的留待二轮复核
                try:
                    self.plugin.server.scheduler.run_task(
                        self.plugin, lambda: check(True),
                        delay=_SPONGE_RECHECK_DELAY,
                    )
                except Exception:
                    self._pending_sponges.discard(key)
            else:
                self._pending_sponges.discard(key)

        self._pending_sponges.add(key)
        try:
            self.plugin.server.scheduler.run_task(
                self.plugin, lambda: check(False), delay=_SPONGE_VERIFY_DELAY
            )
        except Exception:
            self._pending_sponges.discard(key)

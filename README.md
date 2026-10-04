# MXBack

Minecraft 基岩版（BDS）Endstone 方块日志记录与区域回档插件。

记录方块变更、爆炸、液体流动、容器交互、玩家行为等日志，支持可视化选区、按时间窗区域回档、撤销回档、日志查询与每日归档，全部操作可在游戏内表单完成。

## 功能特性

- **方块日志**：破坏 / 放置 / 爆炸（TNT、苦力怕、凋灵、床）/ 树叶枯萎 / 作物生长 / 液体凝固 / 液体流动，均可回档
- **玩家行为日志**：容器交互、门/按钮/拉杆交互、右键实体、聊天、命令、上下线、击杀死亡、物品丢弃/拾取/使用、游戏模式、传送、上床、跨维度、重生、表情等
- **世界事件日志**：活塞推动、熔炉烤制、天气雷暴、广播、插件启停
- **区域回档**：选区 + 时间窗恢复历史方块状态，支持排除/仅指定方块、独立控制水与岩浆
- **撤销回档**：任意一次回档会话都可撤销，方块与日志状态一并恢复
- **特殊场景处理**：骨粉催熟（树消失/作物退回）、桶倒水、海绵吸水、含水方块（waterlogged）清水、掉落物清理
- **未加载区块自动传送**：回档遇到未加载区块时把发起者传送到目标区块触发加载，加载后继续
- **可视化选区**：粒子边框实时渲染（仅本人可见），双工具选点
- **细粒度玩家权限**：9 项权限（选区/回档/选区查询/撤销/撤销他人/记录/文件日志/数据库查询/状态）逐项控制，支持全局默认 + 单玩家单独设置（以单独为准），游戏内表单管理
- **游戏内表单 UI**：主菜单、回档、回档记录、日志中心（文件浏览 + 数据库查询）、权限管理、配置编辑（保存即热生效）、数据库管理
- **每日分类日志文件**：按日期 / 玩家 / 分类分层的人类可读中文日志，自动压缩归档
- **数据库轮换**：当前库一键转归档、从空库开始，归档可随时恢复
- **性能保护**：内存缓冲 + 后台线程落盘、流式分批回档、区块安全检查，避免 TPS 波动与崩溃

## 环境要求

- Bedrock Dedicated Server + [Endstone](https://endstone.dev) >= 0.11（推荐 0.11.8+）
- Python >= 3.10

> Endstone < 0.11.8 存在物品堆读取段错误缺陷（[Endstone #469](https://github.com/EndstoneMC/endstone/issues/469)），插件会自动降级掉落物清理的校验方式规避，不影响使用。

## 安装

从 [Releases](https://github.com/gxh6438/MXBack/releases) 下载最新版 `.whl`，放入 `plugins/` 目录（或 `pip install` 后使用）。

启动服务器后自动生成 `plugins/mxback/config.json`（默认配置）与数据目录。

## 快速上手

1. 进入手持任意方块，输入 `/mxback` 打开主菜单；或直接 `/mxback start` 开启选区模式
2. 手持**木斧**右键依次点击两个方块，选定回档区域（完成选区后自动弹出操作表单）
3. 选择「选区回档」，设定时间（如 30 分钟），确认执行
4. 回档在后台分批执行，完成后收到通知；输错了？`/mxback undo` 一键撤销

## 命令

| 命令 | 说明 |
|---|---|
| `/mxback` | 打开主菜单（全部功能入口） |
| `/mxback start` | 开始选区模式（选区工具生效） |
| `/mxback stop` | 停止选区模式（工具点击失效，清除选区与边框） |
| `/mxback menu` | 当前选区的操作选择（回档 / 查看选区内日志） |
| `/mxback undo [编号]` | 撤销最近一次（或指定编号）回档 |
| `/mxback history` | 查看回档记录并撤销任意一次 |
| `/mxback log` / `lookup` | 日志中心（日志文件浏览 + 数据库查询） |
| `/mxback config` / `settings` | 配置表单（所有配置项，保存即热生效） |
| `/mxback perm` | 权限管理（全局默认 + 单玩家设置，仅 OP） |
| `/mxback status` | 运行状态统计 |
| `/mxback compress [策略]` | 立即压缩旧日志（gzip / bz2 / xz / auto） |
| `/mxback purge <天数>` | 清理数据库中 N 天前的记录 |
| `/mxback db [new\|list\|restore]` | 数据库管理（新建 / 归档列表 / 恢复） |
| `/mxback reload` | 从磁盘重载配置文件 |
| `/mxback help` | 命令帮助 |

基础命令需要 `mxback.use` 权限（默认所有人）。管理类子命令（perm / config / compress / purge / db / reload）仅 OP 与控制台可用；功能类子命令按细粒度玩家权限门控（见下节）。

## 选区工具

默认配置下：

| 操作 | 效果 |
|---|---|
| `/mxback start` 后手持**木斧右键** | 依次选择第一点、第二点 |
| 选区完成后木斧右键 | 修改第一点 |
| 选区完成后**木棍**右键 | 修改第二点 |
| 木斧左键 | 退出选区模式 |
| 跨维度选点 | 自动重置选区 |

选区完成时弹出操作表单，并以粒子渲染选区边框（仅本人可见）。体积上限、Y 范围、工具物品均可在配置中修改。

## 玩家权限管理

细粒度权限系统，普通玩家（非 OP）的功能全部按权限项逐一控制。判定规则：

```
玩家单独设置 > 全局默认；未单独设置的项跟随全局默认；OP / 控制台恒为允许
```

### 权限项（9 项）

| 权限 | 控制 |
|---|---|
| `selection` 选区模式 | 选区工具选点、粒子边框（`/mxback start`、`/mxback stop`） |
| `rollback` 选区回档 | 对已选区域执行回档 |
| `selection_lookup` 选区日志查询 | 查看选区内的方块变更记录 |
| `undo` 撤销自己的回档 | `/mxback undo` 与回档记录中撤销自己的会话 |
| `undo_others` 撤销他人的回档 | 查看全部回档记录并撤销任何人的会话（协管授权） |
| `history` 查看回档记录 | `/mxback history` 回档历史列表 |
| `lookup_files` 日志文件浏览 | 按日期/玩家/分类浏览每日日志文件 |
| `lookup_db` 数据库查询 | 按分类/玩家/时间窗查询数据库记录 |
| `status` 运行状态 | `/mxback status` 运行统计 |

### 设置方式

**全局默认**（统一配置所有普通玩家）：`config.json` → `player_permissions`，或游戏内 `/mxback perm` → 全局默认权限，也可在 `/mxback config` 表单修改，保存即热生效。

**单玩家单独设置**（以单独为准）：`permissions.json` → `players`，或游戏内 `/mxback perm` → 选择玩家（在线列表 / 按名字添加，支持离线玩家）→ 逐项开关。提交时仅记录与当前生效值不同的项为单独设置；「清除全部单独设置」让该玩家恢复跟随全局。

```json
// plugins/mxback/permissions.json
{
  "players": {
    "Steve": { "rollback": true, "undo": true, "lookup_db": true }
  }
}
```

上例：Steve 的回档/撤销/数据库查询按单独设置放行，其余 6 项跟随全局默认。

### 权限与界面联动

菜单按钮按实际权限动态显示：仅有日志查询权限的玩家不会看到回档入口，仅有回档权限的玩家在日志中心只会看到被授权的入口（文件浏览 / 数据库查询分开控制）。授权中途撤销立即生效，选区工具也会即时失效。

| 功能 | OP / 控制台 | 普通玩家 |
|---|---|---|
| 选区与选点 | ✔ | `selection` |
| 选区回档 | ✔ | `rollback` |
| 选区日志查询 | ✔ | `selection_lookup` |
| 撤销自己的回档 | ✔ | `undo` |
| 撤销他人回档 / 看全部记录 | ✔ | `undo_others` |
| 查看回档记录 | ✔ | `history`（或 `undo` / `undo_others`） |
| 日志文件浏览 | ✔ | `lookup_files` |
| 数据库查询 | ✔ | `lookup_db` |
| 运行状态 | ✔ | `status` |
| 配置 / 权限管理 / 压缩 / 清库 / 数据库管理 / 重载 | ✔ | ✘ |

全部权限默认关闭（普通玩家仅能打开主菜单与帮助）。

## 回档机制详解

### 时间语义

回档到「N 时间前」= 恢复区域内所有方块到该时刻的状态。同一坐标只处理时间窗内**最早**一条记录：例如 5 分钟前放了方块、挖掉、再放、再挖，回档 30 分钟 = 恢复为空气（该处本来就是空气），不会错误复原不存在的方块。

### no-op 检测

目标状态与当前状态完全一致（含方块状态字典精确比较）时跳过实际写入。全部记录均无变化则直接提示「没有可恢复的操作」，不产生撤销快照、不写恢复计数。

### 水与含水方块（Waterlogging）

基岩版含水方块的水在层 1，直接复原会把水封进方块里。插件使用三阶段流水线（置空 → 等待归一化 → 复原）+ 复原后观察 + 滚动复检，确保清水彻底、液体不回流。

### 未加载区块

回档遇到未加载区块时（默认开启 `rollback.auto_teleport`）：把发起者传送到目标区块质心的地表（防窒息），等待加载完成后继续处理；超时或传送失败按失败计，不阻塞其余方块。

### 掉落物清理

回档后自动清理区域内被破坏方块的残留掉落物，按破坏时记录的物品指纹（物品 + 数量）匹配，宁少清勿误清。可配置关闭。

### 撤销

每次回档记录撤销快照。`/mxback undo` 撤销最近一次，`/mxback history` 表单中可撤销任意一次（OP 可撤销任何人的）。撤销后相关日志恢复为「未回档」状态，可再次回档。

### 容错

回档期间发起者传送、切维度、退服均不影响执行（引擎只按名字在需要时重解析玩家）；维度被卸载则安全中止并记录。

## 日志系统

### 数据库（SQLite，WAL 模式）

- `block_log`：方块变更（可回档），含变化前/后方块与状态
- `event_log`：玩家行为与世界事件（仅查询）
- `session_log` / `undo_log`：回档会话与撤销快照

### 每日分类日志文件

```
logs/YYYY-MM-DD/
├── break.log          # 破坏（示例：[14:23:01] Steve 破坏了 石头 于主世界 (100, 64, -20)）
├── place.log          # 放置（含变化前方块）
├── explosion.log      # 爆炸摧毁
├── container.log      # 容器交互
├── click.log          # 门/按钮/拉杆交互
├── world.log          # 世界事件（枯萎/生长/凝固/流动/活塞/天气…）
├── chat.log / command.log / session.log / kill.log / item.log / player.log
├── rollback.log       # 回档与撤销记录
└── players/<玩家名>/  # 每个玩家的日志独立分层（可搜索）
archives/              # 自动压缩的历史日志（tar.gz 等）
```

- 每日 04:00 自动压缩今天之前的日志（策略可配：auto = 近期 gzip、更早 xz）
- 压缩包保留天数可配，0 = 永久
- 游戏内 `/mxback log` 可浏览任意历史日期，按玩家/分类分页查看

### 数据库管理（`/mxback db`）

- **新建数据库**：当前库整体转归档（自动后台压缩），从空库开始；适合开新周目或换季存档
- **归档列表**：查看每个归档的时间、大小、记录数、压缩状态
- **恢复**：把归档换回为现行库（当前库自动转归档，数据不丢），适合回看/回档历史数据

## 配置

`plugins/mxback/config.json`，全部可在游戏内 `/mxback config` 表单修改，保存即热生效并写回磁盘。缺省键自动用默认值补齐。

### 通用

| 键 | 默认 | 说明 |
|---|---|---|
| `language` | `zh_CN` | 方块/实体/维度名称的翻译语言 |
| `wand_item` | `minecraft:wooden_axe` | 选区工具（第一点 / 退出） |
| `containers` | （清单） | 容器交互日志识别的方块 ID |

### selection（选区）

| 键 | 默认 | 说明 |
|---|---|---|
| `wand_item_2` | `minecraft:stick` | 第二点修改工具 |
| `menu_open_item` | `minecraft:wooden_axe` | 未开启选区模式时右键开主菜单的物品 |
| `require_start` | `true` | 需先 `/mxback start` 工具才生效 |
| `ground_click_menu` | `false` | 未开启选区模式时右键方块打开主菜单 |
| `max_volume` | `32768` | 选区最大体积（方块数） |
| `min_y` / `max_y` | `-64` / `319` | 选区 Y 范围 |
| `click_debounce_ms` | `250` | 选点防抖窗口（毫秒），PC 端一次右键会连发两次交互事件，窗口内的重复触发被忽略；设 `0` 关闭 |

### rollback（回档与性能）

| 键 | 默认 | 说明 |
|---|---|---|
| `max_records` | `5000` | 单次回档最多记录条数（超出截断） |
| `max_time_days` | `30` | 回档时间窗上限（天） |
| `blocks_per_batch` | `400` | 每批应用方块数（防单 tick 卡顿） |
| `batch_interval_ticks` | `1` | 批次间隔 tick |
| `cleanup_drops` | `true` | 回档后清理区域内残留掉落物 |
| `drop_verify_type` | `true` | 掉落物按类型校验（旧版 Endstone 自动关闭） |
| `rollback_water` / `rollback_lava` | `true` | 是否恢复水 / 岩浆 |
| `exclude_blocks` | `""` | 不回档的方块（逗号分隔 ID） |
| `only_blocks` | `""` | 仅回档这些方块（与排除互斥，都填以排除为准） |
| `auto_teleport` | `true` | 未加载区块时传送发起者触发加载 |
| `teleport_wait_ticks` | `200` | 传送后等待区块加载的 tick 上限 |

### performance（性能）

| 键 | 默认 | 说明 |
|---|---|---|
| `async_flush` | `true` | 后台线程写数据库与日志文件（重启生效） |
| `flush_interval_ticks` | `100` | 落盘间隔（100 tick = 5 秒） |

### particles（粒子边框）

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 渲染选区边框 |
| `type` | `minecraft:basic_flame_particle` | 粒子 ID |
| `interval_ticks` | `10` | 刷新间隔 |
| `density` | `0.75` | 边框密度（每多少格一个点） |
| `max_points` | `600` | 单次刷新粒子总数上限 |

### database（数据库归档）

| 键 | 默认 | 说明 |
|---|---|---|
| `archive_compress` | `true` | 归档库后台压缩 |
| `archive_algorithm` | `gzip` | 归档压缩算法 |

### logs（日志）

| 键 | 默认 | 说明 |
|---|---|---|
| `categories.<分类>` | 见下表 | 30 项日志分类逐一开关 |
| `daily_files` | `true` | 生成每日分类日志文件 |
| `per_player_files` | `true` | 玩家日志独立分层目录 |
| `auto_compress` | `true` | 每日自动压缩旧日志 |
| `compress_hour` | `4` | 自动压缩触发小时（0-23） |
| `strategy` | `auto` | 压缩策略（gzip / bz2 / xz / auto） |
| `auto_gzip_days` | `7` | auto 策略：N 天内 gzip，超出 xz |
| `keep_archives_days` | `0` | 压缩包保留天数（0 = 永久） |

日志分类默认值：**开启** — 破坏、放置、爆炸、凝固、液体流动、容器交互、骨粉、聊天、命令、上下线、击杀、物品丢弃/拾取、插件启停；**关闭** — 树叶枯萎、作物生长、门/按钮交互、右键实体、吃/喝、游戏模式、传送、上床、活塞、烤制、天气、广播、跨维度、重生、表情。

### player_permissions（玩家权限全局默认）

9 项普通玩家权限的统一默认值（详见「玩家权限管理」章节），全部默认关闭：

| 键 | 默认 | 说明 |
|---|---|---|
| `selection` | `false` | 选区模式与选点工具 |
| `rollback` | `false` | 选区回档 |
| `selection_lookup` | `false` | 选区日志查询 |
| `undo` | `false` | 撤销自己的回档 |
| `undo_others` | `false` | 撤销他人的回档（协管授权） |
| `history` | `false` | 查看回档记录 |
| `lookup_files` | `false` | 日志文件浏览 |
| `lookup_db` | `false` | 数据库查询 |
| `status` | `false` | 运行状态查看 |

单玩家覆盖存于 `permissions.json`（`/mxback perm` 界面管理），以单独设置为准。

## 数据目录结构

```
plugins/mxback/
├── config.json     # 配置（含 player_permissions 全局默认权限）
├── permissions.json # 单玩家权限覆盖（以单独设置为准）
├── mxback.db       # SQLite 数据库（WAL）
├── db_archive/     # 归档数据库（.db / 压缩 + .info 边车）
├── logs/           # 每日分类日志（按日期/玩家分层）
├── archives/       # 压缩的历史日志
└── lang/zh_cn.json # 本地翻译映射（可自行补充）
```

## 性能与稳定性设计

- **主线程零 IO**：事件回调只做内存入队，数据库写入与日志文件 IO 全部由后台线程执行
- **流式分批回档**：数据库游标流式读取，每批 400 方块间隔 1 tick，内存占用 O(单批)
- **区块安全检查**：所有延迟回调访问方块前复查区块加载状态，杜绝未加载区块悬空引用段错误
- **不缓存跨 tick 引用**：Dimension/Block 等 pybind 视图绝不跨 tick 持有
- **关服安全**：停机标志 + 任务先行取消 + 缓冲强制落盘，最后几秒日志不丢
- **高频事件排除**：PlayerMoveEvent 等刻意不记录，避免拖垮 TPS

## 已知限制

- 容器**内容物**因 Endstone API 限制无法记录与恢复（仅记录交互行为）
- 回档不恢复实体（生物、掉落物中的非破坏来源物品）
- 异步落盘开关变更需重启服务器完全生效
- `/mxback db restore` 指定归档需在游戏内表单操作（命令行参数长度放不下）

## 从源码构建

```bash
git clone https://github.com/gxh6438/MXBack.git
cd MXBack
pip install build
python -m build --wheel
```

产物在 `dist/`。推送 `v*` 标签会自动触发 GitHub Actions 构建并发布 Release（.whl）。

## 许可

本项目基于 [MIT License](LICENSE) 开源。

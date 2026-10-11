"""名称翻译：优先 BDS 内置语言文件，本地 JSON 兜底。"""

import json
from pathlib import Path
from typing import Any, Optional

from endstone.block import BlockType


class Lang:
    """方块/实体/维度/动作 ID -> 本地化名称。

    查找顺序：内存缓存 -> server.language.translate -> lang/zh_cn.json -> 原始 ID。
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self.locale: str = plugin.cfg.get("language", default="zh_CN")
        self.fallback: dict[str, Any] = {}
        self._cache: dict[str, str] = {}
        self.i18n_available: bool = False
        self._probed: bool = False
        self._load_fallback()
        # 探测必须延迟到首次 block_name()：STARTUP 阶段方块注册表未初始化，
        # 此时 BlockType.get 会触发底层 SIGSEGV（无法被 try 捕获）

    def _load_fallback(self) -> None:
        """加载本地映射：包内资源为底，数据目录副本覆盖其上。"""
        base: dict[str, Any] = {}
        try:
            import importlib.resources as res

            pkg_file = res.files("endstone_mxback") / "lang" / "zh_cn.json"
            if pkg_file.is_file():
                base = json.loads(pkg_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ModuleNotFoundError):
            base = {}

        user_file = Path(self.plugin.data_folder) / "lang" / "zh_cn.json"
        overlay: dict[str, Any] = {}
        if user_file.is_file():
            try:
                overlay = json.loads(user_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                overlay = {}
        else:
            # 首次运行：释放包内映射到数据目录，方便用户补充
            try:
                self.plugin.save_resources("lang/zh_cn.json")
            except (FileNotFoundError, OSError):
                pass

        self.fallback = base
        for section, values in overlay.items():
            if isinstance(values, dict):
                merged = dict(base.get(section) or {})
                merged.update(values)
                self.fallback[section] = merged
            else:
                self.fallback[section] = values

    def _ensure_probed(self) -> None:
        """惰性探测服务器端翻译（只能在服务器完全启动后调用）。"""
        if self._probed:
            return
        self._probed = True
        try:
            # 用 chest 的真实 key 探测，避免误判
            key = BlockType.get("minecraft:chest").translation_key + ".name"
            translated = self.plugin.server.language.translate(key, None, self.locale)
            self.i18n_available = bool(translated) and translated != key
        except Exception:
            self.i18n_available = False
        self.plugin.logger.info(
            f"服务器端翻译{'可用' if self.i18n_available else '不可用'}"
            f"（{self.locale}），方块/实体将使用"
            f"{'官方' if self.i18n_available else '本地映射兜底的'}名称"
        )

    def translatable_text(self, value) -> str:
        """Endstone 的事件属性可能是 str 或 Translatable（如死亡消息、
        广播消息）。Translatable 是 pybind 对象，无法写入 SQLite（会让
        整批日志落盘失败丢失），必须先转换为本地化纯文本；任何情况下
        都不允许 ``<...object at 0x...>`` 落盘。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value

        # Translatable：text = 翻译键（如 death.attack.mob），params = 参数
        text = ""
        params: list[str] = []
        try:
            text = getattr(value, "text", "") or ""
            if not isinstance(text, str):
                text = str(text)
        except Exception:
            text = ""
        try:
            raw_params = getattr(value, "params", None) or []
            if isinstance(raw_params, (list, tuple)):
                # 参数可能嵌套 Translatable（极罕见），递归转纯文本
                params = [self.translatable_text(p) for p in raw_params]
        except Exception:
            params = []

        # 1) 服务器端翻译最准确（如「Steve 被 Zombie 杀死了」）；
        #    旧版 Endstone 无 Translatable 重载 / 语言模块异常时抛错走 2)
        try:
            translated = self.plugin.server.language.translate(
                value, self.locale
            )
            if isinstance(translated, str) and translated:
                return translated
        except Exception:
            pass

        # 2) 翻译失败：翻译键 + 参数还原可读内容；全部为空时占位符兜底，
        #    绝不输出 <endstone._python.lang.Translatable object at 0x...>
        if text and params:
            return f"{text} ({', '.join(params)})"
        if text:
            return text
        if params:
            return ", ".join(params)
        return "(无法翻译的消息)"

    def block_name(self, block_id: str) -> str:
        if not block_id:
            return "未知"
        if block_id in self._cache:
            return self._cache[block_id]
        self._ensure_probed()
        name = self._translate_block_via_i18n(block_id)
        if name is None:
            name = self.fallback.get("blocks", {}).get(block_id, block_id)
        self._cache[block_id] = name
        return name

    def entity_name(self, entity_id: str) -> str:
        if not entity_id:
            return "未知"
        return self.fallback.get("entities", {}).get(entity_id, entity_id)

    def dimension_name(self, dimension_id: str) -> str:
        if not dimension_id:
            return "未知"
        return self.fallback.get("dimensions", {}).get(dimension_id, dimension_id)

    def action_name(self, action: str) -> str:
        return self.fallback.get("actions", {}).get(action, action)

    def _translate_block_via_i18n(self, block_id: str) -> Optional[str]:
        """translation_key 形如 'tile.chest'，语言文件条目带 '.name' 后缀。"""
        if not self.i18n_available:
            return None
        try:
            key = BlockType.get(block_id).translation_key
            for candidate in (key + ".name", key):
                translated = self.plugin.server.language.translate(
                    candidate, None, self.locale
                )
                if translated and translated != candidate:
                    return translated
        except Exception:
            return None
        return None

# app/core/timezone.py
# 时间管理器 — 全局单例，优先基于环境变量 TZ 计算时区偏移
# 所有时间字段存储为 TEXT 格式 YYYY-MM-DD HH:MM:SS

import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

# 时间存储格式
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class TimeManager:
    """全局时间管理器 — 单例模式"""

    _instance: Optional["TimeManager"] = None
    _tz_offset: timedelta
    _tz_info: timezone

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_timezone()
        return cls._instance

    def _init_timezone(self):
        """从环境变量读取时区配置并初始化"""
        tz_str = (
            os.getenv("TZ")
            or os.getenv("MISAKAMF_TZ")
            or os.getenv("MISAKAMF_TIMEZONE")
            or "Asia/Shanghai"
        )
        try:
            # 尝试解析 IANA 时区名（如 Asia/Shanghai）
            tz = ZoneInfo(tz_str)
            # 计算当前偏移量
            self._tz_offset = datetime.now(tz).utcoffset()
            self._tz_info = timezone(self._tz_offset)
        except Exception:
            # 尝试解析偏移量格式（如 +08:00, -05:30）
            try:
                sign = 1 if tz_str[0] == "+" else -1
                parts = tz_str.lstrip("+-").split(":")
                hours = int(parts[0])
                minutes = int(parts[1]) if len(parts) > 1 else 0
                self._tz_offset = timedelta(hours=hours * sign, minutes=minutes * sign)
                self._tz_info = timezone(self._tz_offset)
            except Exception:
                # 最终回退到 UTC+8
                self._tz_offset = timedelta(hours=8)
                self._tz_info = timezone(self._tz_offset)

    def now(self) -> str:
        """获取当前时间的 TEXT 字符串（已偏移时区）"""
        utc_now = datetime.now(timezone.utc)
        local_now = utc_now + self._tz_offset
        return local_now.strftime(TIME_FORMAT)

    def now_datetime(self) -> datetime:
        """获取当前时间的 datetime 对象（无时区信息的本地时间）"""
        utc_now = datetime.now(timezone.utc)
        local_now = utc_now + self._tz_offset
        return local_now.replace(tzinfo=None)

    def format(self, dt: datetime) -> str:
        """将 datetime 格式化为 TEXT"""
        return dt.strftime(TIME_FORMAT)

    def parse(self, text: str) -> datetime:
        """将 TEXT 解析为 datetime"""
        return datetime.strptime(text, TIME_FORMAT)

    @property
    def tz_offset_str(self) -> str:
        """返回时区偏移描述，如 '+08:00'"""
        total_seconds = int(self._tz_offset.total_seconds())
        hours, remainder = divmod(abs(total_seconds), 3600)
        minutes = remainder // 60
        sign = "+" if total_seconds >= 0 else "-"
        return f"{sign}{hours:02d}:{minutes:02d}"


# 全局单例
tm = TimeManager()


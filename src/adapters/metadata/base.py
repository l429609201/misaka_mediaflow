# src/adapters/metadata/base.py
# 元数据源抽象基类 — 可插拔加载
#
# 新增元数据源只需:
#   1. 在 src/adapters/metadata/ 下新建文件 (如 douban.py)
#   2. 继承 MetadataProvider，实现抽象方法
#   3. 在 factory.py 的 _REGISTRY 注册
#
# 配置统一存 SystemConfig 表 (key = "metadata_<provider_name>")

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class MetaFieldSpec:
    """
    元数据 Provider 配置字段规格。
    与 storage.FieldSpec 对齐，Provider 通过类属性 CONFIG_FIELDS 声明字段，
    /search-source/discover 接口把 fields 返回给前端，前端动态渲染，无需硬编码。
    """
    key: str                                              # 配置 JSON 中的键名
    label: str                                            # 前端显示标签
    type: Literal['text', 'password', 'textarea'] = 'text'
    required: bool = False
    secret: bool = False
    placeholder: str = ""
    hint: str = ""
    default: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "secret": self.secret,
            "placeholder": self.placeholder,
            "hint": self.hint,
            "default": self.default,
        }


@dataclass
class MetadataResult:
    """元数据查询结果 — 所有 Provider 统一返回此格式"""
    provider: str = ""              # 来源: tmdb / douban / bangumi
    media_type: str = ""            # movie / tv
    tmdb_id: int = 0
    imdb_id: str = ""
    title: str = ""
    original_title: str = ""
    year: int = 0
    overview: str = ""
    poster_url: str = ""
    backdrop_url: str = ""
    genres: list = field(default_factory=list)
    vote_average: float = 0.0
    # 额外数据（各 Provider 自行扩展）
    extra: dict = field(default_factory=dict)


class MetadataProvider(ABC):
    """元数据源抽象基类"""

    # 子类必须设置
    PROVIDER_NAME: str = ""
    DISPLAY_NAME: str = ""
    CONFIG_KEY: str = ""            # SystemConfig 表中的 key

    # 子类覆盖此属性声明自己的配置字段，discover 接口将其返回给前端动态渲染
    CONFIG_FIELDS: list[MetaFieldSpec] = []

    @abstractmethod
    async def search(self, query: str, media_type: str = "movie", year: int = 0) -> list[MetadataResult]:
        """
        搜索。

        Args:
            query: 搜索关键词
            media_type: "movie" / "tv"
            year: 可选年份过滤

        Returns:
            MetadataResult 列表（按相关性排序）
        """
        ...

    @abstractmethod
    async def get_detail(self, media_id: int | str, media_type: str = "movie") -> MetadataResult | None:
        """
        获取详情。

        Args:
            media_id: 该 Provider 的 ID（TMDB ID / 豆瓣 ID / Bangumi ID）
            media_type: "movie" / "tv"

        Returns:
            MetadataResult 或 None
        """
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """测试连接（验证 API Key 是否有效等）"""
        ...

    @property
    @abstractmethod
    def available(self) -> bool:
        """是否可用（API Key 已配置等）"""
        ...

    # ── 可选方法（子类按需覆盖）──

    async def get_images(self, media_id: int | str, media_type: str = "movie") -> dict:
        """获取图片（海报、背景等），默认返回空"""
        return {"posters": [], "backdrops": []}

    async def find_by_external_id(self, external_id: str, source: str = "imdb") -> MetadataResult | None:
        """通过外部 ID 查找，默认不支持"""
        return None

    async def enrich(self, title: str, year: int = 0, media_type: str = "movie") -> MetadataResult | None:
        """
        搜索 + 取第一个结果的详情 — 一步到位补充元数据。
        默认实现：search → 取第一个 → get_detail
        """
        results = await self.search(title, media_type, year)
        if not results:
            return None
        first = results[0]
        # 如果 search 已经够详细就直接返回
        if first.tmdb_id or first.imdb_id:
            return first
        # 否则查详情
        media_id = first.extra.get("id") or first.tmdb_id
        if media_id:
            return await self.get_detail(media_id, media_type)
        return first


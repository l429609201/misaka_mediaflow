# app/adapters/storage/base.py
# 存储适配器抽象基类

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class FieldSpec:
    """
    存储适配器配置字段规格描述。
    适配器通过类属性 CONFIG_FIELDS 声明自己需要哪些字段，
    API /storage/meta 接口把这些规格返回给前端，
    前端据此动态渲染表单，无需任何硬编码。
    """
    key: str                                                    # config JSON 里的键名
    label: str                                                  # 前端显示标签
    type: Literal['text', 'password', 'textarea', 'select']    # 输入组件类型
    required: bool = False                                      # 是否必填
    secret: bool = False                                        # True → 读取时脱敏
    placeholder: str = ""                                       # 输入框占位文字
    hint: str = ""                                              # 字段下方帮助文字
    default: str = ""                                           # 默认值
    options: list = field(default_factory=list)                  # select 类型的选项 [{"value":"x","label":"X"},...]
    show_when: dict = field(default_factory=dict)                # 条件显示 {"auth_mode":"token"} → 仅 auth_mode=token 时显示

    def to_dict(self) -> dict:
        d = {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "secret": self.secret,
            "placeholder": self.placeholder,
            "hint": self.hint,
            "default": self.default,
        }
        if self.options:
            d["options"] = self.options
        if self.show_when:
            d["show_when"] = self.show_when
        return d


@dataclass
class DirectLink:
    """302 直链响应"""
    url: str = ""
    headers: dict = field(default_factory=dict)
    expires_in: int = 900          # 秒
    file_name: str = ""
    file_size: int = 0
    content_type: str = ""


@dataclass
class FileEntry:
    """文件/目录条目"""
    name: str = ""
    path: str = ""
    size: int = 0
    is_dir: bool = False
    pick_code: str = ""            # 115 专属
    sha1: str = ""                 # 115 专属
    file_id: str = ""
    ed2k: str = ""                 # 115 ed2k 哈希
    mtime: str = ""                # 115 修改时间 (TEXT)
    ctime: str = ""                # 115 创建时间 (TEXT)


class StorageAdapter(ABC):
    """所有存储适配器的统一接口"""

    # 子类覆盖此属性来声明自己的配置字段规格
    CONFIG_FIELDS: list[FieldSpec] = []

    @abstractmethod
    async def get_direct_link(self, cloud_path: str, **kwargs) -> DirectLink:
        """获取 302 直链"""
        ...

    @abstractmethod
    async def list_files(self, cloud_path: str) -> list[FileEntry]:
        """列出目录内容"""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """测试连接"""
        ...

    @abstractmethod
    async def get_space_usage(self) -> dict:
        """获取存储用量 {"total": int, "used": int, "free": int}"""
        ...


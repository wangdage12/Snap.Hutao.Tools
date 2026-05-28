# -*- coding: utf-8 -*-
"""
UIGF 转换器基类
定义所有转换器必须实现的接口
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SourceInfo:
    """来源信息"""
    name: str  # 显示名称
    identifier: str  # 唯一标识符
    description: str = ""  # 描述


class BaseConverter(ABC):
    """
    UIGF 转换器基类
    
    所有转换器必须继承此类并实现以下方法：
    - get_source_info(): 返回来源信息
    - detect(): 检测输入数据是否匹配此来源
    - convert(): 将输入数据转换为 UIGF v4.1 格式
    """
    
    @classmethod
    @abstractmethod
    def get_source_info(cls) -> SourceInfo:
        """
        获取此转换器对应的来源信息
        
        Returns:
            SourceInfo: 包含名称、标识符和描述的来源信息
        """
        pass
    
    @classmethod
    @abstractmethod
    def detect(cls, data: dict) -> bool:
        """
        检测输入数据是否来自此来源
        
        Args:
            data: 解析后的 JSON 数据
            
        Returns:
            bool: 如果数据匹配此来源返回 True
        """
        pass
    
    @classmethod
    @abstractmethod
    def convert(cls, data: dict) -> dict:
        """
        将输入数据转换为 UIGF v4.1 格式
        
        Args:
            data: 解析后的 JSON 数据
            
        Returns:
            dict: UIGF v4.1 格式的数据
            
        Raises:
            ConversionError: 转换过程中出错
        """
        pass
    
    @classmethod
    def get_display_name(cls) -> str:
        """获取显示名称"""
        return cls.get_source_info().name
    
    @classmethod
    def get_identifier(cls) -> str:
        """获取唯一标识符"""
        return cls.get_source_info().identifier


class ConversionError(Exception):
    """转换错误"""
    pass

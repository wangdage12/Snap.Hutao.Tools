# -*- coding: utf-8 -*-
"""
转换器注册表
管理所有已注册的转换器，提供自动检测功能
"""

from typing import Optional, Type, Dict, List

from .base import BaseConverter


class ConverterRegistry:
    """
    转换器注册表
    
    用于管理所有已注册的转换器，支持自动检测输入数据来源
    """
    
    _converters: Dict[str, Type[BaseConverter]] = {}
    
    @classmethod
    def register(cls, converter_class: Type[BaseConverter]) -> Type[BaseConverter]:
        """
        注册转换器（可作为装饰器使用）
        
        Args:
            converter_class: 转换器类
            
        Returns:
            返回转换器类本身（支持装饰器用法）
        """
        identifier = converter_class.get_identifier()
        cls._converters[identifier] = converter_class
        return converter_class
    
    @classmethod
    def get(cls, identifier: str) -> Optional[Type[BaseConverter]]:
        """
        根据标识符获取转换器
        
        Args:
            identifier: 转换器标识符
            
        Returns:
            转换器类，如果不存在则返回 None
        """
        return cls._converters.get(identifier)
    
    @classmethod
    def get_all(cls) -> Dict[str, Type[BaseConverter]]:
        """获取所有已注册的转换器"""
        return cls._converters.copy()
    
    @classmethod
    def get_display_names(cls) -> List[str]:
        """获取所有转换器的显示名称列表"""
        return [conv.get_display_name() for conv in cls._converters.values()]
    
    @classmethod
    def detect_source(cls, data: dict) -> Optional[Type[BaseConverter]]:
        """
        自动检测数据来源
        
        Args:
            data: 解析后的 JSON 数据
            
        Returns:
            匹配的转换器类，如果没有匹配则返回 None
        """
        for converter in cls._converters.values():
            try:
                if converter.detect(data):
                    return converter
            except Exception:
                continue
        return None
    
    @classmethod
    def get_identifier_by_display_name(cls, display_name: str) -> Optional[str]:
        """
        根据显示名称获取标识符
        
        Args:
            display_name: 显示名称
            
        Returns:
            标识符，如果不存在则返回 None
        """
        for identifier, converter in cls._converters.items():
            if converter.get_display_name() == display_name:
                return identifier
        return None


def register_converter(converter_class: Type[BaseConverter]) -> Type[BaseConverter]:
    """
    注册转换器的便捷函数（装饰器）
    
    Args:
        converter_class: 转换器类
        
    Returns:
        转换器类本身
    """
    return ConverterRegistry.register(converter_class)


def get_converter(identifier: str) -> Optional[Type[BaseConverter]]:
    """
    获取转换器的便捷函数
    
    Args:
        identifier: 转换器标识符
        
    Returns:
        转换器类
    """
    return ConverterRegistry.get(identifier)


def detect_source_type(data: dict) -> Optional[Type[BaseConverter]]:
    """
    自动检测数据来源的便捷函数
    
    Args:
        data: 解析后的 JSON 数据
        
    Returns:
        匹配的转换器类
    """
    return ConverterRegistry.detect_source(data)

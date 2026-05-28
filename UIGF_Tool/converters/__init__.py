# -*- coding: utf-8 -*-
"""
UIGF 转换器模块
提供可扩展的转换器注册和自动检测功能
"""

from .base import BaseConverter, SourceInfo, ConversionError
from .heybox import HeyboxConverter
from .registry import ConverterRegistry, register_converter, get_converter, detect_source_type

__all__ = [
    "BaseConverter",
    "SourceInfo",
    "ConversionError",
    "HeyboxConverter",
    "ConverterRegistry",
    "register_converter",
    "get_converter",
    "detect_source_type",
]

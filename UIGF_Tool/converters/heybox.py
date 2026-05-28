# -*- coding: utf-8 -*-
"""
小黑盒转换器
将小黑盒导出的 UIGF v3.0 格式转换为 UIGF v4.1 格式
"""

from collections import defaultdict
from datetime import datetime
from typing import Optional

from .base import BaseConverter, SourceInfo, ConversionError
from .registry import register_converter


@register_converter
class HeyboxConverter(BaseConverter):
    """
    小黑盒转换器
    
    支持将小黑盒导出的 UIGF v3.0 格式转换为 UIGF v4.1 格式
    """
    
    # 目标 UIGF 版本
    TARGET_VERSION = "v4.1"
    
    @classmethod
    def get_source_info(cls) -> SourceInfo:
        return SourceInfo(
            name="小黑盒",
            identifier="heybox",
            description="小黑盒导出的 UIGF v3.0 格式"
        )
    
    @classmethod
    def detect(cls, data: dict) -> bool:
        """
        检测是否为小黑盒导出的格式
        
        小黑盒特征：
        - info.export_app 为 "小黑盒"
        - info.uigf_version 为 "v3.0"
        - 使用 list 结构而非 hk4e 结构
        """
        info = data.get("info", {})
        
        # 检查 export_app
        export_app = info.get("export_app", "")
        if "小黑盒" in export_app:
            return True
        
        # 检查版本和结构
        uigf_version = info.get("uigf_version", "")
        has_list = "list" in data and isinstance(data["list"], list)
        has_hk4e = "hk4e" in data
        
        # v3.0 格式使用 list 结构
        if uigf_version == "v3.0" and has_list and not has_hk4e:
            return True
        
        return False
    
    @classmethod
    def convert(cls, data: dict) -> dict:
        """
        将 UIGF v3.0 格式转换为 v4.1 格式
        
        Args:
            data: 小黑盒导出的 UIGF v3.0 数据
            
        Returns:
            UIGF v4.1 格式的数据
        """
        try:
            return cls._do_convert(data)
        except Exception as e:
            raise ConversionError(f"转换失败: {str(e)}") from e
    
    @classmethod
    def _do_convert(cls, input_data: dict) -> dict:
        """执行实际的转换逻辑"""
        old_info = input_data.get("info", {})
        old_list = input_data.get("list", [])
        
        # 构建新的 info 结构
        export_timestamp = old_info.get("export_timestamp")
        if export_timestamp is None:
            export_timestamp = int(datetime.now().timestamp())
        
        new_info = {
            "export_timestamp": export_timestamp,
            "export_app": "UIGF Converter",
            "export_app_version": "1.0.0",
            "version": cls.TARGET_VERSION
        }
        
        # 按 uid 分组构建 hk4e 结构
        uid_entries = defaultdict(lambda: {
            "items": [],
            "lang": None,
            "timezone": 8
        })
        
        for item in old_list:
            uid = item.get("uid")
            if uid is None:
                continue
            
            # 构建 v4.1 格式的 item
            new_item = {
                "uigf_gacha_type": item.get("uigf_gacha_type"),
                "gacha_type": item.get("gacha_type"),
                "item_id": item.get("item_id"),
                "time": item.get("time"),
                "id": item.get("id")
            }
            
            uid_entries[uid]["items"].append(new_item)
            
            # 保留语言信息
            if uid_entries[uid]["lang"] is None:
                uid_entries[uid]["lang"] = item.get(
                    "lang", old_info.get("lang", "zh-cn")
                )
            
            # 保留时区信息
            if "region_time_zone" in old_info:
                uid_entries[uid]["timezone"] = old_info["region_time_zone"]
        
        # 构建 hk4e 数组
        hk4e = []
        for uid, entry_data in uid_entries.items():
            hk4e_entry = {
                "uid": int(uid) if uid else uid,
                "timezone": entry_data["timezone"],
                "lang": entry_data["lang"],
                "list": entry_data["items"]
            }
            hk4e.append(hk4e_entry)
        
        return {
            "info": new_info,
            "hk4e": hk4e
        }
    
    @classmethod
    def get_conversion_stats(cls, input_data: dict, output_data: dict) -> dict:
        """
        获取转换统计信息
        
        Args:
            input_data: 输入数据
            output_data: 输出数据
            
        Returns:
            包含统计信息的字典
        """
        old_list = input_data.get("list", [])
        hk4e = output_data.get("hk4e", [])
        
        total_input_items = len(old_list)
        total_output_items = sum(len(entry.get("list", [])) for entry in hk4e)
        uid_count = len(hk4e)
        
        return {
            "input_items": total_input_items,
            "output_items": total_output_items,
            "uid_count": uid_count,
            "source_app": input_data.get("info", {}).get("export_app", "未知"),
            "source_version": input_data.get("info", {}).get("uigf_version", "未知"),
            "target_version": cls.TARGET_VERSION
        }

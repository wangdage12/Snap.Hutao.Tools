from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import (
    ConversionError,
    MONSTER_CURVE_VALUE_MAP,
    MONSTER_SUB_HURT_FIELD_MAP,
    MONSTER_TYPE_MAP,
    PROP_TYPE_MAP,
    dump_json,
    load_json,
    logger,
    normalize_value,
)
from .remote import fetch_monster_details

def load_monster_reference_data(
    monster_path: Path,
) -> tuple[dict[int, dict[str, Any]], list[list[dict[str, Any]]]]:
    reference_index: dict[int, dict[str, Any]] = {}
    reference_lists: list[list[dict[str, Any]]] = []
    locale_root = monster_path.parent.parent
    for locale_monster_path in sorted(locale_root.glob("*/Monster.json")):
        if locale_monster_path == monster_path:
            continue
        try:
            locale_monster_list = load_json(locale_monster_path)
            if not isinstance(locale_monster_list, list):
                continue
            reference_lists.append(locale_monster_list)
            for entry in locale_monster_list:
                monster_id = entry.get("Id")
                if isinstance(monster_id, int) and monster_id > 0 and monster_id not in reference_index:
                    reference_index[monster_id] = entry
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"读取参考 Monster 失败: {locale_monster_path}, 错误: {exc}")
    return reference_index, reference_lists



def build_monster_describe_id(monster_id: int, reference_entry: dict[str, Any] | None = None) -> int:
    if isinstance(reference_entry, dict) and isinstance(reference_entry.get("DescribeId"), int):
        return reference_entry["DescribeId"]
    return (monster_id % 10000000) // 100



def resolve_monster_type(
    monster_type: str,
    local_legend: Any,
    reference_entry: dict[str, Any] | None = None,
) -> int:
    if isinstance(reference_entry, dict) and isinstance(reference_entry.get("Type"), int):
        return reference_entry["Type"]
    if local_legend is True:
        return 2
    if monster_type not in MONSTER_TYPE_MAP:
        raise ConversionError(f"未识别的怪物类型: {monster_type}")
    return MONSTER_TYPE_MAP[monster_type]



def resolve_monster_arkhe(reference_entry: dict[str, Any] | None = None) -> int:
    if isinstance(reference_entry, dict) and isinstance(reference_entry.get("Arkhe"), int):
        return reference_entry["Arkhe"]
    return 0



def resolve_monster_child(monster_id: int, child_map: dict[str, Any]) -> dict[str, Any]:
    child_data = child_map.get(str(monster_id))
    if isinstance(child_data, dict):
        return child_data

    child_candidates = sorted(

        [
            (int(child_key), child_data)
            for child_key, child_data in child_map.items()
            if str(child_key).isdigit() and isinstance(child_data, dict)
        ],
        key=lambda item: item[0],
    )
    if len(child_candidates) == 1:
        return child_candidates[0][1]
    raise ConversionError(f"怪物 {monster_id} 缺少匹配的 child 数据")



def build_monster_drops(reward: Any) -> list[int]:
    if not isinstance(reward, list):
        return []

    drops: list[int] = []
    for reward_item in reward:
        if not isinstance(reward_item, dict):
            continue
        reward_id = reward_item.get("id")
        if isinstance(reward_id, int) and reward_id not in drops:
            drops.append(reward_id)
    return drops



def build_monster_base_value(child_data: dict[str, Any]) -> dict[str, Any]:
    base = child_data.get("base")
    if not isinstance(base, dict):
        raise ConversionError("怪物缺少合法的基础属性数据")

    sub_hurt = child_data.get("sub_hurt")
    if not isinstance(sub_hurt, dict):
        raise ConversionError("怪物缺少合法的抗性数据")

    base_value = {}
    for source_key, target_key in (("hp", "HpBase"), ("atk", "AttackBase"), ("def", "DefenseBase")):
        value = base.get(source_key)
        if not isinstance(value, (int, float)):
            raise ConversionError(f"怪物缺少合法的基础属性字段: {source_key}")
        base_value[target_key] = value

    for source_key, target_key in MONSTER_SUB_HURT_FIELD_MAP.items():
        value = sub_hurt.get(source_key)
        if not isinstance(value, (int, float)):
            raise ConversionError(f"怪物缺少合法的抗性字段: {source_key}")
        base_value[target_key] = value

    return normalize_value(base_value)



def build_monster_grow_curves(monster_props: Any) -> list[dict[str, Any]]:
    if not isinstance(monster_props, list) or not monster_props:
        raise ConversionError("怪物缺少合法的成长曲线数据")

    grow_curves: list[dict[str, Any]] = []
    seen_types: set[int] = set()
    for monster_prop in monster_props:
        if not isinstance(monster_prop, dict):
            raise ConversionError("怪物成长曲线结构异常")

        prop_type = monster_prop.get("type")
        curve_name = monster_prop.get("grow_curve")
        if prop_type not in PROP_TYPE_MAP:
            raise ConversionError(f"未识别的怪物属性类型: {prop_type}")
        if curve_name not in MONSTER_CURVE_VALUE_MAP:
            raise ConversionError(f"未识别的怪物成长曲线: {curve_name}")

        mapped_type = PROP_TYPE_MAP[prop_type]
        if mapped_type in seen_types:
            continue
        seen_types.add(mapped_type)
        grow_curves.append(
            {
                "Type": mapped_type,
                "Value": MONSTER_CURVE_VALUE_MAP[curve_name],
            }
        )

    required_types = {1, 4, 7}
    if seen_types != required_types:
        missing_types = sorted(required_types - seen_types)
        raise ConversionError(f"怪物成长曲线缺少必要属性类型: {missing_types}")

    grow_curves.sort(key=lambda entry: entry["Type"])
    return normalize_value(grow_curves)



def build_monster_entry(
    monster_id: int,
    old_monster: dict[str, Any],
    reference_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required_text_fields = {
        "name": old_monster.get("name"),
        "desc": old_monster.get("desc"),
        "icon": old_monster.get("icon"),
        "title": old_monster.get("title"),
    }
    for field_name, value in required_text_fields.items():
        if not isinstance(value, str) or not value:
            raise ConversionError(f"怪物 {monster_id} 缺少必要字段: {field_name}")

    child_map = old_monster.get("child")
    if not isinstance(child_map, dict) or not child_map:
        raise ConversionError(f"怪物 {monster_id} 缺少 child 数据")

    child_data = resolve_monster_child(monster_id, child_map)
    monster_name = child_data.get("monster_name")
    monster_type = child_data.get("type")
    if not isinstance(monster_name, str) or not monster_name:
        raise ConversionError(f"怪物 {monster_id} 缺少 monster_name")
    if not isinstance(monster_type, str) or not monster_type:
        raise ConversionError(f"怪物 {monster_id} 缺少 type")

    monster_entry = {
        "Id": monster_id,
        "DescribeId": build_monster_describe_id(monster_id, reference_entry),
        "MonsterName": monster_name,
        "Name": old_monster["name"],
        "Title": old_monster["title"],
        "Description": old_monster["desc"],
        "Icon": old_monster["icon"],
        "Type": resolve_monster_type(monster_type, child_data.get("local_legend"), reference_entry),
        "Arkhe": resolve_monster_arkhe(reference_entry),
        "BaseValue": build_monster_base_value(child_data),
        "GrowCurves": build_monster_grow_curves(child_data.get("prop")),
    }

    drops = build_monster_drops(old_monster.get("reward"))
    if drops:
        monster_entry["Drops"] = drops

    return normalize_value(monster_entry)



def resolve_monster_insert_index(
    monster_entry: dict[str, Any],
    monster_list: list[dict[str, Any]],
    reference_lists: list[list[dict[str, Any]]],
) -> int:
    target_id = monster_entry.get("Id")
    target_describe_id = monster_entry.get("DescribeId")
    if not isinstance(target_id, int) or not isinstance(target_describe_id, int):
        return len(monster_list)

    describe_to_index = {
        describe_id: index
        for index, entry in enumerate(monster_list)
        for describe_id in [entry.get("DescribeId")]
        if isinstance(describe_id, int)
    }

    for reference_list in reference_lists:
        target_index = next(
            (
                index
                for index, entry in enumerate(reference_list)
                if entry.get("Id") == target_id and entry.get("DescribeId") == target_describe_id
            ),
            None,
        )
        if target_index is None:
            continue

        for index in range(target_index - 1, -1, -1):
            describe_id = reference_list[index].get("DescribeId")
            if isinstance(describe_id, int) and describe_id in describe_to_index:
                return describe_to_index[describe_id] + 1

        for index in range(target_index + 1, len(reference_list)):
            describe_id = reference_list[index].get("DescribeId")
            if isinstance(describe_id, int) and describe_id in describe_to_index:
                return describe_to_index[describe_id]

    for index, entry in enumerate(monster_list):
        describe_id = entry.get("DescribeId")
        if isinstance(describe_id, int) and describe_id > target_describe_id:
            return index
    return len(monster_list)



def update_monsters_from_manifest(
    version: str,
    new_monster_ids: list[Any],
    monster_path: Path,
) -> tuple[int, int, int]:
    monster_list = load_json(monster_path)
    if not isinstance(monster_list, list):
        raise ConversionError(f"Monster 文件结构异常: {monster_path}")

    reference_index, reference_lists = load_monster_reference_data(monster_path)

    existing_ids: set[int] = set()
    duplicate_ids: set[int] = set()
    for entry in monster_list:
        monster_id = entry.get("Id")
        if not isinstance(monster_id, int) or monster_id <= 0:
            continue
        if monster_id in existing_ids:
            duplicate_ids.add(monster_id)
            continue
        existing_ids.add(monster_id)

    for duplicate_id in sorted(duplicate_ids):
        logger.warning(f"Monster.json 中已存在重复怪物 Id: {duplicate_id}，本次将跳过新增")

    pending_monster_ids: list[int] = []
    seen_monster_ids: set[int] = set()
    skipped_count = 0
    for raw_monster_id in new_monster_ids or []:
        try:
            monster_id = int(raw_monster_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的怪物 Id: {raw_monster_id}")
            skipped_count += 1
            continue
        if monster_id <= 0:
            logger.warning(f"跳过无效的怪物 Id: {raw_monster_id}")
            skipped_count += 1
            continue
        if monster_id in seen_monster_ids:
            continue
        seen_monster_ids.add(monster_id)
        pending_monster_ids.append(monster_id)

    added_count = 0
    monster_list_changed = False

    for monster_id in pending_monster_ids:
        monster_details = fetch_monster_details(version, monster_id)
        if not isinstance(monster_details, dict):
            skipped_count += 1
            logger.warning(f"无法获取怪物 {monster_id} 的详情，跳过")
            continue

        try:
            monster_entry = build_monster_entry(
                monster_id,
                monster_details,
                reference_index.get(monster_id),
            )
        except ConversionError as exc:
            skipped_count += 1
            logger.warning(f"怪物 {monster_id} 转换失败，已跳过: {exc}")
            continue

        if monster_id in existing_ids:
            skipped_count += 1
            logger.info(f"怪物 {monster_id} 已存在于 Monster.json，跳过新增")
            continue

        insert_index = resolve_monster_insert_index(monster_entry, monster_list, reference_lists)
        monster_list.insert(insert_index, monster_entry)
        existing_ids.add(monster_id)
        added_count += 1
        monster_list_changed = True
        logger.info(f"已添加怪物 {monster_id} -> {monster_path}")

    if monster_list_changed:
        dump_json(monster_path, monster_list)
    return added_count, skipped_count, len(duplicate_ids)

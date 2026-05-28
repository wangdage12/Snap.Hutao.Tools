from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any

from .common import (
    ConversionError,
    DEFAULT_AVATAR_PROMOTE_TEMPLATE,
    DEFAULT_WEAPON_PROMOTE_TEMPLATE,
    PROP_TYPE_MAP,
    WEAPON_MAP,
    WEAPON_METADATA_TYPE_MAP,
    WEAPON_PROP_TYPE_MAP,
    WEAPON_SORT_GROUP_MAP,
    dump_json,
    load_json,
    logger,
    normalize_value,
)
from .remote import download_image, fetch_weapon_details

def build_weapon_awaken_icon(icon: str) -> str:


    return f"{icon}_Awaken" if icon else ""


def download_weapon_images(weapon_data: dict[str, Any], image_folder: str | Path = "static/raw"):
    image_folder = Path(image_folder)
    image_folder.mkdir(parents=True, exist_ok=True)

    for icon_type in ("Icon", "AwakenIcon"):
        icon_name = weapon_data.get(icon_type, "")
        if icon_name:
            download_image(icon_name, image_folder, "EquipIcon")



def load_weapon_reference_index(weapon_path: Path) -> dict[int, dict[str, Any]]:
    reference_index: dict[int, dict[str, Any]] = {}
    locale_root = weapon_path.parent.parent
    for locale_weapon_path in sorted(locale_root.glob("*/Weapon.json")):
        if locale_weapon_path == weapon_path:
            continue
        try:
            for entry in load_json(locale_weapon_path):
                weapon_id = entry.get("Id")
                if isinstance(weapon_id, int) and weapon_id not in reference_index:
                    reference_index[weapon_id] = entry
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"读取参考 Weapon 失败: {locale_weapon_path}, 错误: {exc}")
    return reference_index



def build_weapon_sort_tracker(
    weapon_list: list[dict[str, Any]],
    reference_index: dict[int, dict[str, Any]],
) -> dict[tuple[int, int], int]:
    sort_tracker: dict[tuple[int, int], int] = {}

    def update_tracker(entry: dict[str, Any]):
        rank_level = entry.get("RankLevel")
        weapon_type = entry.get("WeaponType")
        sort_value = entry.get("Sort")
        if not isinstance(rank_level, int) or not isinstance(weapon_type, int) or not isinstance(sort_value, int):
            return
        bucket = (rank_level, weapon_type)
        sort_tracker[bucket] = max(sort_tracker.get(bucket, 0), sort_value)

    for entry in weapon_list:
        update_tracker(entry)
    for entry in reference_index.values():
        update_tracker(entry)
    return sort_tracker



def resolve_weapon_sort(
    rank_level: int,
    weapon_type: int,
    sort_tracker: dict[tuple[int, int], int],
    reference_entry: dict[str, Any] | None = None,
) -> int:
    if reference_entry and isinstance(reference_entry.get("Sort"), int):
        return reference_entry["Sort"]

    bucket = (rank_level, weapon_type)
    base_sort = rank_level * 1000 + WEAPON_SORT_GROUP_MAP.get(weapon_type, 0) * 100
    next_sort = max(sort_tracker.get(bucket, base_sort), base_sort) + 1
    sort_tracker[bucket] = next_sort
    return next_sort



def weapon_curve_value(curve_name: str, prop_type: str) -> int:
    match = re.search(r"_(\d+)$", curve_name)
    if not match:
        raise ConversionError(f"未识别的武器成长曲线: {curve_name}")

    suffix_value = int(match.group(1))
    if prop_type == "FIGHT_PROP_BASE_ATTACK":
        return 1000 + suffix_value
    return 2000 + suffix_value



def build_weapon_grow_curves(weapon_props: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grow_curves: list[dict[str, Any]] = []
    for weapon_prop in weapon_props:
        init_value = weapon_prop.get("init_value")
        prop_type = weapon_prop.get("prop_type")
        curve_name = weapon_prop.get("type")

        if not isinstance(init_value, (int, float)):
            raise ConversionError("武器缺少合法的 init_value")
        if prop_type not in WEAPON_PROP_TYPE_MAP:
            raise ConversionError(f"未识别的武器属性类型: {prop_type}")
        if not isinstance(curve_name, str) or not curve_name:
            raise ConversionError("武器缺少合法的成长曲线类型")

        grow_curves.append(
            {
                "InitValue": init_value,
                "Type": WEAPON_PROP_TYPE_MAP[prop_type],
                "Value": weapon_curve_value(curve_name, prop_type),
            }
        )

    grow_curves.sort(key=lambda entry: (0 if entry["Type"] == 4 else 1, entry["Type"]))
    if not grow_curves or grow_curves[0]["Type"] != 4:
        raise ConversionError("武器缺少基础攻击成长曲线")
    return normalize_value(grow_curves)



def build_weapon_affix(refinement: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(refinement, dict) or not refinement:
        return None

    descriptions: list[dict[str, Any]] = []
    affix_name = ""
    for raw_level in sorted(refinement, key=lambda value: int(value)):
        level_data = refinement.get(raw_level)
        if not isinstance(level_data, dict):
            raise ConversionError("武器精炼数据结构异常")

        name = level_data.get("name", "")
        description = level_data.get("desc", "")
        if not isinstance(name, str) or not name:
            raise ConversionError("武器精炼名称缺失")
        if not isinstance(description, str) or not description:
            raise ConversionError("武器精炼描述缺失")

        affix_name = affix_name or name
        descriptions.append(
            {
                "Level": int(raw_level) - 1,
                "Description": description,
            }
        )

    return normalize_value(
        {
            "Name": affix_name,
            "Descriptions": descriptions,
        }
    )



def build_weapon_cultivation_items(materials: dict[str, Any]) -> list[int]:
    if not isinstance(materials, dict) or not materials:
        raise ConversionError("武器缺少突破材料数据")

    material_levels = sorted(
        [
            (int(level), data)
            for level, data in materials.items()
            if str(level).isdigit() and isinstance(data, dict)
        ],
        key=lambda item: item[0],
    )

    if not material_levels:
        raise ConversionError("武器突破材料数据为空")

    result: list[int] = []
    for mat in material_levels[-1][1].get("mats", []):
        item_id = mat.get("id")
        if isinstance(item_id, int) and item_id not in result:
            result.append(item_id)

    if not result:
        raise ConversionError("武器缺少可用的 CultivationItems")
    return result



def build_weapon_entry(
    weapon_id: int,
    old_weapon: dict[str, Any],
    sort_tracker: dict[tuple[int, int], int],
    reference_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required_text_fields = {
        "name": old_weapon.get("name"),
        "desc": old_weapon.get("desc"),
        "icon": old_weapon.get("icon"),
        "weapon_type": old_weapon.get("weapon_type"),
    }
    for field_name, value in required_text_fields.items():
        if not isinstance(value, str) or not value:
            raise ConversionError(f"武器 {weapon_id} 缺少必要字段: {field_name}")

    weapon_type_name = old_weapon["weapon_type"]
    if weapon_type_name not in WEAPON_METADATA_TYPE_MAP:
        raise ConversionError(f"未识别的武器类型: {weapon_type_name}")

    rarity = old_weapon.get("rarity")
    if not isinstance(rarity, int):
        raise ConversionError(f"武器 {weapon_id} 缺少合法的 rarity")

    weapon_props = old_weapon.get("weapon_prop")
    if not isinstance(weapon_props, list) or not weapon_props:
        raise ConversionError(f"武器 {weapon_id} 缺少 weapon_prop")

    materials = old_weapon.get("materials")
    if not isinstance(materials, dict) or not materials:
        raise ConversionError(f"武器 {weapon_id} 缺少 materials")

    weapon_entry = {

        "Id": weapon_id,
        "PromoteId": reference_entry.get("PromoteId") if isinstance(reference_entry, dict) and isinstance(reference_entry.get("PromoteId"), int) else weapon_id,
        "Sort": resolve_weapon_sort(rarity, WEAPON_METADATA_TYPE_MAP[weapon_type_name], sort_tracker, reference_entry),
        "WeaponType": WEAPON_METADATA_TYPE_MAP[weapon_type_name],
        "RankLevel": rarity,
        "Name": old_weapon["name"],
        "Description": old_weapon["desc"],
        "Icon": old_weapon["icon"],
        "AwakenIcon": build_weapon_awaken_icon(old_weapon["icon"]),
        "GrowCurves": build_weapon_grow_curves(weapon_props),
        "CultivationItems": build_weapon_cultivation_items(materials),
    }

    affix = build_weapon_affix(old_weapon.get("refinement", {}))
    if affix is not None:
        weapon_entry["Affix"] = affix

    return normalize_value(weapon_entry)



def update_weapons_from_manifest(
    version: str,
    new_weapon_ids: list[Any],
    weapon_path: Path,
    image_folder: str | Path = "static/raw",
) -> tuple[list[int], int, int, int]:
    weapon_list = load_json(weapon_path)
    if not isinstance(weapon_list, list):
        raise ConversionError(f"Weapon 文件结构异常: {weapon_path}")

    reference_index = load_weapon_reference_index(weapon_path)
    sort_tracker = build_weapon_sort_tracker(weapon_list, reference_index)

    existing_ids: set[int] = set()
    duplicate_ids: set[int] = set()
    for entry in weapon_list:
        weapon_id = entry.get("Id")
        if not isinstance(weapon_id, int):
            continue
        if weapon_id in existing_ids:
            duplicate_ids.add(weapon_id)
            continue
        existing_ids.add(weapon_id)

    for duplicate_id in sorted(duplicate_ids):
        logger.warning(f"Weapon.json 中已存在重复武器 Id: {duplicate_id}，本次将跳过新增")

    pending_weapon_ids: list[int] = []
    seen_weapon_ids: set[int] = set()
    skipped_count = 0
    for raw_weapon_id in new_weapon_ids or []:
        try:
            weapon_id = int(raw_weapon_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的武器 Id: {raw_weapon_id}")
            skipped_count += 1
            continue
        if weapon_id in seen_weapon_ids:
            continue
        seen_weapon_ids.add(weapon_id)
        pending_weapon_ids.append(weapon_id)

    valid_weapon_ids: list[int] = []
    added_count = 0
    weapon_list_changed = False

    for weapon_id in pending_weapon_ids:
        weapon_details = fetch_weapon_details(version, weapon_id)
        if not isinstance(weapon_details, dict):
            skipped_count += 1
            logger.warning(f"无法获取武器 {weapon_id} 的详情，跳过")
            continue

        try:
            weapon_entry = build_weapon_entry(
                weapon_id,
                weapon_details,
                sort_tracker,
                reference_index.get(weapon_id),
            )
        except ConversionError as exc:
            skipped_count += 1
            logger.warning(f"武器 {weapon_id} 转换失败，已跳过: {exc}")
            continue

        valid_weapon_ids.append(weapon_id)
        download_weapon_images(weapon_entry, image_folder)

        if weapon_id in existing_ids:
            skipped_count += 1
            logger.info(f"武器 {weapon_id} 已存在于 Weapon.json，跳过新增")
            continue

        weapon_list.append(weapon_entry)
        existing_ids.add(weapon_id)
        added_count += 1
        weapon_list_changed = True
        logger.info(f"已添加武器 {weapon_id} -> {weapon_path}")

    if weapon_list_changed:
        weapon_list.sort(key=lambda entry: int(entry.get("Id", 0)))
        dump_json(weapon_path, weapon_list)
    return valid_weapon_ids, added_count, skipped_count, len(duplicate_ids)



def build_weapon_promote_entries(weapon_id: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for template in DEFAULT_WEAPON_PROMOTE_TEMPLATE:
        entry = deepcopy(template)
        entry["Id"] = weapon_id
        entries.append(normalize_value(entry))
    return entries



def update_weapon_promotes(weapon_ids: list[Any], weapon_promote_path: Path) -> tuple[int, int, int]:
    weapon_promote_list = load_json(weapon_promote_path)
    if not isinstance(weapon_promote_list, list):
        raise ConversionError(f"WeaponPromote 文件结构异常: {weapon_promote_path}")

    existing_pairs: set[tuple[int, int]] = set()
    duplicate_pairs: set[tuple[int, int]] = set()
    for entry in weapon_promote_list:
        weapon_id = entry.get("Id")
        level = entry.get("Level")
        if not isinstance(weapon_id, int) or not isinstance(level, int):
            continue
        pair = (weapon_id, level)
        if pair in existing_pairs:
            duplicate_pairs.add(pair)
            continue
        existing_pairs.add(pair)

    for duplicate_weapon_id, duplicate_level in sorted(duplicate_pairs):
        logger.warning(
            f"WeaponPromote.json 中已存在重复条目 Id: {duplicate_weapon_id}, Level: {duplicate_level}，本次将跳过新增"
        )

    added_count = 0
    skipped_count = 0
    seen_weapon_ids: set[int] = set()
    weapon_promote_changed = False

    for raw_weapon_id in weapon_ids or []:
        try:
            weapon_id = int(raw_weapon_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的武器突破 Id: {raw_weapon_id}")
            skipped_count += 1
            continue

        if weapon_id in seen_weapon_ids:
            continue
        seen_weapon_ids.add(weapon_id)

        missing_entries = [
            entry for entry in build_weapon_promote_entries(weapon_id)
            if (weapon_id, entry["Level"]) not in existing_pairs
        ]
        if not missing_entries:
            skipped_count += 1
            logger.info(f"武器突破 Id {weapon_id} 已存在于 WeaponPromote.json，跳过")
            continue

        for entry in missing_entries:
            weapon_promote_list.append(entry)
            existing_pairs.add((weapon_id, entry["Level"]))
            added_count += 1
            weapon_promote_changed = True

        logger.info(f"已为武器突破 Id {weapon_id} 添加 {len(missing_entries)} 条 WeaponPromote 数据")

    if weapon_promote_changed:
        weapon_promote_list.sort(key=lambda entry: (int(entry.get("Id", 0)), int(entry.get("Level", 0))))
        dump_json(weapon_promote_path, weapon_promote_list)
    return added_count, skipped_count, len(duplicate_pairs)



def build_avatar_promote_entries(promote_id: int) -> list[dict[str, Any]]:

    entries: list[dict[str, Any]] = []
    for template in DEFAULT_AVATAR_PROMOTE_TEMPLATE:
        entry = deepcopy(template)
        entry["Id"] = promote_id
        entries.append(normalize_value(entry))
    return entries


def update_avatar_promotes(promote_ids: list[Any], avatar_promote_path: Path) -> tuple[int, int, int]:
    avatar_promote_list = load_json(avatar_promote_path)
    if not isinstance(avatar_promote_list, list):
        raise ConversionError(f"AvatarPromote 文件结构异常: {avatar_promote_path}")

    existing_pairs: set[tuple[int, int]] = set()
    duplicate_pairs: set[tuple[int, int]] = set()
    for entry in avatar_promote_list:
        promote_id = entry.get("Id")
        level = entry.get("Level")
        if not isinstance(promote_id, int) or not isinstance(level, int):
            continue
        pair = (promote_id, level)
        if pair in existing_pairs:
            duplicate_pairs.add(pair)
            continue
        existing_pairs.add(pair)

    for duplicate_promote_id, duplicate_level in sorted(duplicate_pairs):
        logger.warning(
            f"AvatarPromote.json 中已存在重复条目 Id: {duplicate_promote_id}, Level: {duplicate_level}，本次将跳过新增"
        )

    added_count = 0
    skipped_count = 0
    seen_promote_ids: set[int] = set()

    for raw_promote_id in promote_ids or []:
        try:
            promote_id = int(raw_promote_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的角色突破 Id: {raw_promote_id}")
            skipped_count += 1
            continue

        if promote_id in seen_promote_ids:
            continue
        seen_promote_ids.add(promote_id)

        missing_entries = [
            entry for entry in build_avatar_promote_entries(promote_id)
            if (promote_id, entry["Level"]) not in existing_pairs
        ]
        if not missing_entries:
            skipped_count += 1
            logger.info(f"角色突破 Id {promote_id} 已存在于 AvatarPromote.json，跳过")
            continue

        for entry in missing_entries:
            avatar_promote_list.append(entry)
            existing_pairs.add((promote_id, entry["Level"]))
            added_count += 1

        logger.info(f"已为角色突破 Id {promote_id} 添加 {len(missing_entries)} 条 AvatarPromote 数据")

    avatar_promote_list.sort(key=lambda entry: (int(entry.get("Id", 0)), int(entry.get("Level", 0))))
    dump_json(avatar_promote_path, avatar_promote_list)
    return added_count, skipped_count, len(duplicate_pairs)

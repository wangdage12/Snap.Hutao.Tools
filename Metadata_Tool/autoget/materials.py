from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import (
    ConversionError,
    DEFAULT_MATERIAL_TEMPLATE,
    UNKNOWN_MATERIAL_ID,
    dump_json,
    load_json,
    logger,
    normalize_value,
)
from .remote import download_material_images

def load_material_reference_index(material_path: Path) -> dict[int, dict[str, Any]]:
    reference_index: dict[int, dict[str, Any]] = {}
    locale_root = material_path.parent.parent
    for locale_material_path in sorted(locale_root.glob("*/Material.json")):
        if locale_material_path == material_path:
            continue
        try:
            for entry in load_json(locale_material_path):
                item_id = entry.get("Id")
                if isinstance(item_id, int) and item_id not in reference_index:
                    reference_index[item_id] = entry
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"读取参考 Material 失败: {locale_material_path}, 错误: {exc}")
    return reference_index


def build_material_reference_maps(
    material_list: list[dict[str, Any]],
    item_data: dict[str, Any],
) -> dict[str, dict[str, int]]:
    reference_maps: dict[str, dict[str, int]] = {
        "rank_by_type": {},
        "rank_by_material_type": {},
        "material_type": {},
        "item_type": {},
    }

    for entry in material_list:
        item_id = entry.get("Id")
        if not isinstance(item_id, int):
            continue

        old_item = item_data.get(str(item_id))
        if not isinstance(old_item, dict):
            continue

        item_type = old_item.get("item_type")
        material_type = old_item.get("material_type")
        type_description = old_item.get("type")

        if isinstance(type_description, str) and type_description and isinstance(entry.get("Rank"), int):
            reference_maps["rank_by_type"].setdefault(type_description, entry["Rank"])
        if isinstance(material_type, str) and material_type:
            if isinstance(entry.get("Rank"), int):
                reference_maps["rank_by_material_type"].setdefault(material_type, entry["Rank"])
            if isinstance(entry.get("MaterialType"), int):
                reference_maps["material_type"].setdefault(material_type, entry["MaterialType"])
        if isinstance(item_type, str) and item_type and isinstance(entry.get("ItemType"), int):
            reference_maps["item_type"].setdefault(item_type, entry["ItemType"])

    return reference_maps


def build_material_entry(
    item_id: int,
    old_item: dict[str, Any],
    reference_maps: dict[str, dict[str, int]],
    reference_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    material_entry = deepcopy(DEFAULT_MATERIAL_TEMPLATE)

    if reference_entry:
        for field in ("Rank", "MaterialType", "RankLevel", "ItemType", "Icon"):
            value = reference_entry.get(field)
            if value not in (None, ""):
                material_entry[field] = value

    old_item_type = old_item.get("item_type")
    old_material_type = old_item.get("material_type")
    type_description = old_item.get("type")

    if isinstance(type_description, str) and type_description:
        material_entry["Rank"] = reference_maps["rank_by_type"].get(
            type_description,
            material_entry["Rank"],
        )
    elif isinstance(old_material_type, str) and old_material_type:
        material_entry["Rank"] = reference_maps["rank_by_material_type"].get(
            old_material_type,
            material_entry["Rank"],
        )

    if isinstance(old_material_type, str) and old_material_type:
        material_entry["MaterialType"] = reference_maps["material_type"].get(
            old_material_type,
            material_entry["MaterialType"],
        )
    if isinstance(old_item_type, str) and old_item_type:
        material_entry["ItemType"] = reference_maps["item_type"].get(
            old_item_type,
            material_entry["ItemType"],
        )

    if isinstance(old_item.get("rank"), int):
        material_entry["RankLevel"] = old_item["rank"]

    material_entry["Id"] = item_id
    material_entry["Name"] = old_item.get("name", material_entry["Name"])
    material_entry["Description"] = old_item.get("desc", material_entry["Description"])
    material_entry["TypeDescription"] = old_item.get("type", material_entry["TypeDescription"])
    material_entry["Icon"] = old_item.get("icon", material_entry["Icon"])
    return normalize_value(material_entry)


def build_unknown_material_entry() -> dict[str, Any]:
    material_entry = deepcopy(DEFAULT_MATERIAL_TEMPLATE)
    material_entry.update(
        {
            "Id": UNKNOWN_MATERIAL_ID,
            "Name": "未知道具",
            "Description": "自动补充的占位道具。",
            "TypeDescription": "未知",
        }
    )
    return material_entry


def update_materials_from_item_list(
    item_data: dict[str, Any],
    new_item_ids: list[Any],
    material_path: Path,
    image_folder: str | Path = "static/raw",
) -> tuple[int, int, int]:
    material_list = load_json(material_path)
    if not isinstance(material_list, list):
        raise ConversionError(f"Material 文件结构异常: {material_path}")

    reference_index = load_material_reference_index(material_path)
    reference_maps = build_material_reference_maps(material_list, item_data)

    existing_ids: set[int] = set()
    duplicate_ids: set[int] = set()
    for entry in material_list:
        item_id = entry.get("Id")
        if not isinstance(item_id, int):
            continue
        if item_id in existing_ids:
            duplicate_ids.add(item_id)
            continue
        existing_ids.add(item_id)

    for duplicate_id in sorted(duplicate_ids):
        logger.warning(f"Material.json 中已存在重复道具 Id: {duplicate_id}，本次将跳过新增")

    added_count = 0
    skipped_count = 0
    pending_item_ids: list[int] = []
    seen_new_item_ids: set[int] = set()

    for raw_item_id in new_item_ids or []:
        try:
            item_id = int(raw_item_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的道具 Id: {raw_item_id}")
            skipped_count += 1
            continue
        if item_id in seen_new_item_ids:
            continue
        seen_new_item_ids.add(item_id)
        pending_item_ids.append(item_id)

    if UNKNOWN_MATERIAL_ID not in existing_ids and UNKNOWN_MATERIAL_ID not in seen_new_item_ids:
        pending_item_ids.append(UNKNOWN_MATERIAL_ID)

    for item_id in pending_item_ids:
        if item_id in existing_ids:
            skipped_count += 1
            logger.info(f"道具 {item_id} 已存在于 Material.json，跳过")
            continue

        if item_id == UNKNOWN_MATERIAL_ID:
            material_entry = build_unknown_material_entry()
        else:
            old_item = item_data.get(str(item_id))
            if not isinstance(old_item, dict):
                logger.warning(f"item_all.json 中不存在道具 {item_id}，跳过")
                skipped_count += 1
                continue
            material_entry = build_material_entry(
                item_id,
                old_item,
                reference_maps,
                reference_index.get(item_id),
            )

        material_list.append(material_entry)
        existing_ids.add(item_id)
        added_count += 1
        download_material_images(material_entry, image_folder)
        logger.info(f"已添加道具 {item_id} -> {material_path}")

    material_list.sort(key=lambda entry: int(entry.get("Id", 0)))
    dump_json(material_path, material_list)
    return added_count, skipped_count, len(duplicate_ids)

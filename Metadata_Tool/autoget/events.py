from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import (
    ConversionError,
    ROLE_COMBAT_ELEMENT_MAP,
    TOWER_BACKGROUND_MAP,
    dump_json,
    logger,
    normalize_value,
)
from .monsters import build_monster_describe_id
from .remote import (
    fetch_hard_challenge_overview,
    fetch_role_combat_overview,
    fetch_tower_details,
    fetch_tower_overview,
)
from .common import load_json

def is_blank_string(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def is_placeholder_wave_list(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return True

    has_any_monster = False
    for wave in value:
        if not isinstance(wave, dict):
            return False
        monsters = wave.get("Monsters")
        if not isinstance(monsters, list):
            return False
        if monsters:
            has_any_monster = True
    return not has_any_monster


def normalize_tower_descriptions(values: Any) -> list[str]:
    descriptions: list[str] = []
    if not isinstance(values, list):
        return descriptions

    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized or normalized.startswith("(test)"):
            continue
        descriptions.append(normalized)
    return descriptions


def format_tower_time(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    normalized = value.strip()
    try:
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except ValueError:
        return normalized


def build_tower_monster_describe_index(monster_path: Path) -> dict[int, int]:
    monster_list = load_json(monster_path)
    if not isinstance(monster_list, list):
        raise ConversionError(f"Monster 文件结构异常: {monster_path}")

    monster_describe_index: dict[int, int] = {}
    for entry in monster_list:
        monster_id = entry.get("Id")
        describe_id = entry.get("DescribeId")
        if isinstance(monster_id, int) and isinstance(describe_id, int) and describe_id > 0:
            monster_describe_index[monster_id] = describe_id
    return monster_describe_index


def build_tower_wave(monsters: Any, monster_describe_index: dict[int, int]) -> list[dict[str, Any]]:
    if not isinstance(monsters, list):
        return [{"Type": 0, "Monsters": []}]

    ordered_describe_ids: list[int] = []
    counter: Counter[int] = Counter()
    for monster in monsters:
        if not isinstance(monster, dict):
            continue
        monster_id = monster.get("id")
        if not isinstance(monster_id, int):
            continue
        describe_id = monster_describe_index.get(monster_id, build_monster_describe_id(monster_id))
        if describe_id not in counter:
            ordered_describe_ids.append(describe_id)
        counter[describe_id] += 1

    return [
        {
            "Type": 0,
            "Monsters": [{"Id": describe_id, "Count": counter[describe_id]} for describe_id in ordered_describe_ids],
        }
    ]


def build_tower_level_entry(
    group_id: int,
    room_index: int,
    room_data: dict[str, Any],
    monster_describe_index: dict[int, int],
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "GroupId": group_id,
        "Index": room_index,
        "MonsterLevel": int(room_data.get("level", 0)),
        "Goal": 0,
        "FirstWaves": build_tower_wave(room_data.get("first"), monster_describe_index),
        "SecondWaves": build_tower_wave(room_data.get("second"), monster_describe_index),
    }
    return normalize_value(entry)


def build_tower_floor_entry(group_id: int, floor_index: int, floor_data: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "Id": 1000 + group_id,
        "Index": floor_index,
        "LevelGroupId": group_id,
        "Background": TOWER_BACKGROUND_MAP.get(floor_index, "UI_TowerPic_4"),
        "Descriptions": normalize_tower_descriptions(floor_data.get("buff")),
    }

    first_descriptions = normalize_tower_descriptions([floor_data.get("first_half_buff")])
    second_descriptions = normalize_tower_descriptions([floor_data.get("second_half_buff")])
    if first_descriptions:
        entry["FirstDescriptions"] = first_descriptions
    if second_descriptions:
        entry["SecondDescriptions"] = second_descriptions

    return normalize_value(entry)


def build_tower_schedule_entry(
    schedule_id: int,
    floor_ids: list[int],
    overview_entry: dict[str, Any],
    tower_details: dict[str, Any],
) -> dict[str, Any]:
    leyline = tower_details.get("leyline")
    if not isinstance(leyline, dict):
        leyline = {}

    open_value = tower_details.get("open", overview_entry.get("begin"))
    close_value = tower_details.get("close", overview_entry.get("end"))
    description = leyline.get("desc", overview_entry.get("desc"))

    entry: dict[str, Any] = {
        "Id": schedule_id,
        "FloorIds": floor_ids,
        "Open": format_tower_time(open_value),
        "Close": format_tower_time(close_value),
        "BuffName": leyline.get("name", overview_entry.get("zh", "")),
        "Descriptions": normalize_tower_descriptions([description]),
        "Icon": leyline.get("icon", overview_entry.get("icon", "")),
    }
    return normalize_value(entry)


def build_tower_level_signature(entry: dict[str, Any]) -> str:
    normalized = {
        "Index": entry.get("Index"),
        "MonsterLevel": entry.get("MonsterLevel"),
        "Goal": entry.get("Goal", 0),
        "FirstWaves": normalize_value(entry.get("FirstWaves", [])),
        "SecondWaves": normalize_value(entry.get("SecondWaves", [])),
    }
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def build_tower_floor_signature(
    floor_entry: dict[str, Any],
    levels_by_group: dict[int, dict[int, dict[str, Any]]],
) -> str:
    group_id = floor_entry.get("LevelGroupId")
    group_levels = levels_by_group.get(group_id, {}) if isinstance(group_id, int) else {}
    normalized = {
        "Index": floor_entry.get("Index"),
        "Background": floor_entry.get("Background", ""),
        "Descriptions": normalize_value(floor_entry.get("Descriptions", [])),
        "FirstDescriptions": normalize_value(floor_entry.get("FirstDescriptions", [])),
        "SecondDescriptions": normalize_value(floor_entry.get("SecondDescriptions", [])),
        "Levels": [
            build_tower_level_signature(group_levels[level_index])
            for level_index in sorted(group_levels)
        ],
    }
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def build_existing_tower_signature_map(
    tower_floor_list: list[dict[str, Any]],
    tower_levels_by_group: dict[int, dict[int, dict[str, Any]]],
) -> dict[str, int]:
    signature_map: dict[str, int] = {}
    for floor_entry in tower_floor_list:
        floor_id = floor_entry.get("Id")
        if not isinstance(floor_id, int):
            continue
        signature = build_tower_floor_signature(floor_entry, tower_levels_by_group)
        signature_map.setdefault(signature, floor_id)
    return signature_map


def tower_schedule_needs_update(
    schedule_entry: dict[str, Any] | None,
    floors_by_id: dict[int, dict[str, Any]],
    levels_by_group: dict[int, dict[int, dict[str, Any]]],
) -> bool:
    if schedule_entry is None:
        return True

    if is_blank_string(schedule_entry.get("Open")) or is_blank_string(schedule_entry.get("Close")):
        return True
    if is_blank_string(schedule_entry.get("BuffName")):
        return True

    descriptions = schedule_entry.get("Descriptions")
    if not isinstance(descriptions, list) or not descriptions:
        return True

    floor_ids = schedule_entry.get("FloorIds")
    if not isinstance(floor_ids, list) or not floor_ids:
        return True

    for floor_id in floor_ids:
        if not isinstance(floor_id, int):
            return True
        floor_entry = floors_by_id.get(floor_id)
        if not isinstance(floor_entry, dict):
            return True

        descriptions_missing = not floor_entry.get("Descriptions") and not floor_entry.get("FirstDescriptions") and not floor_entry.get("SecondDescriptions")
        if descriptions_missing or is_blank_string(floor_entry.get("Background")):
            return True

        group_id = floor_entry.get("LevelGroupId")
        if not isinstance(group_id, int):
            return True
        group_levels = levels_by_group.get(group_id, {})
        if len(group_levels) < 3:
            return True

        for room_index in (1, 2, 3):
            level_entry = group_levels.get(room_index)
            if not isinstance(level_entry, dict):
                return True
            if is_placeholder_wave_list(level_entry.get("FirstWaves")) or is_placeholder_wave_list(level_entry.get("SecondWaves")):
                return True

    return False


def merge_missing_tower_schedule_fields(existing_entry: dict[str, Any], new_entry: dict[str, Any]) -> bool:
    changed = False

    if not isinstance(existing_entry.get("FloorIds"), list) or not existing_entry["FloorIds"]:
        existing_entry["FloorIds"] = list(new_entry.get("FloorIds", []))
        changed = True
    if is_blank_string(existing_entry.get("Open")) and new_entry.get("Open"):
        existing_entry["Open"] = new_entry["Open"]
        changed = True
    if is_blank_string(existing_entry.get("Close")) and new_entry.get("Close"):
        existing_entry["Close"] = new_entry["Close"]
        changed = True
    if is_blank_string(existing_entry.get("BuffName")) and new_entry.get("BuffName"):
        existing_entry["BuffName"] = new_entry["BuffName"]
        changed = True
    if (not isinstance(existing_entry.get("Descriptions"), list) or not existing_entry["Descriptions"]) and new_entry.get("Descriptions"):
        existing_entry["Descriptions"] = list(new_entry["Descriptions"])
        changed = True
    if is_blank_string(existing_entry.get("Icon")) and new_entry.get("Icon"):
        existing_entry["Icon"] = new_entry["Icon"]
        changed = True

    return changed


def merge_missing_tower_floor_fields(existing_entry: dict[str, Any], new_entry: dict[str, Any]) -> bool:
    changed = False

    if not isinstance(existing_entry.get("Index"), int) and isinstance(new_entry.get("Index"), int):
        existing_entry["Index"] = new_entry["Index"]
        changed = True
    if not isinstance(existing_entry.get("LevelGroupId"), int) and isinstance(new_entry.get("LevelGroupId"), int):
        existing_entry["LevelGroupId"] = new_entry["LevelGroupId"]
        changed = True
    if is_blank_string(existing_entry.get("Background")) and new_entry.get("Background"):
        existing_entry["Background"] = new_entry["Background"]
        changed = True
    if (not isinstance(existing_entry.get("Descriptions"), list) or not existing_entry["Descriptions"]) and new_entry.get("Descriptions"):
        existing_entry["Descriptions"] = list(new_entry["Descriptions"])
        changed = True
    if (not isinstance(existing_entry.get("FirstDescriptions"), list) or not existing_entry["FirstDescriptions"]) and new_entry.get("FirstDescriptions"):
        existing_entry["FirstDescriptions"] = list(new_entry["FirstDescriptions"])
        changed = True
    if (not isinstance(existing_entry.get("SecondDescriptions"), list) or not existing_entry["SecondDescriptions"]) and new_entry.get("SecondDescriptions"):
        existing_entry["SecondDescriptions"] = list(new_entry["SecondDescriptions"])
        changed = True

    return changed


def merge_missing_tower_level_fields(existing_entry: dict[str, Any], new_entry: dict[str, Any]) -> bool:
    changed = False

    if not isinstance(existing_entry.get("GroupId"), int) and isinstance(new_entry.get("GroupId"), int):
        existing_entry["GroupId"] = new_entry["GroupId"]
        changed = True
    if not isinstance(existing_entry.get("Index"), int) and isinstance(new_entry.get("Index"), int):
        existing_entry["Index"] = new_entry["Index"]
        changed = True
    if not isinstance(existing_entry.get("MonsterLevel"), int) and isinstance(new_entry.get("MonsterLevel"), int):
        existing_entry["MonsterLevel"] = new_entry["MonsterLevel"]
        changed = True
    if not isinstance(existing_entry.get("Goal"), int) and isinstance(new_entry.get("Goal"), int):
        existing_entry["Goal"] = new_entry["Goal"]
        changed = True
    if is_placeholder_wave_list(existing_entry.get("FirstWaves")) and new_entry.get("FirstWaves"):
        existing_entry["FirstWaves"] = deepcopy(new_entry["FirstWaves"])
        changed = True
    if is_placeholder_wave_list(existing_entry.get("SecondWaves")) and new_entry.get("SecondWaves"):
        existing_entry["SecondWaves"] = deepcopy(new_entry["SecondWaves"])
        changed = True

    return changed


def update_tower_from_remote(
    version: str,
    tower_schedule_path: Path,
    tower_floor_path: Path,
    tower_level_path: Path,
    monster_path: Path,
) -> tuple[int, int, int, int, int, int, int]:
    tower_schedule_list = load_json(tower_schedule_path)
    if not isinstance(tower_schedule_list, list):
        raise ConversionError(f"TowerSchedule 文件结构异常: {tower_schedule_path}")

    tower_floor_list = load_json(tower_floor_path)
    if not isinstance(tower_floor_list, list):
        raise ConversionError(f"TowerFloor 文件结构异常: {tower_floor_path}")

    tower_level_list = load_json(tower_level_path)
    if not isinstance(tower_level_list, list):
        raise ConversionError(f"TowerLevel 文件结构异常: {tower_level_path}")

    monster_describe_index = build_tower_monster_describe_index(monster_path)
    tower_overview = fetch_tower_overview(version)
    if not isinstance(tower_overview, dict):
        raise ConversionError(f"无法获取版本 {version} 的深境螺旋数据")

    schedules_by_id: dict[int, dict[str, Any]] = {}
    for entry in tower_schedule_list:
        schedule_id = entry.get("Id")
        if isinstance(schedule_id, int) and schedule_id not in schedules_by_id:
            schedules_by_id[schedule_id] = entry

    floors_by_id: dict[int, dict[str, Any]] = {}
    for entry in tower_floor_list:
        floor_id = entry.get("Id")
        if isinstance(floor_id, int) and floor_id not in floors_by_id:
            floors_by_id[floor_id] = entry

    levels_by_group: dict[int, dict[int, dict[str, Any]]] = {}
    for entry in tower_level_list:
        group_id = entry.get("GroupId")
        room_index = entry.get("Index")
        if isinstance(group_id, int) and isinstance(room_index, int):
            levels_by_group.setdefault(group_id, {})[room_index] = entry

    existing_signature_map = build_existing_tower_signature_map(tower_floor_list, levels_by_group)
    next_group_id = max((entry.get("LevelGroupId", 0) for entry in tower_floor_list if isinstance(entry.get("LevelGroupId"), int)), default=0) + 1
    next_level_id = max((entry.get("Id", 0) for entry in tower_level_list if isinstance(entry.get("Id"), int)), default=0) + 1

    schedule_added_count = 0
    schedule_updated_count = 0
    floor_added_count = 0
    floor_updated_count = 0
    level_added_count = 0
    level_updated_count = 0
    detail_skipped_count = 0

    tower_schedule_changed = False
    tower_floor_changed = False
    tower_level_changed = False

    candidate_schedule_ids: list[tuple[int, dict[str, Any]]] = []
    for raw_schedule_id, overview_entry in tower_overview.items():
        try:
            schedule_id = int(raw_schedule_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的深境螺旋 Id: {raw_schedule_id}")
            continue

        if not isinstance(overview_entry, dict):
            logger.warning(f"Tower {schedule_id} 数据结构异常，已跳过")
            continue

        if tower_schedule_needs_update(schedules_by_id.get(schedule_id), floors_by_id, levels_by_group):
            candidate_schedule_ids.append((schedule_id, overview_entry))

    candidate_schedule_ids.sort(key=lambda item: item[0])

    for schedule_id, overview_entry in candidate_schedule_ids:
        tower_details = fetch_tower_details(version, schedule_id)
        if not isinstance(tower_details, dict):
            detail_skipped_count += 1
            continue

        floor_root = tower_details.get("floor")
        if not isinstance(floor_root, dict) or not floor_root:
            logger.warning(f"Tower {schedule_id} 缺少合法的 floor 数据，已跳过")
            detail_skipped_count += 1
            continue

        sorted_floor_items: list[tuple[int, dict[str, Any]]] = []
        for raw_floor_index, floor_data in floor_root.items():
            try:
                floor_index = int(raw_floor_index)
            except (TypeError, ValueError):
                logger.warning(f"Tower {schedule_id} 存在无法识别的楼层 Index: {raw_floor_index}")
                continue
            if not isinstance(floor_data, dict):
                continue
            sorted_floor_items.append((floor_index, floor_data))
        sorted_floor_items.sort(key=lambda item: item[0])
        if not sorted_floor_items:
            detail_skipped_count += 1
            continue

        schedule_entry = schedules_by_id.get(schedule_id)
        existing_floor_ids = schedule_entry.get("FloorIds") if isinstance(schedule_entry, dict) else None
        resolved_floor_ids: list[int] = []

        for floor_position, (floor_index, floor_data) in enumerate(sorted_floor_items):
            existing_floor_id = None
            if isinstance(existing_floor_ids, list) and floor_position < len(existing_floor_ids):
                candidate_floor_id = existing_floor_ids[floor_position]
                if isinstance(candidate_floor_id, int):
                    existing_floor_id = candidate_floor_id

            if existing_floor_id is not None and existing_floor_id in floors_by_id:
                floor_id = existing_floor_id
                group_id = floors_by_id[floor_id].get("LevelGroupId", floor_id - 1000)
                if not isinstance(group_id, int):
                    group_id = floor_id - 1000
            else:
                provisional_group_id = next_group_id
                room_root = floor_data.get("room", {})
                if not isinstance(room_root, dict):
                    room_root = {}
                candidate_levels_by_group = {
                    provisional_group_id: {
                        room_index: build_tower_level_entry(provisional_group_id, room_index, room_data, monster_describe_index)
                        for room_index, room_data in sorted(
                            (
                                (int(raw_room_index), room_data)
                                for raw_room_index, room_data in room_root.items()
                                if isinstance(room_data, dict)
                            ),
                            key=lambda item: item[0],
                        )
                    }
                }
                candidate_floor_entry = build_tower_floor_entry(provisional_group_id, floor_index, floor_data)
                candidate_signature = build_tower_floor_signature(candidate_floor_entry, candidate_levels_by_group)
                existing_floor_id = existing_signature_map.get(candidate_signature)

                if existing_floor_id is not None and existing_floor_id in floors_by_id:
                    floor_id = existing_floor_id
                    group_id = floors_by_id[floor_id].get("LevelGroupId", floor_id - 1000)
                    if not isinstance(group_id, int):
                        group_id = floor_id - 1000
                else:
                    group_id = provisional_group_id
                    floor_id = 1000 + group_id
                    next_group_id += 1

            resolved_floor_ids.append(floor_id)
            new_floor_entry = build_tower_floor_entry(group_id, floor_index, floor_data)

            existing_floor_entry = floors_by_id.get(floor_id)
            if existing_floor_entry is None:
                tower_floor_list.append(new_floor_entry)
                floors_by_id[floor_id] = new_floor_entry
                tower_floor_changed = True
                floor_added_count += 1
                logger.info(f"已添加深境螺旋楼层 {floor_id} -> {tower_floor_path}")
            else:
                if merge_missing_tower_floor_fields(existing_floor_entry, new_floor_entry):
                    tower_floor_changed = True
                    floor_updated_count += 1
                    logger.info(f"已补充深境螺旋楼层 {floor_id} 缺失信息")

            group_levels = levels_by_group.setdefault(group_id, {})
            room_root = floor_data.get("room", {})
            if not isinstance(room_root, dict):
                room_root = {}

            for raw_room_index, room_data in sorted(room_root.items(), key=lambda item: int(item[0])):
                if not isinstance(room_data, dict):
                    continue
                room_index = int(raw_room_index)
                new_level_entry = build_tower_level_entry(group_id, room_index, room_data, monster_describe_index)
                existing_level_entry = group_levels.get(room_index)
                if existing_level_entry is None:
                    new_level_entry["Id"] = next_level_id
                    next_level_id += 1
                    tower_level_list.append(new_level_entry)
                    group_levels[room_index] = new_level_entry
                    tower_level_changed = True
                    level_added_count += 1
                    logger.info(f"已添加深境螺旋间 {group_id}-{room_index} -> {tower_level_path}")
                else:
                    if merge_missing_tower_level_fields(existing_level_entry, new_level_entry):
                        tower_level_changed = True
                        level_updated_count += 1
                        logger.info(f"已补充深境螺旋间 {group_id}-{room_index} 缺失波次数据")

            existing_signature_map[build_tower_floor_signature(floors_by_id[floor_id], levels_by_group)] = floor_id

        new_schedule_entry = build_tower_schedule_entry(schedule_id, resolved_floor_ids, overview_entry, tower_details)
        if schedule_entry is None:
            tower_schedule_list.insert(0, new_schedule_entry)
            schedules_by_id[schedule_id] = new_schedule_entry
            tower_schedule_changed = True
            schedule_added_count += 1
            logger.info(f"已添加深境螺旋档期 {schedule_id} -> {tower_schedule_path}")
        else:
            if merge_missing_tower_schedule_fields(schedule_entry, new_schedule_entry):
                tower_schedule_changed = True
                schedule_updated_count += 1
                logger.info(f"已补充深境螺旋档期 {schedule_id} 缺失信息")

    if tower_floor_changed:
        tower_floor_list.sort(key=lambda entry: int(entry.get("Id", 0)))
        dump_json(tower_floor_path, tower_floor_list)
    if tower_level_changed:
        tower_level_list.sort(key=lambda entry: int(entry.get("Id", 0)))
        dump_json(tower_level_path, tower_level_list)
    if tower_schedule_changed:
        dump_json(tower_schedule_path, tower_schedule_list)

    return (
        schedule_added_count,
        schedule_updated_count,
        floor_added_count,
        floor_updated_count,
        level_added_count,
        level_updated_count,
        detail_skipped_count,
    )


def normalize_int_list(values: Any) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    if not isinstance(values, list):
        return result
    for value in values:
        if isinstance(value, int) and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_role_combat_elements(values: Any) -> list[int]:
    elements: list[int] = []
    seen: set[int] = set()
    if not isinstance(values, list):
        return elements

    for value in values:
        if not isinstance(value, int) or value == 0:
            continue
        mapped_value = ROLE_COMBAT_ELEMENT_MAP.get(value)
        if mapped_value is None:
            logger.warning(f"幻想真境剧诗存在无法识别的元素类型: {value}")
            continue
        if mapped_value in seen:
            continue
        seen.add(mapped_value)
        elements.append(mapped_value)
    return elements


def merge_missing_role_combat_fields(existing_entry: dict[str, Any], new_entry: dict[str, Any]) -> bool:
    changed = False
    if is_blank_string(existing_entry.get("Begin")) and new_entry.get("Begin"):
        existing_entry["Begin"] = new_entry["Begin"]
        changed = True
    if is_blank_string(existing_entry.get("End")) and new_entry.get("End"):
        existing_entry["End"] = new_entry["End"]
        changed = True
    if (not isinstance(existing_entry.get("Elements"), list) or not existing_entry["Elements"]) and new_entry.get("Elements"):
        existing_entry["Elements"] = list(new_entry["Elements"])
        changed = True
    if (not isinstance(existing_entry.get("SpecialAvatars"), list) or not existing_entry["SpecialAvatars"]) and new_entry.get("SpecialAvatars"):
        existing_entry["SpecialAvatars"] = list(new_entry["SpecialAvatars"])
        changed = True
    if (not isinstance(existing_entry.get("InitialAvatars"), list) or not existing_entry["InitialAvatars"]) and new_entry.get("InitialAvatars"):
        existing_entry["InitialAvatars"] = list(new_entry["InitialAvatars"])
        changed = True
    return changed


def build_role_combat_schedule_entry(schedule_id: int, overview_entry: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "Id": schedule_id,
        "Begin": format_tower_time(overview_entry.get("begin")),
        "End": format_tower_time(overview_entry.get("end")),
        "Elements": build_role_combat_elements(overview_entry.get("element")),
        "SpecialAvatars": normalize_int_list(overview_entry.get("invite")),
        "InitialAvatars": normalize_int_list(overview_entry.get("buff")),
    }
    return normalize_value(entry)


def update_role_combat_from_remote(
    version: str,
    role_combat_schedule_path: Path,
) -> tuple[int, int, int]:
    role_combat_schedule_list = load_json(role_combat_schedule_path)
    if not isinstance(role_combat_schedule_list, list):
        raise ConversionError(f"RoleCombatSchedule 文件结构异常: {role_combat_schedule_path}")

    role_combat_overview = fetch_role_combat_overview(version)
    if not isinstance(role_combat_overview, dict):
        raise ConversionError(f"无法获取版本 {version} 的幻想真境剧诗数据")

    schedules_by_id: dict[int, dict[str, Any]] = {}
    for entry in role_combat_schedule_list:
        schedule_id = entry.get("Id")
        if isinstance(schedule_id, int) and schedule_id not in schedules_by_id:
            schedules_by_id[schedule_id] = entry

    added_count = 0
    updated_count = 0
    skipped_count = 0
    changed = False

    for raw_schedule_id, overview_entry in sorted(role_combat_overview.items(), key=lambda item: int(item[0])):
        try:
            schedule_id = int(raw_schedule_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的幻想真境剧诗 Id: {raw_schedule_id}")
            skipped_count += 1
            continue

        if not isinstance(overview_entry, dict):
            logger.warning(f"幻想真境剧诗 {schedule_id} 数据结构异常，已跳过")
            skipped_count += 1
            continue

        new_entry = build_role_combat_schedule_entry(schedule_id, overview_entry)
        existing_entry = schedules_by_id.get(schedule_id)
        if existing_entry is None:
            role_combat_schedule_list.append(new_entry)
            schedules_by_id[schedule_id] = new_entry
            added_count += 1
            changed = True
            logger.info(f"已添加幻想真境剧诗档期 {schedule_id} -> {role_combat_schedule_path}")
        else:
            if merge_missing_role_combat_fields(existing_entry, new_entry):
                updated_count += 1
                changed = True
                logger.info(f"已补充幻想真境剧诗档期 {schedule_id} 缺失信息")

    if changed:
        role_combat_schedule_list.sort(key=lambda entry: int(entry.get("Id", 0)))
        dump_json(role_combat_schedule_path, role_combat_schedule_list)

    return added_count, updated_count, skipped_count


def merge_missing_hard_challenge_fields(existing_entry: dict[str, Any], new_entry: dict[str, Any]) -> bool:
    changed = False
    if is_blank_string(existing_entry.get("Begin")) and new_entry.get("Begin"):
        existing_entry["Begin"] = new_entry["Begin"]
        changed = True
    if is_blank_string(existing_entry.get("End")) and new_entry.get("End"):
        existing_entry["End"] = new_entry["End"]
        changed = True
    if is_blank_string(existing_entry.get("Name")) and new_entry.get("Name"):
        existing_entry["Name"] = new_entry["Name"]
        changed = True
    return changed


def build_hard_challenge_schedule_entry(schedule_id: int, overview_entry: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "Id": schedule_id,
        "Begin": format_tower_time(overview_entry.get("begin")),
        "End": format_tower_time(overview_entry.get("end")),
        "Name": overview_entry.get("zh", ""),
    }
    return normalize_value(entry)


def update_hard_challenge_from_remote(
    version: str,
    hard_challenge_schedule_path: Path,
) -> tuple[int, int, int]:
    hard_challenge_schedule_list = load_json(hard_challenge_schedule_path)
    if not isinstance(hard_challenge_schedule_list, list):
        raise ConversionError(f"HardChallengeSchedule 文件结构异常: {hard_challenge_schedule_path}")

    hard_challenge_overview = fetch_hard_challenge_overview(version)
    if not isinstance(hard_challenge_overview, dict):
        raise ConversionError(f"无法获取版本 {version} 的幽境危战数据")

    schedules_by_id: dict[int, dict[str, Any]] = {}
    for entry in hard_challenge_schedule_list:
        schedule_id = entry.get("Id")
        if isinstance(schedule_id, int) and schedule_id not in schedules_by_id:
            schedules_by_id[schedule_id] = entry

    added_count = 0
    updated_count = 0
    skipped_count = 0
    changed = False

    for raw_schedule_id, overview_entry in sorted(hard_challenge_overview.items(), key=lambda item: int(item[0])):
        try:
            schedule_id = int(raw_schedule_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的幽境危战 Id: {raw_schedule_id}")
            skipped_count += 1
            continue

        if not isinstance(overview_entry, dict):
            logger.warning(f"幽境危战 {schedule_id} 数据结构异常，已跳过")
            skipped_count += 1
            continue

        new_entry = build_hard_challenge_schedule_entry(schedule_id, overview_entry)
        existing_entry = schedules_by_id.get(schedule_id)
        if existing_entry is None:
            hard_challenge_schedule_list.append(new_entry)
            schedules_by_id[schedule_id] = new_entry
            added_count += 1
            changed = True
            logger.info(f"已添加幽境危战档期 {schedule_id} -> {hard_challenge_schedule_path}")
        else:
            if merge_missing_hard_challenge_fields(existing_entry, new_entry):
                updated_count += 1
                changed = True
                logger.info(f"已补充幽境危战档期 {schedule_id} 缺失信息")

    if changed:
        hard_challenge_schedule_list.sort(key=lambda entry: int(entry.get("Id", 0)))
        dump_json(hard_challenge_schedule_path, hard_challenge_schedule_list)

    return added_count, updated_count, skipped_count

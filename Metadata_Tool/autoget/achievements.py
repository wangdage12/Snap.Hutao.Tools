from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .common import (
    ConversionError,
    dump_json,
    inject_achievement_description_param,
    load_json,
    logger,
    max_param_index,
    normalize_value,
    to_begin_time,
    trim_trailing_empty,
    trim_trailing_zeros,
)
from .remote import fetch_achievement_data, fetch_item_list

def build_achievement_goal_reward_index(item_data: Any) -> dict[str, dict[str, int]]:
    reward_index: dict[str, dict[str, int]] = {}
    if not isinstance(item_data, dict):
        return reward_index

    for raw_item_id, old_item in item_data.items():
        if not isinstance(old_item, dict):
            continue
        try:
            item_id = int(raw_item_id)
        except (TypeError, ValueError):
            continue

        for source in old_item.get("source_list", []):
            if not isinstance(source, str):
                continue
            match = re.fullmatch(r"达成「(.+)」下所有成就时获取。", source.strip())
            if not match:
                continue
            goal_name = match.group(1).strip()
            if goal_name and goal_name not in reward_index:
                reward_index[goal_name] = {"Id": item_id, "Count": 1}
    return reward_index



def build_achievement_entries_by_goal(
    achievement_list: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    entries_by_goal: dict[int, list[dict[str, Any]]] = {}
    for entry in achievement_list:
        goal_id = entry.get("Goal")
        if isinstance(goal_id, int):
            entries_by_goal.setdefault(goal_id, []).append(entry)
    return entries_by_goal



def build_achievement_reference_maps(
    achievement_list: list[dict[str, Any]],
    source_index: dict[int, dict[str, Any]],
) -> tuple[dict[tuple[int, str], dict[str, int]], dict[tuple[int, str], dict[str, Any]]]:
    delete_watcher_reference: dict[tuple[int, str], dict[str, int]] = {}
    icon_reference: dict[tuple[int, str], dict[str, Any]] = {}

    for entry in achievement_list:
        achievement_id = entry.get("Id")
        goal_id = entry.get("Goal")
        if not isinstance(achievement_id, int) or not isinstance(goal_id, int):
            continue

        source_entry = source_index.get(achievement_id)
        if not isinstance(source_entry, dict):
            continue
        trigger_config = source_entry.get("trigger_config")
        if not isinstance(trigger_config, dict):
            continue
        trigger_type = trigger_config.get("trigger_type")
        if not isinstance(trigger_type, str) or not trigger_type:
            continue

        key = (goal_id, trigger_type)
        delete_stats = delete_watcher_reference.setdefault(key, {"true": 0, "missing": 0})
        if entry.get("IsDeleteWatcherAfterFinish") is True:
            delete_stats["true"] += 1
        else:
            delete_stats["missing"] += 1

        icon_stats = icon_reference.setdefault(key, {"total": 0, "icons": {}})
        icon_stats["total"] += 1
        icon = entry.get("Icon")
        if isinstance(icon, str) and icon:
            icon_stats["icons"][icon] = icon_stats["icons"].get(icon, 0) + 1

    return delete_watcher_reference, icon_reference



def resolve_insert_index_by_order(

    entry_to_insert: dict[str, Any],
    entry_list: list[dict[str, Any]],
) -> int:
    target_order = entry_to_insert.get("Order")
    target_id = entry_to_insert.get("Id")
    if not isinstance(target_order, int):
        return len(entry_list)

    for index, entry in enumerate(entry_list):
        entry_order = entry.get("Order")
        if not isinstance(entry_order, int):
            continue
        if entry_order > target_order:
            return index
        if entry_order == target_order and isinstance(target_id, int):
            entry_id = entry.get("Id")
            if isinstance(entry_id, int) and entry_id > target_id:
                return index
    return len(entry_list)



def build_achievement_goal_entry(
    goal_id: int,
    old_goal: dict[str, Any],
    goal_reward_index: dict[str, dict[str, int]],
) -> dict[str, Any]:
    goal_order = old_goal.get("priority")
    goal_name = old_goal.get("name")
    goal_icon = old_goal.get("icon")

    if not isinstance(goal_order, int):
        raise ConversionError(f"成就集 {goal_id} 缺少合法的 priority")
    if not isinstance(goal_name, str) or not goal_name:
        raise ConversionError(f"成就集 {goal_id} 缺少合法的 name")
    if not isinstance(goal_icon, str) or not goal_icon:
        raise ConversionError(f"成就集 {goal_id} 缺少合法的 icon")

    goal_entry: dict[str, Any] = {
        "Id": goal_id,
        "Order": goal_order,
        "Name": goal_name,
        "Icon": goal_icon,
    }

    finish_reward = goal_reward_index.get(goal_name)
    if finish_reward:
        goal_entry["FinishReward"] = deepcopy(finish_reward)

    return normalize_value(goal_entry)



def resolve_achievement_icon(
    goal_id: int,
    achievement_title: str,
    trigger_type: str,
    goal_entries: list[dict[str, Any]],
    icon_reference: dict[tuple[int, str], dict[str, Any]],
) -> str | None:
    for entry in goal_entries:
        if entry.get("Title") == achievement_title:
            icon = entry.get("Icon")
            if isinstance(icon, str) and icon:
                return icon

    icon_stats = icon_reference.get((goal_id, trigger_type))
    if not isinstance(icon_stats, dict):
        return None
    icons = icon_stats.get("icons")
    total = icon_stats.get("total")
    if not isinstance(icons, dict) or not isinstance(total, int) or total <= 0:
        return None
    if len(icons) == 1 and sum(icons.values()) == total:
        return next(iter(icons))
    return None



def resolve_achievement_delete_watcher(
    goal_id: int,
    achievement_title: str,
    trigger_type: str,
    goal_entries: list[dict[str, Any]],
    delete_watcher_reference: dict[tuple[int, str], dict[str, int]],
) -> bool | None:
    for entry in goal_entries:
        if entry.get("Title") == achievement_title and "IsDeleteWatcherAfterFinish" in entry:
            return bool(entry["IsDeleteWatcherAfterFinish"])

    delete_stats = delete_watcher_reference.get((goal_id, trigger_type))
    if not isinstance(delete_stats, dict):
        return None
    true_count = delete_stats.get("true")
    missing_count = delete_stats.get("missing")
    if not isinstance(true_count, int) or not isinstance(missing_count, int):
        return None
    if true_count > 0 and missing_count == 0:
        return True
    if true_count >= 3 and true_count > missing_count * 3:
        return True
    return None



def build_achievement_entry(
    goal_id: int,
    old_achievement: dict[str, Any],
    version: str,
    goal_entries: list[dict[str, Any]],
    delete_watcher_reference: dict[tuple[int, str], dict[str, int]],
    icon_reference: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, Any]:

    achievement_id = old_achievement.get("id")
    order = old_achievement.get("priority")
    title = old_achievement.get("name")
    description = old_achievement.get("desc")
    progress = old_achievement.get("param")
    reward = old_achievement.get("reward")

    if not isinstance(achievement_id, int) or achievement_id <= 0:
        raise ConversionError(f"成就 Goal={goal_id} 缺少合法的 id")
    if not isinstance(order, int):
        raise ConversionError(f"成就 {achievement_id} 缺少合法的 priority")
    if not isinstance(title, str) or not title:
        raise ConversionError(f"成就 {achievement_id} 缺少合法的 name")
    if not isinstance(description, str) or not description:
        raise ConversionError(f"成就 {achievement_id} 缺少合法的 desc")
    if not isinstance(progress, int):
        raise ConversionError(f"成就 {achievement_id} 缺少合法的 param")
    if not isinstance(reward, dict):
        raise ConversionError(f"成就 {achievement_id} 缺少合法的 reward")

    reward_id = reward.get("item_id")
    reward_count = reward.get("item_count")
    if not isinstance(reward_id, int) or not isinstance(reward_count, int):
        raise ConversionError(f"成就 {achievement_id} 缺少合法的奖励字段")

    trigger_config = old_achievement.get("trigger_config")
    if not isinstance(trigger_config, dict):
        raise ConversionError(f"成就 {achievement_id} 缺少合法的 trigger_config")
    trigger_type = trigger_config.get("trigger_type")
    if not isinstance(trigger_type, str) or not trigger_type:
        raise ConversionError(f"成就 {achievement_id} 缺少合法的 trigger_type")

    achievement_entry: dict[str, Any] = {
        "Id": achievement_id,
        "Goal": goal_id,
        "Order": order,
        "Title": title,
        "Description": inject_achievement_description_param(description, progress),
        "FinishReward": {
            "Id": reward_id,
            "Count": reward_count,
        },
        "Progress": progress,
        "Version": version,
    }


    previous_id = old_achievement.get("prev")
    if isinstance(previous_id, int) and previous_id > 0:
        achievement_entry["PreviousId"] = previous_id

    icon = resolve_achievement_icon(goal_id, title, trigger_type, goal_entries, icon_reference)
    if icon:
        achievement_entry["Icon"] = icon

    delete_watcher = resolve_achievement_delete_watcher(
        goal_id,
        title,
        trigger_type,
        goal_entries,
        delete_watcher_reference,
    )
    if delete_watcher is not None:
        achievement_entry["IsDeleteWatcherAfterFinish"] = delete_watcher

    return normalize_value(achievement_entry)




def update_achievements_from_remote(
    version: str,
    achievement_goal_path: Path,
    achievement_path: Path,
) -> tuple[int, int, int, int]:
    achievement_goal_list = load_json(achievement_goal_path)
    if not isinstance(achievement_goal_list, list):
        raise ConversionError(f"AchievementGoal 文件结构异常: {achievement_goal_path}")

    achievement_list = load_json(achievement_path)
    if not isinstance(achievement_list, list):
        raise ConversionError(f"Achievement 文件结构异常: {achievement_path}")

    achievement_data = fetch_achievement_data(version)
    if not isinstance(achievement_data, dict):
        raise ConversionError(f"无法获取版本 {version} 的成就数据")

    item_data = fetch_item_list(version)
    goal_reward_index = build_achievement_goal_reward_index(item_data)

    existing_goal_ids: set[int] = set()
    duplicate_goal_ids: set[int] = set()
    for entry in achievement_goal_list:
        goal_id = entry.get("Id")
        if not isinstance(goal_id, int):
            continue
        if goal_id in existing_goal_ids:
            duplicate_goal_ids.add(goal_id)
            continue
        existing_goal_ids.add(goal_id)

    for duplicate_goal_id in sorted(duplicate_goal_ids):
        logger.warning(f"AchievementGoal.json 中已存在重复成就集 Id: {duplicate_goal_id}，本次将跳过新增")

    existing_achievement_ids: set[int] = set()
    duplicate_achievement_ids: set[int] = set()
    for entry in achievement_list:
        achievement_id = entry.get("Id")
        if not isinstance(achievement_id, int):
            continue
        if achievement_id in existing_achievement_ids:
            duplicate_achievement_ids.add(achievement_id)
            continue
        existing_achievement_ids.add(achievement_id)

    for duplicate_achievement_id in sorted(duplicate_achievement_ids):
        logger.warning(f"Achievement.json 中已存在重复成就 Id: {duplicate_achievement_id}，本次将跳过新增")

    achievement_entries_by_goal = build_achievement_entries_by_goal(achievement_list)

    source_goals: list[tuple[int, dict[str, Any]]] = []
    achievement_source_index: dict[int, dict[str, Any]] = {}
    goal_skipped_count = 0
    for raw_goal_id, old_goal in achievement_data.items():
        try:
            goal_id = int(raw_goal_id)
        except (TypeError, ValueError):
            logger.warning(f"跳过无法识别的成就集 Id: {raw_goal_id}")
            goal_skipped_count += 1
            continue
        if not isinstance(old_goal, dict):
            logger.warning(f"成就集 {goal_id} 数据结构异常，已跳过")
            goal_skipped_count += 1
            continue
        source_goals.append((goal_id, old_goal))
        goal_items = old_goal.get("list")
        if not isinstance(goal_items, list):
            continue
        for old_achievement in goal_items:
            if not isinstance(old_achievement, dict):
                continue
            achievement_id = old_achievement.get("id")
            if isinstance(achievement_id, int) and achievement_id > 0:
                achievement_source_index[achievement_id] = old_achievement

    delete_watcher_reference, icon_reference = build_achievement_reference_maps(
        achievement_list,
        achievement_source_index,
    )

    source_goals.sort(

        key=lambda item: (
            item[1].get("priority") if isinstance(item[1].get("priority"), int) else 10**9,
            item[0],
        )
    )

    goal_added_count = 0
    achievement_added_count = 0
    achievement_skipped_count = 0
    achievement_goal_changed = False
    achievement_list_changed = False

    for goal_id, old_goal in source_goals:
        if goal_id not in existing_goal_ids:
            try:
                goal_entry = build_achievement_goal_entry(goal_id, old_goal, goal_reward_index)
            except ConversionError as exc:
                goal_skipped_count += 1
                logger.warning(f"成就集 {goal_id} 转换失败，已跳过: {exc}")
                continue

            insert_index = resolve_insert_index_by_order(goal_entry, achievement_goal_list)
            achievement_goal_list.insert(insert_index, goal_entry)
            existing_goal_ids.add(goal_id)
            goal_added_count += 1
            achievement_goal_changed = True
            logger.info(f"已添加成就集 {goal_id} -> {achievement_goal_path}")

        goal_entries = achievement_entries_by_goal.setdefault(goal_id, [])
        goal_items = old_goal.get("list")
        if not isinstance(goal_items, list):
            logger.warning(f"成就集 {goal_id} 缺少合法的 list 数据，跳过其下成就")
            continue

        sorted_goal_items = sorted(
            goal_items,
            key=lambda item: (
                item.get("priority") if isinstance(item, dict) and isinstance(item.get("priority"), int) else 10**9,
                item.get("id") if isinstance(item, dict) and isinstance(item.get("id"), int) else 10**9,
            ),
        )

        for old_achievement in sorted_goal_items:
            if not isinstance(old_achievement, dict):
                achievement_skipped_count += 1
                logger.warning(f"成就集 {goal_id} 存在异常的成就结构，已跳过")
                continue

            achievement_id = old_achievement.get("id")
            if not isinstance(achievement_id, int) or achievement_id <= 0:
                achievement_skipped_count += 1
                logger.warning(f"成就集 {goal_id} 存在无法识别的成就 Id: {achievement_id}")
                continue
            if achievement_id in existing_achievement_ids:
                continue

            try:
                achievement_entry = build_achievement_entry(
                    goal_id,
                    old_achievement,
                    version,
                    goal_entries,
                    delete_watcher_reference,
                    icon_reference,
                )
            except ConversionError as exc:

                achievement_skipped_count += 1
                logger.warning(f"成就 {achievement_id} 转换失败，已跳过: {exc}")
                continue

            insert_index = resolve_insert_index_by_order(achievement_entry, achievement_list)
            achievement_list.insert(insert_index, achievement_entry)
            goal_entries.append(achievement_entry)
            existing_achievement_ids.add(achievement_id)
            achievement_added_count += 1
            achievement_list_changed = True
            logger.info(f"已添加成就 {achievement_id} -> {achievement_path}")

    if achievement_goal_changed:
        dump_json(achievement_goal_path, achievement_goal_list)
    if achievement_list_changed:
        dump_json(achievement_path, achievement_list)

    return goal_added_count, goal_skipped_count, achievement_added_count, achievement_skipped_count

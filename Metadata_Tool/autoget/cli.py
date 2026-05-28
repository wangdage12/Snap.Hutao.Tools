from __future__ import annotations

import json
import shutil
from pathlib import Path

from .achievements import update_achievements_from_remote
from .common import convert_game_data, load_json, logger
from .events import (
    update_hard_challenge_from_remote,
    update_role_combat_from_remote,
    update_tower_from_remote,
)
from .materials import update_materials_from_item_list
from .monsters import update_monsters_from_manifest
from .remote import (
    download_character_images,
    fetch_character_details,
    fetch_item_list,
    fetch_manifest,
)
from .weapons import (
    update_avatar_promotes,
    update_weapon_promotes,
    update_weapons_from_manifest,
)

def main():


    manifest_data = fetch_manifest()
    if manifest_data is None:
        logger.error("无法继续处理，因为清单数据获取失败")
        return
    
    gi_latest = manifest_data['gi']['latest']
    gi_live = manifest_data['gi']['live']
    if gi_latest is None or gi_live is None:
        logger.error("清单数据中缺少gi.latest或gi.live字段")
        return
    logger.info(f"最新测试版本: {gi_latest}   最新正式版本: {gi_live}")
    
    # 询问获取最新版本还是手动输入版本
    version_choice = input("请输入版本号（输入 'latest' 获取最新测试版本，输入 'live' 获取最新正式版本，或直接输入版本号）: ").strip()
    if version_choice.lower() == 'latest':
        version = gi_latest
    elif version_choice.lower() == 'live':
        version = gi_live
    else:
        version = version_choice
    logger.info(f"选择的版本: {version}")
    
    # 创建 old 和 new 文件夹
    old_folder = Path("old")
    new_folder = Path("new")
    old_folder.mkdir(exist_ok=True)
    new_folder.mkdir(exist_ok=True)
    # 检查Genshin\CHS文件夹是否存在
    genshin_folder = Path("Genshin/CHS")
    if not genshin_folder.exists():
        logger.error("Genshin/CHS 文件夹不存在，请将工具放在元数据文件夹中并重试")
        return

    if version_choice.lower() == 'latest': # 增量更新
        # 新角色数据gi.new.character
        new_character = manifest_data['gi']['new']['character']
        if new_character is None:
            logger.error("最新版本没有找到新角色数据")
        else:
            # 第一步：下载所有新角色数据到old文件夹
            logger.info(f"开始下载 {len(new_character)} 个新角色数据")
            for character_id in new_character:
                character_details = fetch_character_details(version, character_id)
                if character_details is not None:
                    with open(f"old/{character_id}.json", "w", encoding="utf-8") as f:
                        json.dump(character_details, f, ensure_ascii=False, indent=4)
                    logger.info(f"成功保存角色 {character_id} 的数据到 old 文件夹")
                else:
                    logger.warning(f"无法获取角色 {character_id} 的数据")
            
            # 第二步：一次性转换所有新角色数据
            logger.info("开始转换所有新角色数据")
            old_path = Path("old").resolve()
            new_path = Path("new").resolve()
            convert_game_data(old_path, new_path)
            
            # 第三步：复制转换后的文件到Genshin\CHS\Avatar
            logger.info("开始复制转换后的文件")
            converted_files = list(new_path.glob("*.json"))
            for file in converted_files:
                target_path = genshin_folder / "Avatar" / file.name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                # 如果目标文件已存在，先删除它
                if target_path.exists():
                    target_path.unlink()
                shutil.copy2(file, target_path)
                
                logger.info(f"已将 {file.name} 复制到 {target_path}")
            
            # 第四步：下载所有角色的图片，并补充 AvatarPromote
            logger.info("开始下载角色图片并更新 AvatarPromote")
            avatar_folder = new_path.resolve()
            promote_ids: list[int] = []
            for file in avatar_folder.glob("*.json"):
                character_data = load_json(file)
                promote_id = character_data.get("PromoteId")
                if isinstance(promote_id, int):
                    promote_ids.append(promote_id)
                download_character_images(character_data)

            avatar_promote_path = genshin_folder / "AvatarPromote.json"
            promote_added_count, promote_skipped_count, promote_duplicate_count = update_avatar_promotes(
                promote_ids,
                avatar_promote_path,
            )
            logger.info(
                f"角色处理完成：角色文件 {len(converted_files)} 个，AvatarPromote 新增 {promote_added_count} 条，跳过 {promote_skipped_count} 个角色，检测到 {promote_duplicate_count} 个重复条目"
            )

        # 更新道具
        new_items = manifest_data['gi']['new']['item']
        if new_items is None:
            logger.error("最新版本没有找到新道具数据")
        else:
            logger.info(f"开始处理 {len(new_items)} 个新道具")
            item_data = fetch_item_list(version)
            if item_data is None:
                logger.error("无法获取 item_all.json，道具更新终止")
            else:
                material_path = genshin_folder / "Material.json"
                added_count, skipped_count, duplicate_count = update_materials_from_item_list(
                    item_data,
                    new_items,
                    material_path,
                )
                logger.info(
                    f"道具处理完成：新增 {added_count} 个，跳过 {skipped_count} 个，检测到 {duplicate_count} 个重复 Id"
                )

        # 更新武器
        new_weapons = manifest_data['gi']['new']['weapon']
        if new_weapons is None:
            logger.error("最新版本没有找到新武器数据")
        else:
            logger.info(f"开始处理 {len(new_weapons)} 个新武器")
            weapon_path = genshin_folder / "Weapon.json"
            weapon_promote_path = genshin_folder / "WeaponPromote.json"
            valid_weapon_ids, weapon_added_count, weapon_skipped_count, weapon_duplicate_count = update_weapons_from_manifest(
                version,
                new_weapons,
                weapon_path,
            )
            promote_added_count, promote_skipped_count, promote_duplicate_count = update_weapon_promotes(
                valid_weapon_ids,
                weapon_promote_path,
            )
            logger.info(
                f"武器处理完成：Weapon 新增 {weapon_added_count} 个，Weapon 跳过 {weapon_skipped_count} 个，Weapon 重复 {weapon_duplicate_count} 个；"
                f"WeaponPromote 新增 {promote_added_count} 条，WeaponPromote 跳过 {promote_skipped_count} 个武器，WeaponPromote 重复 {promote_duplicate_count} 个条目"
            )

        # 更新怪物
        new_monsters = manifest_data['gi']['new']['monster']
        if new_monsters is None:
            logger.error("最新版本没有找到新怪物数据")
        else:
            logger.info(f"开始处理 {len(new_monsters)} 个新怪物")
            monster_path = genshin_folder / "Monster.json"
            monster_added_count, monster_skipped_count, monster_duplicate_count = update_monsters_from_manifest(
                version,
                new_monsters,
                monster_path,
            )
            logger.info(
                f"怪物处理完成：Monster 新增 {monster_added_count} 个，跳过 {monster_skipped_count} 个，检测到 {monster_duplicate_count} 个重复 Id"
            )

        # 更新成就（仅通过对比远端全量数据与本地现有数据补齐缺失项）
        tower_schedule_path = genshin_folder / "TowerSchedule.json"
        tower_floor_path = genshin_folder / "TowerFloor.json"
        tower_level_path = genshin_folder / "TowerLevel.json"
        monster_path = genshin_folder / "Monster.json"
        (
            tower_schedule_added_count,
            tower_schedule_updated_count,
            tower_floor_added_count,
            tower_floor_updated_count,
            tower_level_added_count,
            tower_level_updated_count,
            tower_detail_skipped_count,
        ) = update_tower_from_remote(
            version,
            tower_schedule_path,
            tower_floor_path,
            tower_level_path,
            monster_path,
        )
        logger.info(
            f"深境螺旋处理完成：TowerSchedule 新增 {tower_schedule_added_count} 期，补充 {tower_schedule_updated_count} 期；"
            f"TowerFloor 新增 {tower_floor_added_count} 层，补充 {tower_floor_updated_count} 层；"
            f"TowerLevel 新增 {tower_level_added_count} 间，补充 {tower_level_updated_count} 间，详情跳过 {tower_detail_skipped_count} 期"
        )

        role_combat_schedule_path = genshin_folder / "RoleCombatSchedule.json"
        role_combat_added_count, role_combat_updated_count, role_combat_skipped_count = update_role_combat_from_remote(
            version,
            role_combat_schedule_path,
        )
        logger.info(
            f"幻想真境剧诗处理完成：RoleCombatSchedule 新增 {role_combat_added_count} 期，补充 {role_combat_updated_count} 期，跳过 {role_combat_skipped_count} 期"
        )

        hard_challenge_schedule_path = genshin_folder / "HardChallengeSchedule.json"
        hard_challenge_added_count, hard_challenge_updated_count, hard_challenge_skipped_count = update_hard_challenge_from_remote(
            version,
            hard_challenge_schedule_path,
        )
        logger.info(
            f"幽境危战处理完成：HardChallengeSchedule 新增 {hard_challenge_added_count} 期，补充 {hard_challenge_updated_count} 期，跳过 {hard_challenge_skipped_count} 期"
        )

        achievement_goal_path = genshin_folder / "AchievementGoal.json"
        achievement_path = genshin_folder / "Achievement.json"
        goal_added_count, goal_skipped_count, achievement_added_count, achievement_skipped_count = update_achievements_from_remote(
            version,
            achievement_goal_path,
            achievement_path,
        )
        logger.info(
            f"成就处理完成：AchievementGoal 新增 {goal_added_count} 个，跳过 {goal_skipped_count} 个；"
            f"Achievement 新增 {achievement_added_count} 个，跳过 {achievement_skipped_count} 个"
        )

    else: # 更新缺失的数据




        # 获取版本的角色列表
        ...

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from .common import icon_to_side_icon, logger, picture_prefix_from_namecard_icon

def fetch_manifest():
    url = "https://static.nanoka.cc/manifest.json"
    try:
        response = requests.get(url)
        response.raise_for_status()  # 检查请求是否成功
        manifest_data = response.json()
        logger.debug("成功获取清单数据")
        return manifest_data
    except requests.RequestException as e:
        logger.error(f"获取清单数据失败: {e}")
        return None

# 获取角色列表 https://static.nanoka.cc/gi/{ version }/character.json
def fetch_character_list(version):
    url = f"https://static.nanoka.cc/gi/{version}/character.json"
    try:
        response = requests.get(url)
        response.raise_for_status()  # 检查请求是否成功
        character_data = response.json()
        logger.debug(f"成功获取版本 {version} 的角色数据")
        return character_data
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的角色数据失败: {e}")
        return None

# 获取角色详情 https://static.nanoka.cc/gi/6.4.54/zh/character/10000130.json
def fetch_character_details(version, character_id):
    url = f"https://static.nanoka.cc/gi/{version}/zh/character/{character_id}.json"
    try:
        response = requests.get(url)
        response.raise_for_status()  # 检查请求是否成功
        character_details = response.json()
        logger.debug(f"成功获取版本 {version} 的角色详情: {character_id}")
        return character_details
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的角色详情失败: {e}")
        return None

# 获取武器详情 https://static.nanoka.cc/gi/6.4.54/zh/weapon/15515.json
def fetch_weapon_details(version, weapon_id):
    url = f"https://static.nanoka.cc/gi/{version}/zh/weapon/{weapon_id}.json"
    try:
        response = requests.get(url)
        response.raise_for_status()  # 检查请求是否成功
        weapon_details = response.json()
        logger.debug(f"成功获取版本 {version} 的武器详情: {weapon_id}")
        return weapon_details
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的武器详情失败: {e}")
        return None

# 获取怪物详情 https://static.nanoka.cc/gi/6.4.54/zh/monster/24090501.json
def fetch_monster_details(version, monster_id):
    url = f"https://static.nanoka.cc/gi/{version}/zh/monster/{monster_id}.json"
    try:
        response = requests.get(url)
        response.raise_for_status()  # 检查请求是否成功
        monster_details = response.json()
        logger.debug(f"成功获取版本 {version} 的怪物详情: {monster_id}")
        return monster_details
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的怪物详情失败: {e}")
        return None

# 获取成就总表 https://static.nanoka.cc/gi/6.5/zh/achievement/achievement.json
def fetch_achievement_data(version):
    url = f"https://static.nanoka.cc/gi/{version}/zh/achievement/achievement.json"
    try:
        response = requests.get(url)
        response.raise_for_status()  # 检查请求是否成功
        achievement_data = response.json()
        logger.debug(f"成功获取版本 {version} 的成就数据")
        return achievement_data
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的成就数据失败: {e}")
        return None
    

def download_image(image_name, image_folder, subfolder=""):



    url = f"https://static.nanoka.cc/assets/gi/{image_name}.webp"
    try:
        # 创建包含子文件夹的路径
        if subfolder:
            save_folder = Path(image_folder) / subfolder
        else:
            save_folder = Path(image_folder)
        save_folder.mkdir(parents=True, exist_ok=True)

        target_png_path = save_folder / f"{image_name}.png"
        if target_png_path.exists():
            logger.debug(f"图片已存在，跳过下载: {target_png_path}")
            return

        response = requests.get(url)
        response.raise_for_status()  # 检查请求是否成功
        image_path = save_folder / f"{image_name}.webp"
        with open(image_path, "wb") as f:
            f.write(response.content)
        logger.debug(f"成功下载图片: {image_name} 到 {subfolder if subfolder else '根目录'}")
        # 下载以后将webp图片转换为png格式，并删除原来的webp图片，注意保留原文件的所有属性
        from PIL import Image
        with Image.open(image_path) as img:
            img.save(target_png_path, "PNG")
        image_path.unlink()  # 删除原来的webp图片
        logger.debug(f"成功转换图片格式: {image_name}.webp -> {target_png_path.name}")

    except requests.RequestException as e:
        logger.error(f"下载图片失败: {image_name}, 错误: {e}")

    
# 获取角色数据中的图片链接并下载图片，输入新角色数据的文件夹路径和图片保存的文件夹路径
def download_character_images(character_data, image_folder="static/raw"):
    """
    文件路径规则：
    基础路径：static/raw
    请求url:https://static.nanoka.cc/assets/gi/{文件名}.webp
    Icon：AvatarIcon
    SideIcon：AvatarIcon和AvatarIcon_Side都存一个
    SkillDepot.Skills.遍历每个技能.Icon：Skill
    SkillDepot.EnergySkill.Icon：Skill
    SkillDepot.Inherents.遍历每个固有被动.Icon：Talent
    SkillDepot.Talents.遍历每个命座.Icon：Talent
    NameCard.Icon：NameCardIcon
    NameCard.PicturePrefix+_P：NameCardPic
    NameCard.PicturePrefix+_Alpha：NameCardPicAlpha
    """
    image_folder = Path(image_folder)
    image_folder.mkdir(parents=True, exist_ok=True)

    # 下载 Icon 和 SideIcon 到 AvatarIcon 子目录
    for icon_type in ["Icon", "SideIcon"]:
        icon_name = character_data.get(icon_type, "")
        if icon_name:
            download_image(icon_name, image_folder, "AvatarIcon")

    # 下载技能图标到 Skill 子目录
    skill_depot = character_data.get("SkillDepot", {})
    # 下载普通技能（前两个）
    for skill in skill_depot.get("Skills", []):
        icon_name = skill.get("Icon", "")
        if icon_name:
            download_image(icon_name, image_folder, "Skill")
    
    # 下载元素爆发
    energy_skill = skill_depot.get("EnergySkill", {})
    if energy_skill:
        icon_name = energy_skill.get("Icon", "")
        if icon_name:
            download_image(icon_name, image_folder, "Skill")
    
    # 下载天赋（固有被动和命座）到 Talent 子目录
    for inherent in skill_depot.get("Inherents", []):
        icon_name = inherent.get("Icon", "")
        if icon_name:
            download_image(icon_name, image_folder, "Talent")
    
    for talent in skill_depot.get("Talents", []):
        icon_name = talent.get("Icon", "")
        if icon_name:
            download_image(icon_name, image_folder, "Talent")

    # 下载名片图标和图片
    name_card = character_data.get("NameCard", {})
    name_card_icon = name_card.get("Icon", "")
    picture_prefix = name_card.get("PicturePrefix", "")
    
    if name_card_icon:
        download_image(name_card_icon, image_folder, "NameCardIcon")
    
    if picture_prefix:
        download_image(picture_prefix + "_P", image_folder, "NameCardPic")
        download_image(picture_prefix + "_Alpha", image_folder, "NameCardPicAlpha")

    # 下载抽卡立绘图片到 GachaAvatarImg 子目录
    icon_name = character_data.get("Icon", "")
    if icon_name:
        # 从 Icon 中提取角色英文名（使用_分隔的最后一段）
        english_name = icon_name.split("_")[-1]
        gacha_image_name = f"UI_Gacha_AvatarImg_{english_name}"
        download_image(gacha_image_name, image_folder, "GachaAvatarImg")

# 获取道具列表https://static.nanoka.cc/gi/{version}/zh/item_all.json
def fetch_item_list(version):
    url = f"https://static.nanoka.cc/gi/{version}/zh/item_all.json"
    try:
        response = requests.get(url)
        response.raise_for_status()  # 检查请求是否成功
        item_data = response.json()
        logger.debug(f"成功获取版本 {version} 的道具数据")
        return item_data
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的道具数据失败: {e}")
        return None


def fetch_tower_overview(version):
    url = f"https://static.nanoka.cc/gi/{version}/tower.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        tower_overview = response.json()
        logger.debug(f"成功获取版本 {version} 的深境螺旋总览数据")
        return tower_overview
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的深境螺旋总览数据失败: {e}")
        return None


def fetch_tower_details(version, tower_id):
    url = f"https://static.nanoka.cc/gi/{version}/zh/tower/{tower_id}.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        tower_details = response.json()
        logger.debug(f"成功获取版本 {version} 的深境螺旋 {tower_id} 详情")
        return tower_details
    except requests.RequestException as e:
        logger.warning(f"获取版本 {version} 的深境螺旋 {tower_id} 详情失败: {e}")
        return None


def fetch_role_combat_overview(version):
    url = f"https://static.nanoka.cc/gi/{version}/rolecombat.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        role_combat_overview = response.json()
        logger.debug(f"成功获取版本 {version} 的幻想真境剧诗总览数据")
        return role_combat_overview
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的幻想真境剧诗总览数据失败: {e}")
        return None


def fetch_hard_challenge_overview(version):
    url = f"https://static.nanoka.cc/gi/{version}/leyline.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        hard_challenge_overview = response.json()
        logger.debug(f"成功获取版本 {version} 的幽境危战总览数据")
        return hard_challenge_overview
    except requests.RequestException as e:
        logger.error(f"获取版本 {version} 的幽境危战总览数据失败: {e}")
        return None


def download_material_images(material_data: dict[str, Any], image_folder: str | Path = "static/raw"):

    image_folder = Path(image_folder)
    image_folder.mkdir(parents=True, exist_ok=True)

    icon_name = material_data.get("Icon", "")
    if icon_name:
        download_image(icon_name, image_folder, "ItemIcon")

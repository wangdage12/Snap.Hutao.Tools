from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import coloredlogs

logger = logging.getLogger(__name__)
coloredlogs.install(level="DEBUG", logger=logger)

WEAPON_MAP = {
    "WEAPON_SWORD_ONE_HAND": 1,
    "WEAPON_CATALYST": 10,
    "WEAPON_CLAYMORE": 11,
    "WEAPON_POLE": 12,
    "WEAPON_BOW": 13,
}
WEAPON_METADATA_TYPE_MAP = {
    "WEAPON_SWORD_ONE_HAND": 1,
    "WEAPON_CATALYST": 10,
    "WEAPON_CLAYMORE": 11,
    "WEAPON_BOW": 12,
    "WEAPON_POLE": 13,
}
WEAPON_SORT_GROUP_MAP = {
    1: 1,
    11: 2,
    13: 3,
    10: 4,
    12: 5,
}

QUALITY_MAP = {

    "QUALITY_PURPLE": 4,
    "QUALITY_ORANGE": 5,
}

PROP_TYPE_MAP = {
    "FIGHT_PROP_BASE_HP": 1,
    "FIGHT_PROP_BASE_ATTACK": 4,
    "FIGHT_PROP_BASE_DEFENSE": 7,
}
WEAPON_PROP_TYPE_MAP = {
    "FIGHT_PROP_HP_PERCENT": 3,
    "FIGHT_PROP_BASE_ATTACK": 4,
    "FIGHT_PROP_ATTACK_PERCENT": 6,
    "FIGHT_PROP_DEFENSE_PERCENT": 9,
    "FIGHT_PROP_CRITICAL": 20,
    "FIGHT_PROP_CRITICAL_HURT": 22,
    "FIGHT_PROP_CHARGE_EFFICIENCY": 23,
    "FIGHT_PROP_ELEMENT_MASTERY": 28,
    "FIGHT_PROP_PHYSICAL_ADD_HURT": 30,
}
MONSTER_TYPE_MAP = {
    "MONSTER_ORDINARY": 1,
    "MONSTER_BOSS": 2,
}
MONSTER_CURVE_VALUE_MAP = {
    "GROW_CURVE_HP": 1,
    "GROW_CURVE_ATTACK": 2,
    "GROW_CURVE_DEFENSE": 12,
    "GROW_CURVE_HP_2": 23,
    "GROW_CURVE_ATTACK_2": 24,
    "GROW_CURVE_HP_3": 25,
}
MONSTER_SUB_HURT_FIELD_MAP = {
    "fire": "FireSubHurt",
    "grass": "GrassSubHurt",
    "water": "WaterSubHurt",
    "elec": "ElecSubHurt",
    "wind": "WindSubHurt",
    "ice": "IceSubHurt",
    "rock": "RockSubHurt",
    "physical": "PhysicalSubHurt",
}

DEFAULT_ASSOCIATION_MAP = {


    "ASSOC_TYPE_NATLAN": 9,
    "ASSOC_TYPE_NODKRAI": 12,
}

SKILL_SUFFIXES = (31, 32, 39)
EXTRA_LEVEL_MAP = {
    2: {"Index": 9, "Level": 3},
    4: {"Index": 2, "Level": 3},
}
TOWER_BACKGROUND_MAP = {
    9: "UI_TowerPic_4",
    10: "UI_TowerPic_4",
    11: "UI_TowerPic_4",
    12: "UI_TowerPic_5",
}
ROLE_COMBAT_ELEMENT_MAP = {
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    6: 5,
    7: 7,
    8: 8,
}
UNKNOWN_MATERIAL_ID = 114514
DEFAULT_MATERIAL_TEMPLATE = {
    "Rank": 317,
    "MaterialType": 4,
    "RankLevel": 0,
    "ItemType": 2,
    "Name": "",
    "Description": "",
    "TypeDescription": "",
    "Icon": "",
}
DEFAULT_AVATAR_PROMOTE_TEMPLATE = [
    {
        "Level": 0,
        "AddProperties": [
            {"Type": 1, "Value": 0},
            {"Type": 7, "Value": 0},
            {"Type": 4, "Value": 0},
            {"Type": 22, "Value": 0},
        ],
    },
    {
        "Level": 1,
        "AddProperties": [
            {"Type": 1, "Value": 841.9073},
            {"Type": 7, "Value": 53.0955},
            {"Type": 4, "Value": 23.546604},
            {"Type": 22, "Value": 0},
        ],
    },
    {
        "Level": 2,
        "AddProperties": [
            {"Type": 1, "Value": 1440.1045},
            {"Type": 7, "Value": 90.82125},
            {"Type": 4, "Value": 40.27709},
            {"Type": 22, "Value": 0.096},
        ],
    },
    {
        "Level": 3,
        "AddProperties": [
            {"Type": 1, "Value": 2237.701},
            {"Type": 7, "Value": 141.12225},
            {"Type": 4, "Value": 62.584396},
            {"Type": 22, "Value": 0.192},
        ],
    },
    {
        "Level": 4,
        "AddProperties": [
            {"Type": 1, "Value": 2835.8982},
            {"Type": 7, "Value": 178.848},
            {"Type": 4, "Value": 79.31488},
            {"Type": 22, "Value": 0.192},
        ],
    },
    {
        "Level": 5,
        "AddProperties": [
            {"Type": 1, "Value": 3434.0955},
            {"Type": 7, "Value": 216.57375},
            {"Type": 4, "Value": 96.045364},
            {"Type": 22, "Value": 0.288},
        ],
    },
    {
        "Level": 6,
        "AddProperties": [
            {"Type": 1, "Value": 4032.2927},
            {"Type": 7, "Value": 254.2995},
            {"Type": 4, "Value": 112.77585},
            {"Type": 22, "Value": 0.384},
        ],
    },
]
DEFAULT_WEAPON_PROMOTE_TEMPLATE = [
    {
        "Level": 0,
        "AddProperties": [
            {"Type": 4, "Value": 0},
            {"Type": 20, "Value": 0},
            {"Type": 22, "Value": 0},
            {"Type": 23, "Value": 0},
            {"Type": 28, "Value": 0},
        ],
    },
    {
        "Level": 1,
        "AddProperties": [
            {"Type": 4, "Value": 25.9},
            {"Type": 20, "Value": 0},
            {"Type": 22, "Value": 0},
            {"Type": 23, "Value": 0},
            {"Type": 28, "Value": 0},
        ],
    },
    {
        "Level": 2,
        "AddProperties": [
            {"Type": 4, "Value": 51.9},
            {"Type": 20, "Value": 0},
            {"Type": 22, "Value": 0},
            {"Type": 23, "Value": 0},
            {"Type": 28, "Value": 0},
        ],
    },
    {
        "Level": 3,
        "AddProperties": [
            {"Type": 4, "Value": 77.8},
            {"Type": 20, "Value": 0},
            {"Type": 22, "Value": 0},
            {"Type": 23, "Value": 0},
            {"Type": 28, "Value": 0},
        ],
    },
    {
        "Level": 4,
        "AddProperties": [
            {"Type": 4, "Value": 103.7},
            {"Type": 20, "Value": 0},
            {"Type": 22, "Value": 0},
            {"Type": 23, "Value": 0},
            {"Type": 28, "Value": 0},
        ],
    },
    {
        "Level": 5,
        "AddProperties": [
            {"Type": 4, "Value": 129.7},
            {"Type": 20, "Value": 0},
            {"Type": 22, "Value": 0},
            {"Type": 23, "Value": 0},
            {"Type": 28, "Value": 0},
        ],
    },
    {
        "Level": 6,
        "AddProperties": [
            {"Type": 4, "Value": 155.6},
            {"Type": 20, "Value": 0},
            {"Type": 22, "Value": 0},
            {"Type": 23, "Value": 0},
            {"Type": 28, "Value": 0},
        ],
    },
]


class ConversionError(Exception):



    pass


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def trim_trailing_zeros(values: list[Any]) -> list[Any]:
    result = list(values)
    while result and result[-1] == 0:
        result.pop()
    return result


def trim_trailing_empty(values: list[str]) -> list[str]:
    result = list(values)
    while result and result[-1] == "":
        result.pop()
    return result


def max_param_index(descriptions: list[str]) -> int:
    indexes = [int(match) for desc in descriptions for match in re.findall(r"param(\d+)", desc)]
    return max(indexes, default=0)


def inject_achievement_description_param(description: str, progress: int) -> str:
    return description.replace("{param0}", str(progress))


def normalize_value(value: Any) -> Any:

    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, str):
        return value.replace("\\n", "\n")
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_value(item) for key, item in value.items()}
    return value



def to_begin_time(value: str) -> str:
    value = (value or "1970-01-01 00:00:00").strip()
    if "T" in value and (value.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", value)):
        return value
    return value.replace(" ", "T") + "+08:00"


def icon_to_side_icon(icon: str) -> str:
    if icon.startswith("UI_AvatarIcon_"):
        return icon.replace("UI_AvatarIcon_", "UI_AvatarIcon_Side_", 1)
    return icon


def grow_curve_value(name: str) -> int:
    if name.endswith("_S5"):
        return 31 if "ATTACK" in name else 21
    if name.endswith("_S4"):
        return 30 if "ATTACK" in name else 20
    raise ConversionError(f"未识别的成长曲线: {name}")


def file_id(path: Path) -> int:
    try:
        return int(path.stem)
    except ValueError as exc:
        raise ConversionError(f"文件名不是纯数字 ID: {path.name}") from exc


def promote_id(character_id: int) -> int:
    return character_id % 1000


def picture_prefix_from_namecard_icon(icon: str) -> tuple[str, str]:
    picture_prefix = icon.removesuffix("_P")
    if picture_prefix.startswith("UI_NameCardPic_"):
        icon_name = picture_prefix.replace("UI_NameCardPic_", "UI_NameCardIcon_", 1)
    else:
        icon_name = picture_prefix
    return icon_name, picture_prefix


def learn_reference_maps(reference_old_dir: Path | None, reference_new_dir: Path | None) -> dict[str, Any]:
    learned = {
        "association_by_region": {},
        "sort_by_id": {},
        "body_by_id": {},
        "cook_by_item": {},
        "cook_by_recipe": {},
    }
    if not reference_old_dir or not reference_new_dir:
        return learned
    if not reference_old_dir.exists() or not reference_new_dir.exists():
        return learned

    for old_path in sorted(reference_old_dir.glob("*.json")):
        new_path = reference_new_dir / old_path.name
        if not new_path.exists():
            continue
        old_data = load_json(old_path)
        new_data = load_json(new_path)

        region = old_data.get("chara_info", {}).get("region")
        association = new_data.get("FetterInfo", {}).get("Association")
        if region and isinstance(association, int):
            learned["association_by_region"][region] = association

        char_id = new_data.get("Id")
        if isinstance(char_id, int):
            if isinstance(new_data.get("Sort"), int):
                learned["sort_by_id"][char_id] = new_data["Sort"]
            if isinstance(new_data.get("Body"), int):
                learned["body_by_id"][char_id] = new_data["Body"]

        special_food = old_data.get("chara_info", {}).get("special_food", {})
        cook_bonus = new_data.get("FetterInfo", {}).get("CookBonus")
        if isinstance(cook_bonus, dict):
            if isinstance(special_food.get("id"), int):
                learned["cook_by_item"][special_food["id"]] = deepcopy(cook_bonus)
            if isinstance(special_food.get("recipe"), int):
                learned["cook_by_recipe"][special_food["recipe"]] = deepcopy(cook_bonus)

    return learned


def resolve_association(region: str, learned: dict[str, Any], warnings: list[str]) -> int:
    if region in learned["association_by_region"]:
        return learned["association_by_region"][region]
    if region in DEFAULT_ASSOCIATION_MAP:
        return DEFAULT_ASSOCIATION_MAP[region]
    warnings.append(f"未找到地区 `{region}` 的 Association 映射，已回退为 0。")
    return 0


def resolve_sort(character_id: int, promote: int, learned: dict[str, Any], explicit_sort: int | None) -> int:
    if explicit_sort is not None:
        return explicit_sort
    if character_id in learned["sort_by_id"]:
        return learned["sort_by_id"][character_id]
    return promote


def resolve_body(character_id: int, learned: dict[str, Any], explicit_body: int | None) -> int:
    if explicit_body is not None:
        return explicit_body
    if character_id in learned["body_by_id"]:
        return learned["body_by_id"][character_id]
    return 3


def build_base_value(old_data: dict[str, Any]) -> dict[str, Any]:
    return normalize_value(
        {
            "HpBase": old_data["base_hp"],
            "AttackBase": old_data["base_atk"],
            "DefenseBase": old_data["base_def"],
        }
    )



def build_grow_curves(old_data: dict[str, Any]) -> list[dict[str, int]]:
    curves = []
    for item in old_data.get("stats_modifier", {}).get("prop_grow_curves", []):
        prop_type = item.get("type")
        curve_name = item.get("grow_curve")
        if prop_type not in PROP_TYPE_MAP:
            raise ConversionError(f"未识别的属性类型: {prop_type}")
        curves.append(
            {
                "Type": PROP_TYPE_MAP[prop_type],
                "Value": grow_curve_value(curve_name),
            }
        )
    return curves


def build_skill(old_skill: dict[str, Any], group_id: int) -> dict[str, Any]:
    promote = old_skill.get("promote", {})
    level_keys = sorted(promote, key=lambda x: int(x))
    if not level_keys:
        raise ConversionError(f"技能 `{old_skill.get('name', '')}` 缺少 promote 数据")

    first_level = promote[level_keys[0]]
    descriptions = trim_trailing_empty(first_level.get("desc", []))
    used_param_count = max_param_index(descriptions)

    proud_parameters = []
    for key in level_keys:
        level_data = promote[key]
        parameters = list(level_data.get("param", []))
        parameters = parameters[:used_param_count] if used_param_count else trim_trailing_zeros(parameters)
        proud_parameters.append(
            normalize_value(
                {
                    "Id": group_id * 100 + int(level_data["level"]),
                    "Level": int(level_data["level"]),
                    "Parameters": parameters,
                }
            )

        )

    return {
        "GroupId": group_id,
        "Proud": {
            "Descriptions": descriptions,
            "Parameters": proud_parameters,
        },
        "Id": old_skill["id"],
        "Name": old_skill["name"],
        "Description": old_skill["desc"],
        "Icon": first_level.get("icon", ""),
    }


def build_inherent(old_passive: dict[str, Any]) -> dict[str, Any]:
    params = trim_trailing_zeros(old_passive.get("param_list", []))
    proud: dict[str, Any] = {
        "Descriptions": [],
        "Parameters": [
            normalize_value(
                {
                    "Id": old_passive["id"],
                    "Level": 1,
                    "Parameters": params,
                }
            )

        ],
    }
    if old_passive.get("unlock", 0):
        proud["Display"] = 1

    return {
        "GroupId": old_passive["id"] // 100,
        "Proud": proud,
        "Id": old_passive["id"],
        "Name": old_passive["name"],
        "Description": old_passive["desc"],
        "Icon": old_passive.get("icon", ""),
    }


def build_talent(old_constellation: dict[str, Any], index: int) -> dict[str, Any]:
    result = {
        "Id": old_constellation["id"],
        "Name": old_constellation["name"],
        "Description": old_constellation["desc"],
        "Icon": old_constellation.get("icon", ""),
    }
    if index in EXTRA_LEVEL_MAP:
        result["ExtraLevel"] = deepcopy(EXTRA_LEVEL_MAP[index])
    return result


def build_namecard(old_namecard: dict[str, Any]) -> dict[str, Any] | None:
    if not old_namecard:
        return None
    icon_name, picture_prefix = picture_prefix_from_namecard_icon(old_namecard.get("icon", ""))
    return {
        "Name": old_namecard.get("name", ""),
        "Description": old_namecard.get("desc", ""),
        "Icon": icon_name,
        "PicturePrefix": picture_prefix,
    }


def build_costumes(old_costumes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(old_costumes or []):
        result.append(
            {
                "Id": item.get("id"),
                "Name": item.get("name", ""),
                "Description": item.get("desc", ""),
                "IsDefault": index == 0,
            }
        )
    return result


def build_cultivation_items(materials: dict[str, Any]) -> list[int]:
    result: list[int] = []

    ascensions = materials.get("ascensions", [])
    if ascensions:
        for mat in ascensions[-1].get("mats", []):
            item_id = mat.get("id")
            if isinstance(item_id, int) and item_id not in result:
                result.append(item_id)

    talents = materials.get("talents", [])
    if talents and talents[0]:
        for mat in talents[0][-1].get("mats", []):
            item_id = mat.get("id")
            if not isinstance(item_id, int):
                continue
            if item_id == 104319:
                continue
            if item_id not in result:
                result.append(item_id)

    return result


def build_cook_bonus(old_food: dict[str, Any], learned: dict[str, Any], warnings: list[str]) -> dict[str, Any] | None:
    if not old_food:
        return None

    if old_food.get("id") in learned["cook_by_item"]:
        return deepcopy(learned["cook_by_item"][old_food["id"]])
    if old_food.get("recipe") in learned["cook_by_recipe"]:
        return deepcopy(learned["cook_by_recipe"][old_food["recipe"]])

    warnings.append(
        f"特殊料理 `{old_food.get('name', '')}` 缺少 CookBonus 参考数据，已输出空的 OriginItemId / InputList。请在生成的文件中以正确的值覆盖'OriginItemId': 114514"
    )
    return {
        "OriginItemId": 114514,
        "ItemId": old_food.get("id"),
        "InputList": [],
    }


def build_fetter_info(
    old_root: dict[str, Any],
    learned: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    info = old_root.get("chara_info", {})
    before_special = info.get("vision_special_type_before", "")
    after_special = info.get("vision_special_type_after", "")
    vision = info.get("vision", "")
    constellation = info.get("constellation", "")

    result: dict[str, Any] = {
        "Title": info.get("title", ""),
        "Detail": info.get("detail", ""),
        "Association": resolve_association(info.get("region", ""), learned, warnings),
        "Native": info.get("native", ""),
        "BirthMonth": (info.get("birth") or [0, 0])[0],
        "BirthDay": (info.get("birth") or [0, 0])[1],
        "VisionBefore": vision,
        "ConstellationBefore": constellation,
        "CvChinese": info.get("va", {}).get("chinese", ""),
        "CvJapanese": info.get("va", {}).get("japanese", ""),
        "CvEnglish": info.get("va", {}).get("english", ""),
        "CvKorean": info.get("va", {}).get("korean", ""),
    }

    cook_bonus = build_cook_bonus(info.get("special_food", {}), learned, warnings)
    if cook_bonus is not None:
        result["CookBonus"] = cook_bonus

    if before_special:
        result["VisionOverrideLocked"] = before_special
    if after_special:
        result["VisionAfter"] = vision
        result["VisionOverrideUnlocked"] = after_special
    elif before_special:
        result["VisionOverrideUnlocked"] = before_special
    else:
        result["VisionAfter"] = vision
        result["VisionOverrideUnlocked"] = "神之眼"

    if not before_special and not after_special:
        result["ConstellationAfter"] = constellation

    result["Fetters"] = [
        {"Title": item.get("title", ""), "Context": item.get("text", "")}
        for item in info.get("quotes", [])
    ]
    result["FetterStories"] = [
        {"Title": item.get("title", ""), "Context": item.get("text", "")}
        for item in info.get("stories", [])
    ]
    return result


def convert_character(
    input_path: Path,
    old_root: dict[str, Any],
    learned: dict[str, Any],
    explicit_sort: int | None,
    explicit_body: int | None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    char_id = file_id(input_path)
    promote = promote_id(char_id)

    active_skills = old_root.get("skills", [])
    if len(active_skills) < 3:
        raise ConversionError(f"角色 `{input_path.name}` 的主动技能数量不足 3 个")

    skill_depot = {
        "Arkhe": 0,
        "Skills": [
            build_skill(active_skills[0], promote * 100 + SKILL_SUFFIXES[0]),
            build_skill(active_skills[1], promote * 100 + SKILL_SUFFIXES[1]),
        ],
        "EnergySkill": build_skill(active_skills[2], promote * 100 + SKILL_SUFFIXES[2]),
        "Inherents": [build_inherent(item) for item in old_root.get("passives", [])],
        "Talents": [build_talent(item, index) for index, item in enumerate(old_root.get("constellations", []))],
    }

    result: dict[str, Any] = {
        "Id": char_id,
        "PromoteId": promote,
        "Sort": resolve_sort(char_id, promote, learned, explicit_sort),
        "Body": resolve_body(char_id, learned, explicit_body),
        "Icon": old_root.get("icon", ""),
        "SideIcon": icon_to_side_icon(old_root.get("icon", "")),
        "Name": old_root.get("name", ""),
        "Description": old_root.get("desc", ""),
        "BeginTime": to_begin_time(old_root.get("chara_info", {}).get("release_date", "")),
        "Quality": QUALITY_MAP.get(old_root.get("rarity", ""), 0),
        "Weapon": WEAPON_MAP.get(old_root.get("weapon", ""), 0),
        "BaseValue": build_base_value(old_root),
        "GrowCurves": build_grow_curves(old_root),
        "SkillDepot": skill_depot,
        "FetterInfo": build_fetter_info(old_root, learned, warnings),
        "Costumes": build_costumes(old_root.get("chara_info", {}).get("costume", [])),
        "CultivationItems": build_cultivation_items(old_root.get("materials", {})),
    }

    namecard = build_namecard(old_root.get("chara_info", {}).get("namecard", {}))
    if namecard is not None:
        result["NameCard"] = namecard

    return normalize_value(result), warnings



def iter_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(path for path in input_path.glob("*.json") if path.is_file())
    raise ConversionError(f"输入路径不存在: {input_path}")


def output_path_for(input_path: Path, input_root: Path, output_path: Path) -> Path:
    if output_path.suffix.lower() == ".json":
        return output_path
    relative = input_path.name if input_root.is_file() else input_path.relative_to(input_root)
    return output_path / relative


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将旧版角色 JSON 转换为新版结构。")
    parser.add_argument("input", help="输入 JSON 文件或目录")
    parser.add_argument("-o", "--output", required=True, help="输出 JSON 文件或目录")
    parser.add_argument("--reference-old", help="旧版参考目录，例如 old")
    parser.add_argument("--reference-new", help="新版参考目录，例如 new")
    parser.add_argument("--sort", type=int, help="手动指定 Sort")
    parser.add_argument("--body", type=int, help="手动指定 Body")
    return parser.parse_args()


def convert_game_data(input_path, output_path):
    reference_old = None
    reference_new = None

    try:
        learned = learn_reference_maps(reference_old, reference_new)
        files = iter_input_files(input_path)
        if not files:
            raise ConversionError("没有找到可转换的 JSON 文件")

        for file_path in files:
            old_root = load_json(file_path)
            converted, warnings = convert_character(file_path, old_root, learned, None, None)
            target = output_path_for(file_path, input_path, output_path)
            dump_json(target, converted)
            print(f"已转换: {file_path} -> {target}")
            for warning in warnings:
                print(f"警告: {warning}", file=sys.stderr)
        return 0
    except ConversionError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

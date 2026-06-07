#!/usr/bin/env python
"""
BOSS直聘岗位搜索脚本（CLI入口）
使用方式：
  python scripts/boss_search.py --cities 杭州,深圳 --roles 数据分析 --output data/results.json
"""
import argparse
import json
import sys
import os

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.config import UserProfile, SearchConfig
from agent.models import JobPosition, SearchResult
from agent.exporter import ExcelExporter


def main():
    parser = argparse.ArgumentParser(description="BOSS直聘岗位搜索Agent")
    parser.add_argument("--cities", default="杭州,深圳", help="目标城市，逗号分隔")
    parser.add_argument("--roles", default="数据分析,策略运营,增长,AI-Agent应用", help="目标岗位方向")
    parser.add_argument("--output", default="data/search_results.json", help="输出JSON路径")
    parser.add_argument("--excel", default=None, help="同时导出Excel路径（可选）")
    args = parser.parse_args()

    profile = UserProfile()
    config = SearchConfig()

    # 覆盖配置
    profile.target_cities = [c.strip() for c in args.cities.split(",")]
    profile.target_roles = [r.strip() for r in args.roles.split(",")]

    print(f"=== BOSS直聘求职Agent ===")
    print(f"用户：{profile.name} | {profile.degree} | {profile.graduation_year}")
    print(f"目标城市：{', '.join(profile.target_cities)}")
    print(f"目标方向：{', '.join(profile.target_roles)}")
    print(f"期望薪资：{profile.salary_min}-{profile.salary_max}元/天")
    print()

    # 构造搜索提示（供AI Agent使用）
    search_prompt = _build_search_prompt(profile, config)
    print("=== 搜索提示词（供AI Agent使用） ===")
    print(search_prompt)
    print()

    # 保存配置和提示词到JSON
    output_data = {
        "user_profile": {
            "name": profile.name,
            "degree": profile.degree,
            "graduation_year": profile.graduation_year,
            "target_cities": profile.target_cities,
            "target_roles": profile.target_roles,
            "salary_range": f"{profile.salary_min}-{profile.salary_max}元/天",
            "skills": profile.skills,
        },
        "search_config": {
            "platforms": config.platforms,
            "keywords": config.keywords,
            "target_companies": config.target_companies,
        },
        "search_prompt": search_prompt,
        "note": "此JSON供AI Agent执行实际搜索时参考。实际岗位结果需由Agent搜索后填充到results字段。",
        "results": [],
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"配置已保存到: {args.output}")
    print(f"\n下一步：将此文件交给AI Agent，Agent将执行实际搜索并填充results字段。")
    print(f"然后运行: python scripts/generate_excel.py {args.output} --output data/杭州2027届实习生岗位汇总表.xlsx")


def _build_search_prompt(profile: UserProfile, config: SearchConfig) -> str:
    """构造搜索提示词"""
    cities_str = "、".join(profile.target_cities)
    roles_str = "、".join(profile.target_roles)
    companies_str = "、".join(config.target_companies[:8])

    return f"""请在以下平台搜索2027届数据分析实习岗位：

【搜索平台】BOSS直聘(zhipin.com)、牛客网(nowcoder.com)、实习僧(shixiseng.com)

【搜索条件】
- 岗位方向：{roles_str}
- 工作地点：{cities_str}
- 毕业时间：2027届（2026年9月-2027年8月毕业）
- 薪资范围：200-400元/天
- 行业偏好：互联网、金融科技、AI

【优先搜索公司】{companies_str}等

【输出要求】
对每个找到的岗位，提取以下信息：
- 公司名称、岗位名称、岗位方向、行业、工作地点
- 实习薪资（如未标注写"面议"）
- 岗位职责概述、任职要求概述
- 投递链接或来源平台
- 是否有转正机会/是否可留用

请按"有转正机会 > 可留用 > 普通实习"排序，同条件按薪资降序。

输出为JSON数组格式，保存到results字段。"""


if __name__ == "__main__":
    main()

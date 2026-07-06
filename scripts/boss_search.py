#!/usr/bin/env python
"""
BOSS直聘岗位搜索脚本（CLI入口）
实际抓取岗位 + 生成提示词 fallback

使用方式：
  # 实际抓取（需要 BOSS_COOKIE 等环境变量）
  python scripts/boss_search.py --cities 杭州,深圳 --roles 数据分析 --output data/results.json

  # 仅生成提示词（不抓取，留给外部 AI Agent 执行）
  python scripts/boss_search.py --prompt-only --output data/search_prompt.json
"""
import argparse
import json
import sys
import os
import logging

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.config import UserProfile, SearchConfig
from agent.models import JobPosition, SearchResult
from agent.exporter import ExcelExporter

logger = logging.getLogger("boss_search")


def main():
    parser = argparse.ArgumentParser(description="BOSS直聘岗位搜索Agent")
    parser.add_argument("--cities", default="杭州,深圳", help="目标城市，逗号分隔")
    parser.add_argument("--roles", default="数据分析,策略运营,增长,AI-Agent应用", help="目标岗位方向")
    parser.add_argument("--output", default="data/search_results.json", help="输出JSON路径")
    parser.add_argument("--excel", default=None, help="同时导出Excel路径（可选）")
    parser.add_argument("--prompt-only", action="store_true", help="仅生成提示词，不实际抓取")
    parser.add_argument("--platforms", default="BOSS直聘,牛客网,实习僧", help="抓取平台，逗号分隔")
    parser.add_argument("--max-per-keyword", type=int, default=30, help="每个关键词最多抓取岗位数")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 加载 .env（如果存在）
    _load_dotenv()

    profile = UserProfile()
    config = SearchConfig()

    # 覆盖配置
    profile.target_cities = [c.strip() for c in args.cities.split(",")]
    profile.target_roles = [r.strip() for r in args.roles.split(",")]
    platforms = [p.strip() for p in args.platforms.split(",")]

    print("=== BOSS直聘求职Agent ===")
    print(f"用户：{profile.name} | {profile.degree} | {profile.graduation_year}")
    print(f"目标城市：{', '.join(profile.target_cities)}")
    print(f"目标方向：{', '.join(profile.target_roles)}")
    print(f"期望薪资：{profile.salary_min}-{profile.salary_max}元/天")
    print(f"抓取平台：{', '.join(platforms)}")
    print()

    # ---------- 模式 1：仅生成提示词 ----------
    if args.prompt_only:
        search_prompt = _build_search_prompt(profile, config)
        print("=== 搜索提示词（供AI Agent使用） ===")
        print(search_prompt)
        print()

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
            "note": "此JSON供AI Agent执行实际搜索时参考。",
            "results": [],
        }

        _write_json(args.output, output_data)
        print(f"配置已保存到: {args.output}")
        return

    # ---------- 模式 2：实际抓取 ----------
    from agent.fetcher import FetcherPipeline

    # 把 target_roles 转成搜索关键词
    keywords = [f"{role}实习生" for role in profile.target_roles]
    # 加上配置里的关键词
    keywords.extend(config.keywords)

    pipeline = FetcherPipeline(
        platforms=platforms,
        max_per_keyword=args.max_per_keyword,
    )

    print(f"开始抓取，关键词：{keywords}")
    print(f"城市：{profile.target_cities}")
    print()

    positions = pipeline.fetch(keywords=keywords, cities=profile.target_cities)

    if not positions:
        print("\n⚠ 未抓取到任何岗位。可能原因：")
        print("  1. BOSS_COOKIE 未配置或已过期（从浏览器 F12 复制）")
        print("  2. 触发平台风控，稍后重试")
        print("  3. 网络问题")
        print("\n可改用 --prompt-only 模式生成提示词，交给外部 AI Agent 执行搜索。")
        return

    # 过滤薪资下限
    filtered = _filter_by_salary(positions, profile.salary_min)
    if len(filtered) < len(positions):
        logger.info(f"薪资过滤：{len(positions)} → {len(filtered)}（最低 {profile.salary_min}元/天）")

    # 匹配度评分（写入 skill_match_score 和 match_notes）
    try:
        from agent.matcher import JobMatcher
        matcher = JobMatcher()
        matcher.score_batch(filtered)
        logger.info("匹配度评分完成")
    except Exception as e:
        logger.warning(f"匹配度评分失败（不影响主流程）: {e}")

    result = SearchResult(positions=filtered, total_found=len(filtered))
    result.sort_by_priority()

    print()
    print(result.summary())
    print()

    # 保存 JSON
    output_data = {
        "user_profile": {
            "name": profile.name,
            "target_cities": profile.target_cities,
            "target_roles": profile.target_roles,
            "salary_range": f"{profile.salary_min}-{profile.salary_max}元/天",
        },
        "search_time": result.search_time,
        "total": len(result.positions),
        "results": [p.to_dict() for p in result.positions],
    }
    _write_json(args.output, output_data)
    print(f"JSON 已保存: {args.output}（{len(result.positions)} 个岗位）")

    # 导出 Excel
    excel_path = args.excel
    if excel_path is None:
        city_tag = "+".join(profile.target_cities)
        excel_path = f"data/{city_tag}2027届实习生岗位汇总表.xlsx"

    exporter = ExcelExporter(result)
    exporter.export(excel_path)
    print(f"Excel 已生成: {excel_path}")


def _filter_by_salary(positions: list, salary_min: int) -> list:
    """过滤薪资低于下限的岗位（面议保留）"""
    import re
    filtered = []
    for p in positions:
        if "面议" in p.salary or not p.salary:
            filtered.append(p)
            continue
        # 提取薪资数字，如 "200-300元/天" → 200
        match = re.search(r"(\d+)", p.salary)
        if match:
            low = int(match.group(1))
            if low >= salary_min:
                filtered.append(p)
    return filtered


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_dotenv():
    """简易 .env 加载（避免 python-dotenv 依赖）"""
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".env",
    )
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def _build_search_prompt(profile: UserProfile, config: SearchConfig) -> str:
    """构造搜索提示词（prompt-only 模式使用）"""
    cities_str = "、".join(profile.target_cities)
    roles_str = "、".join(profile.target_roles)
    companies_str = "、".join(config.target_companies[:8])

    return f"""请在以下平台搜索2027届数据分析实习岗位：

【搜索平台】BOSS直聘(zhipin.com)、牛客网(nowcoder.com)、实习僧(shixiseng.com)

【搜索条件】
- 岗位方向：{roles_str}
- 工作地点：{cities_str}
- 毕业时间：2027届（2026年9月-2027年8月毕业）
- 薪资范围：{profile.salary_min}-{profile.salary_max}元/天
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

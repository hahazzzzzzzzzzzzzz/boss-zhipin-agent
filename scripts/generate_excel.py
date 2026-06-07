#!/usr/bin/env python
"""
Excel生成脚本
使用方式：
  python scripts/generate_excel.py data/search_results.json --output data/岗位汇总表.xlsx
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.exporter import export_from_json


def main():
    parser = argparse.ArgumentParser(description="生成结构化岗位汇总Excel")
    parser.add_argument("input", help="输入的JSON文件路径（包含results数组）")
    parser.add_argument("--output", "-o", default=None, help="输出Excel路径")
    parser.add_argument("--city", default=None, help="指定城市筛选（可选：杭州/深圳）")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误：文件不存在 - {args.input}")
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 兼容两种格式：results直接在顶层，或在data.results
    if isinstance(data, list):
        results = data
        total_in_file = len(data)
    elif isinstance(data, dict) and "results" in data:
        results = data["results"]
        total_in_file = len(data["results"])
    else:
        print(f"错误：JSON中未找到results数组")
        sys.exit(1)

    # 城市筛选
    if args.city:
        results = [r for r in results if r.get("工作地点", "") == args.city]
        print(f"筛选城市：{args.city}，剩余 {len(results)} 个岗位")

    if not results:
        print("没有找到任何岗位数据")
        sys.exit(0)

    # 默认输出路径
    if args.output is None:
        city_tag = args.city or "全部"
        args.output = f"data/{city_tag}2027届实习生岗位汇总表.xlsx"

    # 如果筛选后的结果和原始结果数量一致，直接导出；否则用过滤导出
    if len(results) == total_in_file:
        output_path = export_from_json(args.input, args.output)
    else:
        output_path = _export_filtered(results, args.output)

    print(f"Excel已生成: {output_path}")
    print(f"共 {len(results)} 个岗位")

    # 统计
    cities = {}
    conversions = 0
    for r in results:
        city = r.get("工作地点", "未知")
        cities[city] = cities.get(city, 0) + 1
        if r.get("有转正机会"):
            conversions += 1

    print(f"城市分布：{cities}")
    print(f"有转正机会：{conversions} 个")


def _export_filtered(results: list, output_path: str) -> str:
    """导出筛选后的结果"""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(results, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    result = export_from_json(tmp.name, output_path)
    os.unlink(tmp.name)
    return result


if __name__ == "__main__":
    main()

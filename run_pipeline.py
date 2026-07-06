"""
端到端流水线 v3：用户只需 LLM_API_KEY + 简历文件路径

使用方式：
  python run_pipeline.py --resume path/to/resume.pdf
  python run_pipeline.py --resume path/to/resume.md --cities 杭州,深圳
  python run_pipeline.py --resume path/to/resume.pdf --no-llm-resume  # 简历用简单解析（不调 LLM）
"""
import os, sys, json, logging, time, argparse

# 加载 .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.fetcher import FetcherPipeline
from agent.matcher import JobMatcher
from agent.greeting import GreetingGenerator
from agent.models import SearchResult
from agent.exporter import ExcelExporter
from agent.reporter import generate_markdown_report
from agent.resume import ResumeParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def main():
    parser = argparse.ArgumentParser(description="BOSS-Agent 端到端流水线 v3")
    parser.add_argument("--resume", required=True, help="简历文件路径（PDF/Markdown/纯文本）")
    parser.add_argument("--cities", default="杭州,深圳,北京", help="目标城市，逗号分隔")
    parser.add_argument("--keywords", default="数据分析,数据运营,策略运营",
                        help="搜索关键词，逗号分隔")
    parser.add_argument("--no-llm-resume", action="store_true",
                        help="简历用简单解析（不调 LLM，速度快但精度低）")
    parser.add_argument("--no-detail", action="store_true",
                        help="不抓详情页 JD（速度快但匹配度评分不准）")
    parser.add_argument("--top-n", type=int, default=10, help="为前 N 个岗位生成招呼语")
    parser.add_argument("--max-per-keyword", type=int, default=15, help="每个关键词最多抓取岗位数")
    parser.add_argument("--platform", default="实习僧",
                        choices=["实习僧", "BOSS直聘", "BOSS直聘-Playwright"],
                        help="抓取平台（默认实习僧；BOSS直聘-Playwright 需安装 playwright）")
    parser.add_argument("--no-cache", action="store_true",
                        help="禁用抓取缓存，强制重新抓取")
    args = parser.parse_args()

    print("=" * 60)
    print("  BOSS-Agent 端到端流水线 v3")
    print("  简历解析 → 实习僧抓取 → 评分 → LLM 招呼语 → Markdown 报告")
    print("=" * 60)
    print()

    # ---------- 0. 检查 LLM API ----------
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        print("⚠ LLM_API_KEY 未配置，招呼语将用规则模式生成（质量较低）")
        print("  在 .env 中配置: LLM_API_KEY=...")
        print()
    else:
        print(f"✓ LLM API 已配置: {os.environ.get('LLM_MODEL', 'qwen-plus')}")
    print()

    # ---------- 1. 解析简历 ----------
    print(f"【步骤 1/5】解析简历: {args.resume}")
    t0 = time.time()
    rp = ResumeParser()
    if args.no_llm_resume:
        print("  使用简单解析（正则）...")
        resume = rp.parse(args.resume)
    else:
        print("  使用 LLM 解析（更准确）...")
        resume = rp.parse_with_llm(args.resume)
    parse_time = time.time() - t0
    print(f"✓ 简历解析完成（{parse_time:.1f}s）")
    print(f"  姓名: {resume.get('name', '—')}")
    print(f"  简介: {resume.get('basics', '—')}")
    print(f"  技能: {len(resume.get('skills', []))} 个 - {', '.join(resume.get('skills', [])[:8])}")
    print(f"  项目: {len(resume.get('projects', []))} 个")
    print()

    # ---------- 2. 抓取岗位 ----------
    print(f"【步骤 2/5】{args.platform} 抓取岗位...")
    t0 = time.time()

    from agent.fetcher import ShixisengFetcher, BOSSPlaywrightFetcher, BOSSFetcher

    cache_dir = None if args.no_cache else "data/.fetch_cache"

    if args.platform == "实习僧":
        fetcher = ShixisengFetcher(
            max_per_keyword=args.max_per_keyword,
            fetch_detail=not args.no_detail,
            detail_limit=args.top_n,
            cache_dir=cache_dir,
        )
    elif args.platform == "BOSS直聘-Playwright":
        fetcher = BOSSPlaywrightFetcher(
            max_per_keyword=args.max_per_keyword,
            cache_dir=cache_dir,
        )
    else:  # BOSS直聘（wapi）
        fetcher = BOSSFetcher(
            max_per_keyword=args.max_per_keyword,
            cache_dir=cache_dir,
        )

    positions = []
    seen_keys = set()
    cities = [c.strip() for c in args.cities.split(",")]
    keywords = [k.strip() for k in args.keywords.split(",")]
    for kw in keywords:
        for city in cities:
            try:
                pos_list = fetcher.fetch(kw, city)
                for p in pos_list:
                    key = (p.company, p.title, p.city)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        positions.append(p)
            except Exception as e:
                logger.error(f"抓取异常 [{kw}/{city}]: {e}")

    # Playwright 抓取器需要关闭
    if hasattr(fetcher, "close"):
        fetcher.close()

    fetch_time = time.time() - t0
    print(f"✓ 抓取 {len(positions)} 个岗位（{fetch_time:.1f}s）\n")

    if not positions:
        print("⚠ 未抓到岗位，流程终止")
        return

    # ---------- 3. 匹配度评分 ----------
    print("【步骤 3/5】匹配度评分（基于用户简历）...")
    matcher = JobMatcher(resume=resume)
    matcher.score_batch(positions)
    positions.sort(key=lambda p: p.priority_score, reverse=True)
    high_match = sum(1 for p in positions if p.skill_match_score >= 0.5)
    print(f"✓ 高匹配度（≥50%）：{high_match} 个\n")

    # ---------- 4. 并发 LLM 招呼语 ----------
    print(f"【步骤 4/5】并发 LLM 招呼语（4 并发）...")
    t0 = time.time()
    gen = GreetingGenerator(
        mode="auto" if api_key else "rule",
        max_workers=4,
        cache_path="data/greetings_cache.json",
        resume=resume,
    )
    top_n = min(args.top_n, len(positions))
    greetings = gen.generate_batch(positions[:top_n])
    llm_time = time.time() - t0
    print(f"✓ 生成 {len(greetings)} 条招呼语（{llm_time:.1f}s）\n")

    # ---------- 5. 导出 ----------
    print("【步骤 5/5】导出 Excel + JSON + Markdown 报告...")
    result = SearchResult(positions=positions, total_found=len(positions))

    excel_path = "data/pipeline_results.xlsx"
    ExcelExporter(result).export(excel_path)

    json_path = "data/pipeline_results.json"
    output = {
        "search_time": result.search_time,
        "resume_name": resume.get("name"),
        "total": len(positions),
        "high_match_count": high_match,
        "model": os.environ.get("LLM_MODEL"),
        "fetch_time_sec": round(fetch_time, 1),
        "llm_time_sec": round(llm_time, 1),
        "positions": [
            {
                "公司": p.company,
                "岗位": p.title,
                "城市": p.city,
                "薪资": p.salary,
                "方向": p.direction,
                "行业": p.industry,
                "匹配度": f"{p.skill_match_score:.0%}",
                "匹配说明": p.match_notes,
                "转正": "有" if p.has_conversion else "无",
                "来源": p.source,
                "链接": p.apply_link,
                "招呼语": greetings.get(f"{p.company}-{p.title}", ""),
            }
            for p in positions
        ],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    md_path = "data/招呼语报告.md"
    generate_markdown_report(
        positions=positions,
        greetings=greetings,
        output_path=md_path,
        top_n=top_n,
    )
    print(f"✓ Excel: {excel_path}")
    print(f"✓ JSON:  {json_path}")
    print(f"✓ Markdown: {md_path}\n")

    # ---------- 展示 Top 5 ----------
    print("=" * 60)
    print(f"  Top 5 岗位 + 招呼语")
    print(f"  简历: {resume.get('name')} | 抓取 {fetch_time:.1f}s + LLM {llm_time:.1f}s")
    print("=" * 60)
    for i, p in enumerate(positions[:5], 1):
        greeting = greetings.get(f"{p.company}-{p.title}", "")
        print(f"\n{i}. [{p.skill_match_score:.0%}] {p.company} - {p.title} ({p.city}, {p.salary})")
        print(f"   匹配: {p.match_notes}")
        print(f"   招呼语({len(greeting)}字): {greeting}")


if __name__ == "__main__":
    main()

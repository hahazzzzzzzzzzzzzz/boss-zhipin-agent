"""
招呼语生成器 — 基于岗位 + 用户简历生成个性化招呼语

设计要点：
- 双模式：LLM 调用（更自然）+ 本地规则兜底（无 LLM/调用失败时可用）
- 简历摘要内置，避免每次解析 PDF
- 按岗位方向（数据分析/策略运营/AI-Agent/风控）匹配不同卖点
- 长度 80-120 字，符合 BOSS 直聘首轮招呼语习惯

使用方式：
    from agent.greeting import GreetingGenerator
    gen = GreetingGenerator()
    text = gen.generate(job_position)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from .models import JobPosition

logger = logging.getLogger(__name__)


# ---------- 用户简历摘要（示例占位，实际使用时通过 ResumeParser 从上传的简历解析）----------
# 注意：此处仅作示例，运行时优先使用 --resume 参数传入的真实简历
# 或通过 GreetingGenerator(resume=...) 注入，避免硬编码真实个人信息

RESUME_SUMMARY = {
    "name": "求职者示例",
    "basics": "应用统计硕士在读（示例大学），GPA 4.0/90，2027 届，可随时到岗、每周实习 5 天",
    "skills": [
        "Python", "Pandas", "Scikit-learn", "SQL", "Excel",
        "LightGBM", "XGBoost", "SHAP", "LIME", "χ²检验",
        "Mann-Whitney U", "Kruskal-Wallis", "时间序列", "迁移学习",
    ],
    "projects": [
        {
            "name": "电商平台用户行为与转化分析（示例项目）",
            "highlights": [
                "构建 LightGBM 购买预测模型 AUC=0.95",
                "χ²检验定位移动端转化瓶颈，输出运营建议推动 GMV 提升",
                "完成多维流量细分指标体系监控",
            ],
            "tags": ["数据分析", "用户行为", "LightGBM", "SHAP", "χ²"],
        },
        {
            "name": "消费信贷风控建模（示例项目）",
            "highlights": [
                "处理百万级贷款数据",
                "Kruskal-Wallis/Mann-Whitney U 识别 FICO、DTI 为违约关键因子",
                "LightGBM 违约预测 ROC-AUC=0.70",
                "差异化定价策略优化风险收益",
            ],
            "tags": ["风控", "信贷", "LightGBM", "假设检验", "SQL"],
        },
        {
            "name": "跨域数据分布对齐迁移学习框架（示例项目）",
            "highlights": [
                "TCA 域适应显著缩减域间分布距离",
                "贝叶斯优化 XGBoost 提升源域准确率",
                "SHAP+LIME 解释特征决策逻辑",
            ],
            "tags": ["迁移学习", "XGBoost", "SHAP", "AI"],
        },
    ],
    "competitions": "数学建模竞赛奖项（示例）",
    "languages": "CET-4/6，英语可作为工作语言",
}


# ---------- 招呼语生成器 ----------

class GreetingGenerator:
    """
    招呼语生成器

    mode:
        - "auto"（默认）：优先 LLM，失败回退规则
        - "llm"：仅 LLM
        - "rule"：仅规则
    """
    def __init__(self, mode: str = "auto", llm_provider: str = "codebuddy",
                 max_workers: int = 4, cache_path: str | None = None,
                 resume: Optional[dict] = None):
        """
        max_workers: LLM 并发数（默认 4，阿里云百炼支持并发）
        cache_path: 招呼语缓存文件路径，None 则不持久化（仅内存缓存）
        resume: 用户简历 dict（来自 ResumeParser），None 则用内置默认简历
        """
        self.mode = mode
        self.llm_provider = llm_provider
        self.max_workers = max_workers
        self._llm_client = None
        self._cache: dict[str, str] = {}
        self._cache_path = cache_path
        # 简历：优先外部传入，否则用内置默认
        self.resume = resume if resume else RESUME_SUMMARY
        if cache_path:
            self._load_cache()

    def _cache_key(self, job: JobPosition) -> str:
        return f"{job.company}|{job.title}|{job.direction}"

    def _load_cache(self):
        """从磁盘加载缓存"""
        import json as _json
        if self._cache_path and os.path.exists(self._cache_path):
            try:
                with open(self._cache_path, "r", encoding="utf-8") as f:
                    self._cache = _json.load(f)
                logger.info(f"加载招呼语缓存: {len(self._cache)} 条")
            except Exception as e:
                logger.warning(f"缓存加载失败: {e}")
                self._cache = {}

    def _save_cache(self):
        """保存缓存到磁盘"""
        import json as _json
        if self._cache_path and self._cache:
            try:
                os.makedirs(os.path.dirname(self._cache_path) or ".", exist_ok=True)
                with open(self._cache_path, "w", encoding="utf-8") as f:
                    _json.dump(self._cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"缓存保存失败: {e}")

    def generate(self, job: JobPosition) -> str:
        """生成单个岗位的招呼语（带缓存）"""
        key = self._cache_key(job)
        if key in self._cache:
            logger.debug(f"缓存命中: {key}")
            return self._cache[key]

        if self.mode in ("auto", "llm"):
            try:
                text = self._generate_via_llm(job)
            except Exception as e:
                logger.warning(f"LLM 生成失败，回退规则模式: {e}")
                if self.mode == "llm":
                    raise
                text = self._generate_via_rule(job)
        else:
            text = self._generate_via_rule(job)

        self._cache[key] = text
        self._save_cache()
        return text

    def generate_batch(self, jobs: list[JobPosition]) -> dict[str, str]:
        """
        批量生成（并发版）
        - LLM 模式：用 ThreadPoolExecutor 并发调用
        - 规则模式：直接串行（很快，无需并发）
        - 自动跳过缓存命中的岗位
        """
        # 先过滤掉缓存命中的
        todo: list[tuple[int, JobPosition]] = []
        results: dict[str, str] = {}
        for i, job in enumerate(jobs):
            key = self._cache_key(job)
            if key in self._cache:
                results[f"{job.company}-{job.title}"] = self._cache[key]
            else:
                todo.append((i, job))

        if not todo:
            logger.info(f"全部 {len(jobs)} 条命中缓存")
            return results

        logger.info(f"需生成 {len(todo)}/{len(jobs)} 条（{len(results)} 条缓存命中）")

        if self.mode == "rule":
            # 规则模式串行
            for i, job in todo:
                try:
                    text = self._generate_via_rule(job)
                    key = self._cache_key(job)
                    self._cache[key] = text
                    results[f"{job.company}-{job.title}"] = text
                except Exception as e:
                    logger.error(f"生成失败 [{job.company}/{job.title}]: {e}")
        else:
            # LLM/auto 模式并发
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {
                    pool.submit(self.generate, job): (i, job)
                    for i, job in todo
                }
                for fut in as_completed(futures):
                    i, job = futures[fut]
                    try:
                        text = fut.result()
                        results[f"{job.company}-{job.title}"] = text
                    except Exception as e:
                        logger.error(f"生成失败 [{job.company}/{job.title}]: {e}")
                        # 回退规则模式
                        try:
                            text = self._generate_via_rule(job)
                            results[f"{job.company}-{job.title}"] = text
                        except Exception:
                            pass

        self._save_cache()
        return results

    # ---------- LLM 模式 ----------

    def _generate_via_llm(self, job: JobPosition) -> str:
        client = self._get_llm_client()
        prompt = self._build_prompt(job)

        # 最多重试 2 次（共 3 次调用）
        for attempt in range(3):
            resp = client.chat.completions.create(
                model=self._get_model(),
                messages=[
                    {"role": "system", "content": "你是求职招呼语生成助手，严格控制字数在 80-120 字之间。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7 if attempt > 0 else 0.5,  # 重试时提高温度
                max_tokens=250,
            )
            text = resp.choices[0].message.content.strip()
            # 清理可能的引号、markdown
            text = text.strip("`\"'\n ")

            # 长度兜底：超过 130 字时智能截断到最后一个句号
            if len(text) > 130:
                for cut in range(120, 80, -5):
                    for punct in ["。", "！", "？"]:
                        idx = text.rfind(punct, 0, cut)
                        if idx > 0:
                            text = text[:idx + 1]
                            break
                    if len(text) <= 130:
                        break
                if len(text) > 130:
                    text = text[:120] + "。"

            # 长度过短（<70 字）时重试
            if len(text) < 70:
                logger.warning(f"LLM 招呼语过短 ({len(text)} 字)，第 {attempt+1} 次尝试重试")
                if attempt < 2:
                    continue
                # 重试仍短，回退规则模式
                logger.warning(f"LLM 多次重试仍过短，回退规则模式 [{job.company}/{job.title}]")
                return self._generate_via_rule(job)

            return text

        return self._generate_via_rule(job)

    def _get_llm_client(self):
        if self._llm_client is not None:
            return self._llm_client

        # 优先通用 LLM_* 变量，兼容旧版 CODEBUDDY_*
        api_key = (
            os.environ.get("LLM_API_KEY")
            or os.environ.get("CODEBUDDY_API_KEY", "")
        ).strip()
        if not api_key:
            raise RuntimeError("LLM_API_KEY / CODEBUDDY_API_KEY 未配置")

        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("需要安装 openai: pip install openai") from e

        base_url = (
            os.environ.get("LLM_BASE_URL")
            or os.environ.get("CODEBUDDY_BASE_URL")
            or "https://api.codebuddy.com/v1"
        )
        self._llm_client = OpenAI(api_key=api_key, base_url=base_url)
        return self._llm_client

    def _get_model(self) -> str:
        return (
            os.environ.get("LLM_MODEL")
            or os.environ.get("CODEBUDDY_MODEL")
            or "qwen-max"
        )

    # 招呼语开头模式池（避免雷同）
    OPENING_PATTERNS = [
        '看到贵司{title}岗位，方向很契合。',
        '{company}的{title}岗位我很感兴趣。',
        '关注{company}有一阵了，{title}岗位与我的背景很匹配。',
        '我对{title}岗位很感兴趣，希望进一步沟通。',
        '您好，{title}岗位的职责和我做过的项目高度吻合。',
        '{title}这个岗位的方向正是我想深入的，希望能聊聊。',
    ]

    def _build_prompt(self, job: JobPosition) -> str:
        """构造 LLM 提示词"""
        # 根据岗位方向挑匹配项目
        matched_projects = self._match_projects(job)
        # 只用 1 个最匹配的项目
        top_project = matched_projects[0] if matched_projects else self.resume["projects"][0]
        project_str = f"{top_project['name']}：{top_project['highlights'][0]}"

        # 随机选开头模式
        import random as _r
        opening = _r.choice(self.OPENING_PATTERNS).format(
            company=job.company, title=job.title
        )

        # 简历摘要
        basics = self.resume.get("basics", "求职者")
        skills = self.resume.get("skills", [])[:10]

        return f"""生成 BOSS 直聘打招呼消息。

【硬性要求】
1. **严格 80-120 字**（含标点），超过 120 字必须删减
2. 只突出 1 个最匹配的项目，**不要堆砌多个项目**
3. 自然口语化，不油腻、不套话、不列点
4. **必须用以下开头**："{opening}"
5. 结尾固定句："可随时到岗、每周 5 天，期待沟通。"
6. 不要用"您好"开头（开头已给定）

【岗位】{job.company} - {job.title}（{job.direction}）
【JD 摘要】{(job.responsibilities + job.requirements)[:200]}

【候选人】{basics}，{project_str}
【技能】{', '.join(skills)}

【字数控制示例】
"{opening}我是应用统计硕士，熟练Python/SQL/LightGBM，做过用户行为分析项目，用χ²检验定位转化瓶颈推动业务指标提升。可随时到岗、每周 5 天，期待沟通。"

直接输出招呼语，不要解释。"""

    def _match_projects(self, job: JobPosition) -> list[dict]:
        """根据岗位方向匹配简历项目"""
        text = f"{job.title} {job.responsibilities} {job.requirements}".lower()
        projects = self.resume.get("projects", [])
        if not projects:
            return []
        scored = []
        for p in projects:
            score = sum(1 for tag in p.get("tags", []) if tag.lower() in text)
            scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        # 如果都没匹配上，返回第一个项目作为通用
        result = [p for s, p in scored if s > 0]
        if not result:
            result = [projects[0]]
        return result

    # ---------- 规则模式（兜底） ----------

    def _generate_via_rule(self, job: JobPosition) -> str:
        """基于规则的招呼语生成（兜底，无 LLM 时用）"""
        matched = self._match_projects(job)
        projects = self.resume.get("projects", [])
        project = matched[0] if matched else (projects[0] if projects else {"name": "项目", "highlights": ["有相关经验"], "tags": []})
        highlight = project["highlights"][0] if project.get("highlights") else "有相关经验"
        # 提取项目里的关键技能
        proj_tags = [s for s in project.get("tags", []) if s.lower() not in ["数据分析", "风控", "信贷", "ai"]][:3]
        skills_str = "、".join(proj_tags) if proj_tags else "、".join(self.resume.get("skills", [])[:3]) or "Python、SQL"

        basics = self.resume.get("basics", "求职者")

        # 根据方向微调开头
        if "数据分析" in job.direction:
            opening = f"看到贵司{job.title}岗位，很感兴趣。"
        elif "策略运营" in job.direction or "增长" in job.direction:
            opening = f"对{job.company}的{job.title}岗位很感兴趣。"
        elif "AI" in job.direction:
            opening = f"关注{job.company}的{job.title}岗位，方向很契合。"
        else:
            opening = f"看到{job.company}招聘{job.title}，希望沟通。"

        body = (
            f"我是{basics}，熟练{skills_str}，"
            f"有{project.get('name', '项目')[:15]}项目经验，{highlight}。"
        )

        ending = "可随时到岗、每周 5 天，期待沟通。"

        text = opening + body + ending
        # 控制长度
        if len(text) > 130:
            text = opening + body[:60] + "。" + ending
        return text


# ---------- CLI 入口 ----------

def main():
    """命令行入口：从 JSON 读取岗位，批量生成招呼语"""
    import argparse
    parser = argparse.ArgumentParser(description="批量生成招呼语")
    parser.add_argument("input", help="岗位 JSON 路径（含 results 数组）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 路径")
    parser.add_argument("--mode", default="auto", choices=["auto", "llm", "rule"])
    parser.add_argument("--limit", type=int, default=20, help="最多生成条数")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("results", [])

    # 转成 JobPosition
    from .exporter import _dict_to_position  # 复用现有转换
    positions = [_dict_to_position(item) for item in items[:args.limit]]

    gen = GreetingGenerator(mode=args.mode)
    greetings = gen.generate_batch(positions)

    # 输出
    output_path = args.output or args.input.replace(".json", "_greetings.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(greetings, f, ensure_ascii=False, indent=2)

    print(f"生成 {len(greetings)} 条招呼语 → {output_path}")
    print()
    for key, text in list(greetings.items())[:3]:
        print(f"【{key}】")
        print(text)
        print(f"（{len(text)} 字）")
        print()


if __name__ == "__main__":
    main()

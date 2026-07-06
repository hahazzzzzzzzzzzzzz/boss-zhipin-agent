"""
岗位匹配度评分器 — 计算简历与 JD 的匹配度

设计要点：
- 多维评分：技能匹配(40%) + 项目匹配(30%) + 方向/学历匹配(20%) + 软技能(10%)
- 技能匹配用加权关键词（核心技能权重高，如 LightGBM/SQL/Python）
- 语义相似度用 TF-IDF + cosine（轻量，无需 sentence-transformers）
- 输出 0-1 分 + 匹配说明（命中哪些关键词），写入 JobPosition.skill_match_score 和 match_notes

使用方式：
    from agent.matcher import JobMatcher
    matcher = JobMatcher()
    score, notes = matcher.score(job_position)
    # 或批量
    matcher.score_batch(positions)
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .models import JobPosition
from .greeting import RESUME_SUMMARY

logger = logging.getLogger(__name__)


# ---------- 评分配置 ----------

# 技能关键词权重（核心技能权重高）
SKILL_WEIGHTS: dict[str, float] = {
    # 编程语言/工具（核心）
    "python": 3.0, "sql": 3.0, "pandas": 2.0, "numpy": 1.5,
    "scikit-learn": 2.0, "sklearn": 2.0, "excel": 1.5, "tableau": 1.5,
    "spark": 2.0, "hadoop": 1.5, "hive": 1.5,
    # 机器学习（核心）
    "lightgbm": 3.0, "xgboost": 3.0, "机器学习": 2.5, "深度学习": 2.0,
    "lstm": 1.5, "resnet": 1.5, "tensorflow": 1.5, "pytorch": 1.5,
    # 统计方法（核心，差异化优势）
    "假设检验": 2.5, "卡方检验": 2.5, "χ²": 2.5, "χ2": 2.5,
    "mann-whitney": 2.5, "kruskal-wallis": 2.5,
    "时间序列": 2.0, "sarima": 2.0, "回归分析": 2.0,
    "聚类": 1.5, "k-means": 1.5, "anova": 2.0,
    # 模型解释（差异化）
    "shap": 2.5, "lime": 2.0, "模型解释": 2.0,
    # 业务能力
    "用户行为分析": 2.5, "用户画像": 2.0, "指标体系": 2.0,
    "ab测试": 2.0, "a/b测试": 2.0, "实验设计": 2.0,
    "风控": 2.5, "信贷": 2.0, "违约预测": 2.0,
    "迁移学习": 2.0, "域适应": 1.5,
    # 通用
    "数据分析": 1.0, "数据挖掘": 1.5, "数据可视化": 1.5,
    "特征工程": 2.0, "特征选择": 1.5,
}

# 项目标签（用于项目匹配）
PROJECT_TAGS = {
    "用户行为分析": ["数据分析", "用户行为", "lightgbm", "shap", "χ²", "转化分析", "gmv"],
    "信贷风控": ["风控", "信贷", "lightgbm", "假设检验", "sql", "违约", "fico", "dti"],
    "迁移学习": ["迁移学习", "xgboost", "shap", "ai", "故障诊断", "域适应"],
}

# 软技能关键词
SOFT_SKILLS = ["沟通", "团队", "学习能力", "责任心", "主动", "逻辑", "业务理解"]


@dataclass
class ScoreBreakdown:
    """评分明细"""
    skill_score: float = 0.0          # 0-1
    project_score: float = 0.0        # 0-1
    direction_score: float = 0.0      # 0-1
    soft_skill_score: float = 0.0     # 0-1
    semantic_score: float = 0.0       # 0-1, TF-IDF 相似度
    total_score: float = 0.0          # 加权总分 0-1
    hit_skills: list[str] = field(default_factory=list)
    hit_projects: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        if not self.total_score:
            self.total_score = (
                self.skill_score * 0.35
                + self.project_score * 0.25
                + self.direction_score * 0.15
                + self.soft_skill_score * 0.05
                + self.semantic_score * 0.20
            )
            self.total_score = min(self.total_score, 1.0)


# ---------- 匹配器 ----------

class JobMatcher:
    """岗位匹配度评分器"""

    def __init__(self, resume: Optional[dict] = None):
        self.resume = resume or RESUME_SUMMARY
        # 预计算简历文本（用于 TF-IDF）
        self._resume_text = self._build_resume_text()

    def score(self, job: JobPosition) -> tuple[float, str]:
        """计算单个岗位匹配度，返回 (0-1 分数, 匹配说明)"""
        breakdown = self._score_detail(job)
        # 写入 job 对象
        job.skill_match_score = breakdown.total_score
        job.match_notes = breakdown.notes
        return breakdown.total_score, breakdown.notes

    def score_batch(self, jobs: list[JobPosition]) -> list[tuple[float, str]]:
        """批量评分"""
        return [self.score(job) for job in jobs]

    def _score_detail(self, job: JobPosition) -> ScoreBreakdown:
        """详细评分"""
        jd_text = f"{job.title} {job.responsibilities} {job.requirements}".lower()

        skill_score, hit_skills = self._score_skills(jd_text)
        project_score, hit_projects = self._score_projects(jd_text, job)
        direction_score = self._score_direction(job)
        soft_score = self._score_soft_skills(jd_text)
        semantic_score = self._score_semantic(jd_text)

        # 组装说明
        notes_parts = []
        if hit_skills:
            notes_parts.append(f"命中技能: {', '.join(hit_skills[:5])}")
        if hit_projects:
            notes_parts.append(f"匹配项目: {', '.join(hit_projects)}")
        if direction_score >= 0.8:
            notes_parts.append("方向高度契合")
        elif direction_score >= 0.5:
            notes_parts.append("方向契合")

        notes = " | ".join(notes_parts) if notes_parts else "匹配度一般"

        return ScoreBreakdown(
            skill_score=skill_score,
            project_score=project_score,
            direction_score=direction_score,
            soft_skill_score=soft_score,
            semantic_score=semantic_score,
            hit_skills=hit_skills,
            hit_projects=hit_projects,
            notes=notes,
        )

    # ---------- 维度 1：技能匹配 ----------

    def _score_skills(self, jd_text: str) -> tuple[float, list[str]]:
        """
        技能关键词加权匹配（校准版）

        评分逻辑：
        - 命中技能数 / 期望命中数（5个）作为基础分
        - 命中核心技能（权重≥2.5）额外加分
        - 命中差异化技能（χ²/SHAP/假设检验）再加分
        - 这样合理匹配能到 60-80%，强匹配 90%+
        """
        hit = []
        matched_weight = 0.0
        core_hits = 0       # 核心技能命中数
        diff_hits = 0       # 差异化技能命中数

        for skill, weight in SKILL_WEIGHTS.items():
            skill_variants = self._skill_variants(skill)
            if any(v in jd_text for v in skill_variants):
                hit.append(skill)
                matched_weight += weight
                if weight >= 2.5:
                    core_hits += 1
                # 差异化技能（统计方法 + 模型解释）
                if skill in ("χ²", "假设检验", "mann-whitney", "kruskal-wallis",
                             "shap", "lime", "ab测试", "a/b测试"):
                    diff_hits += 1

        if not hit:
            return 0.0, hit

        # 基础分：命中数 / 期望命中数（5个核心技能为合理期望）
        base_score = min(len(hit) / 5.0, 1.0)
        # 核心技能加分：每个 +0.1，最多 +0.2
        core_bonus = min(core_hits * 0.1, 0.2)
        # 差异化加分：每个 +0.08，最多 +0.16（突出简历独特性）
        diff_bonus = min(diff_hits * 0.08, 0.16)

        score = min(base_score + core_bonus + diff_bonus, 1.0)
        return score, hit

    @staticmethod
    def _skill_variants(skill: str) -> list[str]:
        """技能关键词的变体（大小写、分隔符）"""
        s = skill.lower()
        variants = [s]
        # χ² 的变体
        if "χ²" in s:
            variants.extend(["χ2", "卡方", "chi-square", "chi square"])
        # sklearn 别名
        if "sklearn" in s:
            variants.append("scikit-learn")
        if "scikit-learn" in s:
            variants.append("sklearn")
        # a/b 测试
        if "a/b" in s:
            variants.extend(["ab测试", "a/b test", "ab test"])
        return variants

    # ---------- 维度 2：项目匹配 ----------

    def _score_projects(self, jd_text: str, job: JobPosition) -> tuple[float, list[str]]:
        """项目匹配评分"""
        hit_projects = []
        max_score = 0.0

        for proj in self.resume["projects"]:
            proj_name = proj["name"]
            tags = [t.lower() for t in proj["tags"]]
            hit_count = sum(1 for t in tags if t in jd_text)
            if hit_count == 0:
                continue

            # 命中标签数 / 总标签数，作为该项目匹配度
            proj_score = min(hit_count / max(len(tags), 1), 1.0)
            if proj_score > max_score:
                max_score = proj_score
                hit_projects = [proj_name]
            elif proj_score == max_score and max_score > 0:
                hit_projects.append(proj_name)

        return max_score, hit_projects

    # ---------- 维度 3：方向匹配 ----------

    def _score_direction(self, job: JobPosition) -> float:
        """岗位方向与求职方向匹配"""
        target_roles = self.resume.get("target_roles") or [
            "数据分析", "策略运营", "增长", "AI-Agent应用"
        ]
        job_text = f"{job.direction} {job.title}".lower()

        for role in target_roles:
            if role.lower() in job_text:
                return 1.0
        # 部分匹配
        if "数据" in job_text or "分析" in job_text:
            return 0.7
        return 0.3

    # ---------- 维度 4：软技能 ----------

    def _score_soft_skills(self, jd_text: str) -> float:
        """软技能匹配（占比小）"""
        hit = sum(1 for s in SOFT_SKILLS if s in jd_text)
        return min(hit / 3, 1.0)

    # ---------- 维度 5：语义相似度（TF-IDF + cosine） ----------

    def _score_semantic(self, jd_text: str) -> float:
        """TF-IDF + cosine 相似度（轻量级语义匹配）"""
        try:
            return self._tfidf_cosine(self._resume_text, jd_text)
        except Exception as e:
            logger.debug(f"语义评分失败: {e}")
            return 0.0

    def _build_resume_text(self) -> str:
        """构建简历全文（用于 TF-IDF）"""
        parts = [self.resume.get("basics", "")]
        parts.extend(self.resume.get("skills", []))
        for proj in self.resume.get("projects", []):
            parts.append(proj["name"])
            parts.extend(proj["highlights"])
            parts.extend(proj["tags"])
        return " ".join(parts).lower()

    @staticmethod
    def _tfidf_cosine(text1: str, text2: str) -> float:
        """TF-IDF + cosine 相似度"""
        # 中文用 bigram 分词，避免 jieba 依赖
        tokens1 = JobMatcher._tokenize(text1)
        tokens2 = JobMatcher._tokenize(text2)

        if not tokens1 or not tokens2:
            return 0.0

        # 词频
        tf1 = Counter(tokens1)
        tf2 = Counter(tokens2)

        # 共享词汇的 IDF（简化：用两文档集合的 IDF）
        all_tokens = set(tokens1) | set(tokens2)
        idf = {}
        for token in all_tokens:
            count = (token in tf1) + (token in tf2)
            idf[token] = math.log(3 / (1 + count)) + 1  # 平滑

        # TF-IDF 向量
        vec1 = {t: tf1.get(t, 0) * idf[t] for t in all_tokens}
        vec2 = {t: tf2.get(t, 0) * idf[t] for t in all_tokens}

        # cosine
        dot = sum(vec1[t] * vec2[t] for t in all_tokens)
        norm1 = math.sqrt(sum(v * v for v in vec1.values()))
        norm2 = math.sqrt(sum(v * v for v in vec2.values()))

        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中文分词：bigram + 英文单词"""
        tokens = []
        # 英文单词
        tokens.extend(re.findall(r"[a-z]+", text.lower()))
        # 中文 bigram
        chinese = re.findall(r"[\u4e00-\u9fa5]", text)
        for i in range(len(chinese) - 1):
            tokens.append(chinese[i] + chinese[i + 1])
        # 中文 unigram 作为补充
        tokens.extend(chinese)
        return tokens


# ---------- CLI ----------

def main():
    """命令行：对 JSON 中的岗位批量评分"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="岗位匹配度评分")
    parser.add_argument("input", help="岗位 JSON 路径")
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--top", type=int, default=20, help="显示前 N 个")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("results", [])

    from .exporter import dict_to_position
    positions = [dict_to_position(item) for item in items]

    matcher = JobMatcher()
    matcher.score_batch(positions)

    # 排序
    positions.sort(key=lambda p: p.skill_match_score, reverse=True)

    # 输出
    print(f"=== 匹配度评分 Top {min(args.top, len(positions))} ===\n")
    for i, p in enumerate(positions[:args.top], 1):
        print(f"{i}. [{p.skill_match_score:.0%}] {p.company} - {p.title} ({p.city})")
        print(f"   {p.match_notes}")
        print()

    # 保存
    output_path = args.output or args.input.replace(".json", "_scored.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    **p.to_dict(),
                    "匹配度": f"{p.skill_match_score:.0%}",
                }
                for p in positions
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"已保存评分结果 → {output_path}")


if __name__ == "__main__":
    main()

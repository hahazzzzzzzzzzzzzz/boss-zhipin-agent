"""
数据模型：岗位信息、搜索结果等
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
import json


@dataclass
class JobPosition:
    """单个岗位信息"""
    # 基本信息
    company: str                    # 公司名称
    title: str                      # 岗位名称
    direction: str                  # 岗位方向：数据分析/策略运营/增长/AI-Agent应用
    industry: str                   # 行业：互联网/金融科技/AI/其他
    city: str                       # 工作地点：杭州/深圳
    salary: str                     # 实习薪资，如"200-300元/天"或"面议"

    # 详细描述
    responsibilities: str = ""      # 岗位职责概述
    requirements: str = ""          # 任职要求概述

    # 投递信息
    apply_link: str = ""            # 投递链接
    source: str = ""                # 来源平台：BOSS直聘/牛客网/实习僧/企业官网

    # 标签
    has_conversion: bool = False    # 是否有转正机会
    can_retain: bool = False        # 是否可留用
    target_grad: str = ""           # 面向届别

    # 匹配分析
    skill_match_score: float = 0.0  # 技能匹配度 0-1
    match_notes: str = ""           # 匹配说明

    # 元数据
    found_at: str = field(default_factory=lambda: datetime.now().isoformat())
    notes: str = ""                 # 备注

    def to_dict(self) -> dict:
        return {
            "公司名称": self.company,
            "岗位名称": self.title,
            "岗位方向": self.direction,
            "行业": self.industry,
            "工作地点": self.city,
            "实习薪资": self.salary,
            "岗位职责概述": self.responsibilities,
            "任职要求概述": self.requirements,
            "投递链接/来源": f"{self.apply_link} ({self.source})" if self.apply_link else self.source,
            "备注": self._build_notes(),
        }

    def _build_notes(self) -> str:
        notes = []
        if self.has_conversion:
            notes.append("有转正机会")
        if self.can_retain:
            notes.append("可留用")
        if self.target_grad:
            notes.append(f"面向{self.target_grad}")
        if self.skill_match_score > 0:
            notes.append(f"匹配度:{self.skill_match_score:.0%}")
        if self.match_notes:
            notes.append(self.match_notes)
        if self.notes:
            notes.append(self.notes)
        return " | ".join(notes)

    @property
    def priority_score(self) -> int:
        """优先级评分：越高越优先"""
        score = 0
        if self.has_conversion:
            score += 100
        if self.can_retain:
            score += 50
        score += int(self.skill_match_score * 30)
        return score


@dataclass
class SearchResult:
    """搜索结果集"""
    positions: List[JobPosition] = field(default_factory=list)
    search_time: str = field(default_factory=lambda: datetime.now().isoformat())
    total_found: int = 0

    @property
    def hangzhou_count(self) -> int:
        return sum(1 for p in self.positions if p.city == "杭州")

    @property
    def shenzhen_count(self) -> int:
        return sum(1 for p in self.positions if p.city == "深圳")

    @property
    def conversion_count(self) -> int:
        return sum(1 for p in self.positions if p.has_conversion)

    @property
    def direction_distribution(self) -> dict:
        dist = {}
        for p in self.positions:
            dist[p.direction] = dist.get(p.direction, 0) + 1
        return dist

    def to_json(self) -> str:
        return json.dumps([p.to_dict() for p in self.positions], ensure_ascii=False, indent=2)

    def sort_by_priority(self):
        self.positions.sort(key=lambda p: p.priority_score, reverse=True)

    def summary(self) -> str:
        """生成搜索摘要"""
        self.sort_by_priority()
        lines = [
            f"## 搜索结果摘要",
            f"- 搜索时间：{self.search_time[:19]}",
            f"- 共找到 **{len(self.positions)}** 个岗位",
            f"  - 杭州：{self.hangzhou_count} 个",
            f"  - 深圳：{self.shenzhen_count} 个",
            f"- 有转正机会：**{self.conversion_count}** 个",
            f"",
            f"### 方向分布",
        ]
        for direction, count in sorted(self.direction_distribution.items(), key=lambda x: -x[1]):
            lines.append(f"  - {direction}：{count} 个")
        return "\n".join(lines)

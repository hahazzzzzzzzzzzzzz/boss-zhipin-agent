"""
Markdown 报告生成器 — 输出可读、可复制的招呼语报告

格式特点：
- 按匹配度降序排列
- 每条招呼语独立一段，方便复制粘贴到 BOSS 直聘
- 含匹配说明、薪资、转正机会等关键信息
- 顶部有总览表，底部有复制清单
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .models import JobPosition

logger = logging.getLogger(__name__)


def generate_markdown_report(
    positions: list[JobPosition],
    greetings: dict[str, str],
    output_path: str,
    top_n: Optional[int] = None,
) -> str:
    """
    生成 Markdown 招呼语报告

    Args:
        positions: 岗位列表（已按 priority_score 排序）
        greetings: {岗位唯一键: 招呼语}，key 格式 "公司-岗位"
        output_path: 输出 .md 文件路径
        top_n: 只显示前 N 条，None 则全部

    Returns:
        Markdown 文本
    """
    # 按匹配度降序
    sorted_positions = sorted(
        positions, key=lambda p: p.skill_match_score, reverse=True
    )
    if top_n:
        sorted_positions = sorted_positions[:top_n]

    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---------- 标题 + 元信息 ----------
    lines.append(f"# BOSS 直聘招呼语报告")
    lines.append(f"")
    lines.append(f"生成时间：{now} | 共 **{len(sorted_positions)}** 个岗位")
    lines.append(f"")

    # ---------- 总览表 ----------
    lines.append(f"## 岗位总览")
    lines.append(f"")
    lines.append(f"| # | 匹配度 | 公司 | 岗位 | 城市 | 薪资 | 转正 | 来源 |")
    lines.append(f"|---|--------|------|------|------|------|------|------|")
    for i, p in enumerate(sorted_positions, 1):
        match_pct = f"{p.skill_match_score:.0%}"
        conversion = "✅" if p.has_conversion else "—"
        lines.append(
            f"| {i} | {match_pct} | {p.company} | {p.title} | {p.city} | "
            f"{p.salary} | {conversion} | {p.source} |"
        )
    lines.append(f"")

    # ---------- 招呼语详情 ----------
    lines.append(f"## 招呼语详情（按匹配度降序）")
    lines.append(f"")
    lines.append(f"> 每条招呼语独立成段，可直接复制粘贴到 BOSS 直聘聊天框")
    lines.append(f"")

    for i, p in enumerate(sorted_positions, 1):
        key = f"{p.company}-{p.title}"
        greeting = greetings.get(key, "")

        lines.append(f"### {i}. {p.company} - {p.title}")
        lines.append(f"")
        lines.append(f"- **匹配度**：{p.skill_match_score:.0%}")
        lines.append(f"- **匹配说明**：{p.match_notes or '—'}")
        lines.append(f"- **薪资**：{p.salary} | **城市**：{p.city} | **转正**：{'有' if p.has_conversion else '无'}")
        if p.notes:
            lines.append(f"- **备注**：{p.notes}")
        if p.apply_link:
            lines.append(f"- **链接**：{p.apply_link}")
        lines.append(f"")
        lines.append(f"**招呼语**（{len(greeting)} 字）：")
        lines.append(f"")
        lines.append(f"```")
        lines.append(greeting)
        lines.append(f"```")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    # ---------- 一键复制清单 ----------
    lines.append(f"## 复制清单（仅招呼语文本）")
    lines.append(f"")
    lines.append(f"以下为纯文本招呼语，方便批量复制：")
    lines.append(f"")
    for i, p in enumerate(sorted_positions, 1):
        key = f"{p.company}-{p.title}"
        greeting = greetings.get(key, "")
        if greeting:
            lines.append(f"**{i}. {p.company} - {p.title}**")
            lines.append(f"")
            lines.append(f"> {greeting}")
            lines.append(f"")

    # 写入文件
    import os
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Markdown 报告已生成: {output_path}")
    return "\n".join(lines)

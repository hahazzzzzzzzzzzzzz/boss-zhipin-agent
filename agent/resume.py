"""
简历解析器 — 支持用户上传简历文件，解析为统一结构

支持格式：
- PDF: 用 pdfplumber 提取文本
- Markdown/纯文本: 直接读取
- DOCX: 用 python-docx 提取

双路径解析：
1. 简单解析（默认）：从文本中正则提取基本信息（姓名、技能、项目）
2. LLM 解析（可选）：调用 LLM 从简历文本提取结构化信息，更准确

输出统一结构（与原 RESUME_SUMMARY 兼容）：
{
    "name": str,
    "basics": str,        # 一句话简介
    "skills": list[str],  # 技能列表
    "projects": [         # 项目经历
        {"name": str, "highlights": list[str], "tags": list[str]}
    ],
    "competitions": str,
    "languages": str,
}

使用方式：
    from agent.resume import ResumeParser
    parser = ResumeParser()
    resume = parser.parse("path/to/resume.pdf")
    # 或 LLM 解析
    resume = parser.parse_with_llm("path/to/resume.pdf")
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


# 常见技能关键词表（用于从简历文本提取技能）
SKILL_KEYWORDS = [
    # 编程语言
    "Python", "Java", "JavaScript", "SQL", "R", "Scala", "Go", "C++", "C",
    # 数据处理
    "Pandas", "NumPy", "Spark", "Hadoop", "Hive", "Flink", "Kafka",
    # 机器学习
    "Scikit-learn", "sklearn", "TensorFlow", "PyTorch", "Keras",
    "LightGBM", "XGBoost", "CatBoost",
    # NLP/CV
    "NLTK", "spaCy", "Transformers", "HuggingFace", "OpenCV",
    # 统计
    "假设检验", "卡方检验", "χ²", "方差分析", "ANOVA",
    "Mann-Whitney", "Kruskal-Wallis", "时间序列", "ARIMA", "SARIMA",
    "回归分析", "聚类", "贝叶斯",
    # 模型解释
    "SHAP", "LIME",
    # 业务
    "用户行为分析", "用户画像", "指标体系", "AB测试", "A/B测试",
    "风控", "信贷", "违约预测", "特征工程",
    # 工具
    "Excel", "Tableau", "PowerBI", "Matplotlib", "Seaborn", "Plotly",
    "Git", "Linux", "Docker",
    # 数据库
    "MySQL", "PostgreSQL", "MongoDB", "Redis",
    # 大模型
    "LLM", "Agent", "RAG", "Prompt Engineering",
    # 通用
    "数据分析", "数据挖掘", "数据可视化", "机器学习", "深度学习",
    "迁移学习", "域适应",
]


class ResumeParser:
    """简历解析器"""

    def __init__(self, llm_provider: str = "codebuddy"):
        self.llm_provider = llm_provider

    # ---------- 文件读取 ----------

    @staticmethod
    def read_file(file_path: str) -> str:
        """根据扩展名读取简历文件为纯文本"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"简历文件不存在: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return ResumeParser._read_pdf(file_path)
        elif ext == ".docx":
            return ResumeParser._read_docx(file_path)
        elif ext in (".md", ".markdown", ".txt", ""):
            return ResumeParser._read_text(file_path)
        else:
            # 尝试当文本读
            logger.warning(f"未知扩展名 {ext}，尝试当文本读取")
            return ResumeParser._read_text(file_path)

    @staticmethod
    def _read_pdf(file_path: str) -> str:
        try:
            import pdfplumber
        except ImportError:
            try:
                from PyPDF2 import PdfReader
                logger.warning("使用 PyPDF2（建议安装 pdfplumber: pip install pdfplumber）")
                reader = PdfReader(file_path)
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                raise ImportError("需要安装 pdfplumber: pip install pdfplumber")

        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)

    @staticmethod
    def _read_docx(file_path: str) -> str:
        try:
            from docx import Document
        except ImportError:
            raise ImportError("需要安装 python-docx: pip install python-docx")
        doc = Document(file_path)
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())

    @staticmethod
    def _read_text(file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    # ---------- 简单解析（正则） ----------

    def parse(self, file_path: str) -> dict:
        """
        简单解析：从文本中提取技能、项目等
        不依赖 LLM，速度快，但结构化程度低
        """
        text = self.read_file(file_path)
        return self._parse_text(text)

    def _parse_text(self, text: str) -> dict:
        """从纯文本解析为结构化简历"""
        # 姓名：开头第一行 或 "姓名：xxx"
        name = ""
        name_match = re.search(r'(?:姓名|Name)[:：\s]*([^\s,，。]+)', text)
        if name_match:
            name = name_match.group(1).strip()
        else:
            # 取第一行非空文本前 10 字符
            first_line = next((line.strip() for line in text.split("\n") if line.strip()), "")
            if len(first_line) <= 20 and not any(c in first_line for c in "@|·"):
                name = first_line

        # 学历
        degree = ""
        degree_match = re.search(r'(本科|硕士|博士|学士)\s*(?:在读|研究生)?', text)
        if degree_match:
            degree = degree_match.group(0)

        # 技能：匹配关键词表
        skills = []
        text_lower = text.lower()
        for skill in SKILL_KEYWORDS:
            skill_lower = skill.lower()
            # 处理别名
            variants = [skill_lower]
            if "χ²" in skill_lower:
                variants.extend(["χ2", "卡方", "chi-square"])
            if "sklearn" in skill_lower:
                variants.append("scikit-learn")
            if "scikit-learn" in skill_lower:
                variants.append("sklearn")
            if "a/b" in skill_lower:
                variants.extend(["ab测试", "a/b test"])

            if any(v in text_lower for v in variants):
                skills.append(skill)

        # 项目：找"项目"或"经历"段落
        projects = self._extract_projects(text)

        # 学校
        school = ""
        school_match = re.search(r'(?:学校|University|学院)[:：\s]*([^\s,，。]+)', text)
        if school_match:
            school = school_match.group(1)

        basics_parts = []
        if degree:
            basics_parts.append(f"{degree}在读")
        if school:
            basics_parts.append(school)
        basics = "，".join(basics_parts) if basics_parts else "求职者"

        return {
            "name": name or "求职者",
            "basics": basics,
            "skills": skills,
            "projects": projects,
            "competitions": "",
            "languages": "",
            "raw_text": text[:2000],  # 保留原文前 2000 字，供 LLM 模式用
        }

    @staticmethod
    def _extract_projects(text: str) -> list[dict]:
        """从文本中提取项目经历（启发式）"""
        projects = []
        # 找"项目经历"/"项目经验"/"项目"段落
        project_section_match = re.search(
            r'(?:项目经历|项目经验|项目|Projects?)[:：\s]*(.*?)(?:实习经历|工作经历|教育经历|教育背景|技能|自我评价|获奖|\Z)',
            text, re.DOTALL | re.IGNORECASE,
        )
        if not project_section_match:
            return projects

        section = project_section_match.group(1)
        # 按空行或换行符分割项目
        # 启发式：每个项目以「项目名：」或「- 项目名」开头
        proj_blocks = re.split(r'\n\s*(?=[\u4e00-\u9fa5\w]+项目|项目[\u4e00-\u9fa5\w]+[:：]|-\s)', section)

        for block in proj_blocks:
            block = block.strip()
            if len(block) < 20:
                continue
            # 项目名：第一行或冒号前
            first_line = block.split("\n")[0].strip()
            proj_name = first_line.split("：")[0].split(":")[0].strip()[:50]

            # 提取要点（以 - 或数字开头的行）
            highlights = []
            for line in block.split("\n")[1:]:
                line = line.strip()
                if re.match(r'^[-\d•·]', line):
                    clean = re.sub(r'^[-\d•·\s]+', '', line).strip()
                    if clean and len(clean) > 5:
                        highlights.append(clean[:100])

            if not highlights:
                # 没找到要点，取整段前 200 字
                highlights = [block[:200]]

            # 推断 tags：从项目文本中匹配技能
            tags = []
            block_lower = block.lower()
            for skill in SKILL_KEYWORDS:
                if skill.lower() in block_lower:
                    tags.append(skill)

            projects.append({
                "name": proj_name,
                "highlights": highlights[:3],
                "tags": tags[:5],
            })

        return projects[:5]  # 最多 5 个项目

    # ---------- LLM 解析（更准确） ----------

    def parse_with_llm(self, file_path: str) -> dict:
        """
        LLM 解析：调用 LLM 从简历文本提取结构化信息
        比简单解析更准确，特别是项目经历的结构化
        """
        text = self.read_file(file_path)
        return self._parse_with_llm_text(text)

    def _parse_with_llm_text(self, text: str) -> dict:
        """用 LLM 解析简历文本"""
        import os
        api_key = (
            os.environ.get("LLM_API_KEY")
            or os.environ.get("CODEBUDDY_API_KEY", "")
        ).strip()
        if not api_key:
            logger.warning("LLM_API_KEY 未配置，回退到简单解析")
            return self._parse_text(text)

        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai 未安装，回退到简单解析")
            return self._parse_text(text)

        base_url = (
            os.environ.get("LLM_BASE_URL")
            or os.environ.get("CODEBUDDY_BASE_URL")
            or "https://api.codebuddy.com/v1"
        )
        model = os.environ.get("LLM_MODEL") or os.environ.get("CODEBUDDY_MODEL") or "qwen-plus"

        client = OpenAI(api_key=api_key, base_url=base_url)

        # 截取前 3000 字（避免 token 过多）
        resume_text = text[:3000]

        prompt = f"""请从以下简历文本中提取结构化信息，输出 JSON 格式。

要求：
1. 严格输出 JSON，不要任何解释或 markdown 标记
2. 字段说明：
   - name: 姓名
   - basics: 一句话简介（学历+学校+求职方向，不超过 30 字）
   - skills: 技能列表（数组，10-20 个，包含编程语言、工具、统计方法、机器学习算法等）
   - projects: 项目经历数组，每个项目含：
     - name: 项目名（简短）
     - highlights: 亮点数组（2-3 条，每条带具体数据指标）
     - tags: 相关技能标签数组（3-5 个）
   - competitions: 竞赛获奖
   - languages: 语言能力

【简历文本】
{resume_text}

【输出 JSON 格式示例】
{{
  "name": "张三",
  "basics": "应用统计硕士在读，XX大学，2027届",
  "skills": ["Python", "SQL", "Pandas", "LightGBM", "χ²检验", "SHAP"],
  "projects": [
    {{
      "name": "用户行为分析",
      "highlights": ["LightGBM购买预测AUC=0.95", "χ²检验定位转化瓶颈推动业务指标提升"],
      "tags": ["LightGBM", "用户行为分析", "χ²", "SHAP"]
    }}
  ],
  "competitions": "数学建模竞赛奖项",
  "languages": "CET-6，英语可作为工作语言"
}}"""

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是简历解析助手，严格输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1500,
            )
            content = resp.choices[0].message.content.strip()
            # 清理 markdown 标记
            content = content.strip("`").strip()
            if content.startswith("json"):
                content = content[4:].strip()

            import json
            resume = json.loads(content)

            # 兜底字段
            resume.setdefault("name", "求职者")
            resume.setdefault("basics", "求职者")
            resume.setdefault("skills", [])
            resume.setdefault("projects", [])
            resume.setdefault("competitions", "")
            resume.setdefault("languages", "")
            resume["raw_text"] = text[:2000]

            logger.info(f"LLM 简历解析成功：{resume['name']}，{len(resume['skills'])} 个技能，{len(resume['projects'])} 个项目")
            return resume
        except Exception as e:
            logger.warning(f"LLM 简历解析失败，回退简单解析: {e}")
            return self._parse_text(text)


# ---------- CLI 入口 ----------

def main():
    """命令行：解析简历并打印结构化结果"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="简历解析器")
    parser.add_argument("resume_path", help="简历文件路径（PDF/Markdown/纯文本）")
    parser.add_argument("--llm", action="store_true", help="使用 LLM 解析（更准确但需要 API）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    rp = ResumeParser()
    if args.llm:
        print(f"使用 LLM 解析: {args.resume_path}")
        resume = rp.parse_with_llm(args.resume_path)
    else:
        print(f"使用简单解析: {args.resume_path}")
        resume = rp.parse(args.resume_path)

    print()
    print(f"姓名: {resume['name']}")
    print(f"简介: {resume['basics']}")
    print(f"技能 ({len(resume['skills'])}): {', '.join(resume['skills'][:15])}")
    print(f"项目 ({len(resume['projects'])}):")
    for i, p in enumerate(resume["projects"], 1):
        print(f"  {i}. {p['name']}")
        for h in p["highlights"][:2]:
            print(f"     - {h}")
        print(f"     tags: {', '.join(p['tags'])}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            # 移除 raw_text 避免输出过大
            output = {k: v for k, v in resume.items() if k != "raw_text"}
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n已保存: {args.output}")


if __name__ == "__main__":
    main()

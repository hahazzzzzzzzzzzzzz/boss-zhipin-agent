"""
用户画像与搜索配置
敏感信息通过环境变量配置，支持脱敏分享。
使用前复制 .env.example 为 .env 并填入真实值。
"""
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class UserProfile:
    """用户画像 — 通过环境变量配置"""
    name: str = field(default_factory=lambda: os.environ.get("USER_NAME", "姓名占位"))
    degree: str = field(default_factory=lambda: os.environ.get("USER_DEGREE", "学历占位"))
    school: str = field(default_factory=lambda: os.environ.get("USER_SCHOOL", "学校占位"))
    graduation_year: str = field(default_factory=lambda: os.environ.get("USER_GRADUATION_YEAR", "2027届"))
    arrival: str = "随时到岗"

    # 求职方向（按优先级排序）
    target_roles: List[str] = field(default_factory=lambda: [
        "数据分析", "策略运营", "增长", "AI-Agent应用"
    ])

    # 目标城市
    target_cities: List[str] = field(default_factory=lambda: ["杭州", "深圳"])

    # 期望行业
    target_industries: List[str] = field(default_factory=lambda: [
        "互联网", "金融科技", "AI"
    ])

    # 薪资范围（元/天）
    salary_min: int = 200
    salary_max: int = 400

    # 偏好
    prefer_small_medium: bool = True  # 偏好中小厂
    prefer_conversion: bool = True    # 优先有转正机会

    # 技能栈
    skills: List[str] = field(default_factory=lambda: [
        "Python", "Pandas", "NumPy", "sklearn", "TensorFlow",
        "SQL", "Tableau", "SHAP", "LIME", "时序模型",
        "LightGBM", "XGBoost", "迁移学习"
    ])


@dataclass
class SearchConfig:
    """搜索配置"""
    # 搜索平台
    platforms: List[str] = field(default_factory=lambda: [
        "BOSS直聘", "牛客网", "实习僧", "企业官网"
    ])

    # 搜索关键词模板
    keywords: List[str] = field(default_factory=lambda: [
        "数据分析实习生",
        "策略运营实习生",
        "增长实习生",
        "AI Agent实习生",
        "数据科学实习生",
    ])

    # 每次搜索最大结果数
    max_results_per_platform: int = 20

    # 输出目录
    output_dir: str = "data"

    # 目标公司（优先搜索）
    target_companies: List[str] = field(default_factory=lambda: [
        "字节跳动", "阿里巴巴", "蚂蚁集团", "腾讯", "快手",
        "美团", "拼多多", "小红书", "哔哩哔哩", "滴滴",
        "众安保险", "网易", "大疆", "华为", "宁德时代",
    ])

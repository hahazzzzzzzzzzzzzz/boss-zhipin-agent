"""
BOSS直聘求职Agent - 核心模块
专为2027届数据分析实习生打造的岗位搜索与投递辅助Agent
"""

from .config import UserProfile, SearchConfig
from .models import JobPosition, SearchResult
from .exporter import ExcelExporter

__version__ = "1.0.0"
__all__ = ["UserProfile", "SearchConfig", "JobPosition", "SearchResult", "ExcelExporter"]

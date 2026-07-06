"""
BOSS直聘求职Agent - 核心模块
专为2027届数据分析实习生打造的岗位搜索、评分与招呼语生成辅助Agent
"""

from .config import UserProfile, SearchConfig
from .models import JobPosition, SearchResult
from .exporter import ExcelExporter, dict_to_position
from .fetcher import (
    FetcherPipeline, BOSSFetcher, BOSSPlaywrightFetcher,
    NowcoderFetcher, ShixisengFetcher,
)
from .matcher import JobMatcher
from .greeting import GreetingGenerator
from .reporter import generate_markdown_report
from .resume import ResumeParser

__version__ = "3.1.0"
__all__ = [
    "UserProfile",
    "SearchConfig",
    "JobPosition",
    "SearchResult",
    "ExcelExporter",
    "dict_to_position",
    "FetcherPipeline",
    "BOSSFetcher",
    "BOSSPlaywrightFetcher",
    "NowcoderFetcher",
    "ShixisengFetcher",
    "JobMatcher",
    "GreetingGenerator",
    "generate_markdown_report",
    "ResumeParser",
]

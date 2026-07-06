"""
岗位抓取器 — 实际抓取 BOSS 直聘 / 实习僧 / 牛客网 岗位数据

设计要点：
- BOSS 直聘：Web 端强反爬，走 wapi/zpgeek/search/joblist.json，需 BOSS_COOKIE
- 实习僧：JSON API /app/interns/search/v2，**字体反爬**，需 fonttools 动态解码
- 牛客网：旧 API /np/cover/intern/search 已失效，新页面 SSR 但翻页触发滑块，
          纯 requests 不可行，标记 deprecated
- Cookie 通过环境变量注入（用户从浏览器 F12 复制）
- 限速 + 随机延迟，避免触发风控
- 抓取器可插拔，统一返回 JobPosition 列表

使用方式：
    from agent.fetcher import FetcherPipeline
    pipeline = FetcherPipeline(platforms=["实习僧", "BOSS直聘"])
    positions = pipeline.fetch(keywords=["数据分析实习生"], cities=["杭州", "深圳"])
"""
from __future__ import annotations

import io
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

from .models import JobPosition

logger = logging.getLogger(__name__)


# ---------- 异常 ----------

class FetchError(RuntimeError):
    """抓取过程中的错误"""


# ---------- 基类 ----------

class BaseFetcher:
    """抓取器基类"""
    platform: str = ""
    base_url: str = ""

    def __init__(self, timeout: int = 15, max_per_keyword: int = 30,
                 cache_dir: str | None = "data/.fetch_cache",
                 cache_ttl: int = 3600 * 6):
        """
        cache_dir: 抓取结果磁盘缓存目录，None 则不缓存
        cache_ttl: 缓存有效期（秒），默认 6 小时
        """
        self.timeout = timeout
        self.max_per_keyword = max_per_keyword
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl

    def fetch(self, keyword: str, city: str) -> list[JobPosition]:
        raise NotImplementedError

    @staticmethod
    def _sleep(base: float = 2.0, jitter: float = 2.0):
        """随机延迟，避免请求规律"""
        time.sleep(base + random.random() * jitter)

    @staticmethod
    def _get_session():
        """构建 requests Session，注入通用 Header"""
        try:
            import requests
        except ImportError as e:
            raise FetchError("需要安装 requests: pip install requests") from e

        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        return s

    # ---------- 磁盘缓存 ----------

    def _cache_key(self, *args) -> str:
        """生成缓存键"""
        import hashlib
        key_str = f"{self.platform}|{'|'.join(str(a) for a in args)}"
        return hashlib.md5(key_str.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> list[JobPosition] | None:
        """从磁盘读缓存，返回 None 表示未命中"""
        if not self.cache_dir:
            return None
        import os
        path = os.path.join(self.cache_dir, f"{key}.json")
        if not os.path.exists(path):
            return None
        # 检查 TTL
        mtime = os.path.getmtime(path)
        if time.time() - mtime > self.cache_ttl:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 反序列化 JobPosition
            from .exporter import dict_to_position
            return [dict_to_position(d) for d in data]
        except Exception as e:
            logger.debug(f"缓存读取失败 {key}: {e}")
            return None

    def _cache_set(self, key: str, positions: list[JobPosition]):
        """写缓存到磁盘"""
        if not self.cache_dir:
            return
        import os
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            path = os.path.join(self.cache_dir, f"{key}.json")
            # 序列化 JobPosition（用与 dict_to_position 兼容的中文 key）
            data = [
                {
                    "公司名称": p.company, "岗位名称": p.title, "岗位方向": p.direction,
                    "行业": p.industry, "工作地点": p.city, "实习薪资": p.salary,
                    "岗位职责概述": p.responsibilities, "任职要求概述": p.requirements,
                    "投递链接/来源": p.apply_link, "来源平台": p.source,
                    "有转正机会": p.has_conversion, "面向届别": p.target_grad,
                    "备注": p.notes,
                }
                for p in positions
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"缓存写入失败 {key}: {e}")

    @staticmethod
    def _infer_direction(text: str) -> str:
        text = text.lower()
        if any(k in text for k in ["策略", "运营", "增长"]):
            return "策略运营"
        if any(k in text for k in ["ai", "agent", "llm", "大模型"]):
            return "AI-Agent应用"
        if any(k in text for k in ["数据科学", "算法", "机器学习"]):
            return "数据科学"
        if any(k in text for k in ["风控", "信贷", "建模"]):
            return "风控建模"
        return "数据分析"

    @staticmethod
    def _infer_industry(text: str) -> str:
        text = text.lower()
        if any(k in text for k in ["金融", "保险", "银行", "信贷"]):
            return "金融科技"
        if any(k in text for k in ["ai", "人工智能", "大模型"]):
            return "AI"
        return "互联网"


# ---------- 实习僧（推荐：JSON API + 字体解码，无需登录） ----------

class ShixisengFetcher(BaseFetcher):
    """
    实习僧抓取器 — https://www.shixiseng.com/app/interns/search/v2 + 详情页补全 JD

    特点：
    - 列表 API：JSON，无需登录，**字体反爬**（name/cname/minsal 等用 woff 加密）
    - 详情页：HTML，无需登录，**无字体加密**，从 window.__NUXT__ 提取 JD 正文
    - 解码方案：fontTools 解析 cmap，glyph 名 uniXXXX 直接转字符
    """
    platform = "实习僧"
    base_url = "https://www.shixiseng.com/app/interns/search/v2"
    font_url = "https://www.shixiseng.com/interns/iconfonts/file"
    home_url = "https://www.shixiseng.com/"
    detail_url_tpl = "https://www.shixiseng.com/intern/{uuid}?pcm=pc_SearchList"

    def __init__(self, timeout: int = 15, max_per_keyword: int = 30,
                 fetch_detail: bool = True, detail_limit: int = 10,
                 detail_workers: int = 6,
                 cache_dir: str | None = "data/.fetch_cache",
                 cache_ttl: int = 3600 * 6):
        """
        fetch_detail: 是否抓详情页补全 JD（会增加请求量，默认 True）
        detail_limit: 每个关键词最多抓多少个详情页（控制请求量，默认 10）
        detail_workers: 详情页并发数（默认 6）
        cache_dir: 抓取结果磁盘缓存目录，None 则不缓存
        cache_ttl: 缓存有效期（秒），默认 6 小时
        """
        super().__init__(timeout, max_per_keyword, cache_dir, cache_ttl)
        self._cmap: dict[int, str] | None = None
        self.fetch_detail = fetch_detail
        self.detail_limit = detail_limit
        self.detail_workers = detail_workers

    def _get_cmap(self, session) -> dict[int, str]:
        """获取字体 cmap 映射（带缓存）"""
        if self._cmap is not None:
            return self._cmap

        try:
            from fontTools.ttLib import TTFont
        except ImportError:
            logger.warning("需要 fonttools: pip install fonttools")
            return {}

        params = {"rand": str(random.random())}
        try:
            resp = session.get(self.font_url, params=params, timeout=self.timeout)
            if resp.status_code != 200 or len(resp.content) < 100:
                logger.warning(f"字体文件获取失败: status={resp.status_code}")
                return {}
            font = TTFont(io.BytesIO(resp.content))
            cmap = font.getBestCmap()
            self._cmap = cmap
            logger.info(f"实习僧字体 cmap 加载成功，{len(cmap)} 个字符")
            return cmap
        except Exception as e:
            logger.warning(f"字体解析失败: {e}")
            return {}

    def _decode(self, text: str, cmap: dict[int, str]) -> str:
        """解码实习僧字体加密文本"""
        if not text or not cmap:
            return text

        def replace_entity(m):
            hex_str = m.group(1)
            try:
                cp = int(hex_str, 16)
            except ValueError:
                return m.group(0)
            glyph_name = cmap.get(cp)
            if not glyph_name:
                return ""
            match = re.match(r'uni([0-9A-Fa-f]+)', glyph_name)
            if match:
                real_cp = int(match.group(1), 16)
                return chr(real_cp)
            return ""

        return re.sub(r'&#x([0-9a-fA-F]+);?', replace_entity, text)

    def fetch(self, keyword: str, city: str) -> list[JobPosition]:
        # 1. 先查缓存
        cache_key = self._cache_key(keyword, city, self.max_per_keyword,
                                     self.fetch_detail, self.detail_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info(f"实习僧 [{keyword}/{city}] 缓存命中，{len(cached)} 个岗位")
            return cached

        session = self._get_session()
        session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.shixiseng.com/interns",
        })

        try:
            session.get(self.home_url, timeout=self.timeout)
        except Exception as e:
            logger.debug(f"实习僧首页访问失败（继续）: {e}")

        cmap = self._get_cmap(session)

        positions: list[JobPosition] = []
        for page in range(1, 4):
            if len(positions) >= self.max_per_keyword:
                break

            params = {
                "build_time": str(int(time.time() * 1000)),
                "page": str(page),
                "type": "intern",
                "keyword": keyword,
                "city": city,
                "salary": "-0",
                "area": "", "months": "", "days": "", "degree": "",
                "official": "", "enterprise": "", "publishTime": "",
                "sortType": "", "internExtend": "",
            }
            try:
                self._sleep(base=1.5, jitter=1.5)
                resp = session.get(self.base_url, params=params, timeout=self.timeout)
                data = resp.json()
            except Exception as e:
                logger.error(f"实习僧请求失败 [{keyword}/{city}/p{page}]: {e}")
                break

            msg = data.get("msg")
            if not isinstance(msg, dict):
                logger.error(f"实习僧响应异常: code={data.get('code')}")
                break

            items = msg.get("data", [])
            if not items:
                break

            for item in items:
                pos = self._parse_item(item, keyword, city, cmap)
                if pos:
                    positions.append(pos)
                if len(positions) >= self.max_per_keyword:
                    break

        # 抓详情页补全 JD（并发）
        if self.fetch_detail and positions:
            detail_count = min(self.detail_limit, len(positions))
            todo = [p for p in positions[:detail_count] if not p.responsibilities]
            if todo:
                logger.info(f"实习僧 [{keyword}/{city}] 并发抓取 {len(todo)} 个详情页（{self.detail_workers} 并发）...")
                self._fetch_details_concurrent(session, todo)

        # 写缓存
        self._cache_set(cache_key, positions)
        logger.info(f"实习僧 [{keyword}/{city}] 抓取 {len(positions)} 个岗位")
        return positions

    def _fetch_details_concurrent(self, session, positions: list[JobPosition]):
        """并发抓取详情页 JD"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def worker(pos: JobPosition) -> tuple[JobPosition, str]:
            # 每个线程内随机微延迟，避免请求过于同步
            time.sleep(random.random() * 0.5)
            jd = self._fetch_detail_jd(session, pos.apply_link)
            return pos, jd

        with ThreadPoolExecutor(max_workers=self.detail_workers) as pool:
            futures = {pool.submit(worker, p): p for p in positions}
            for fut in as_completed(futures):
                pos, jd = fut.result()
                if not jd:
                    continue
                # 切分职责/要求
                if "\n" in jd and len(jd) > 200:
                    mid = len(jd) // 2
                    for offset in range(0, 50):
                        for direction in [1, -1]:
                            idx = jd.rfind("\n", 0, mid + offset * direction)
                            if idx > 0:
                                pos.responsibilities = jd[:idx].strip()[:400]
                                pos.requirements = jd[idx:].strip()[:400]
                                break
                        if pos.responsibilities:
                            break
                if not pos.responsibilities:
                    pos.responsibilities = jd[:400]
                    pos.requirements = ""

    def _fetch_detail_jd(self, session, detail_url: str) -> str:
        """从详情页 HTML 提取 JD 正文（从 window.__NUXT__ 解析）"""
        if not detail_url:
            return ""

        try:
            resp = session.get(detail_url, timeout=self.timeout)
            html = resp.text
        except Exception as e:
            logger.debug(f"详情页抓取失败 {detail_url}: {e}")
            return ""

        # 从 window.__NUXT__ 中提取 k.info="..." 字段
        # Nuxt SSR 数据是 JS 函数体，k.info 是 JD 正文
        # 正则匹配 k.info="..." 或 k.info=`...`
        patterns = [
            r'k\.info\s*=\s*"((?:[^"\\]|\\.)*)"',
            r'k\.info\s*=\s*`([^`]*)`',
            r'"info"\s*:\s*"((?:[^"\\]|\\.)*)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                info = match.group(1)
                # 还原 JS 转义
                info = info.replace("\\n", "\n").replace("\\u002F", "/").replace('\\"', '"')
                info = info.replace("\\t", "\t").replace("\\r", "")
                return info.strip()

        # 备选：从 HTML 选择器提取（job_detail 类）
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            job_detail = soup.select_one("div.job_detail")
            if job_detail:
                return job_detail.get_text(separator="\n", strip=True)
        except ImportError:
            pass

        return ""

    def _parse_item(self, item: dict, keyword: str, city: str, cmap: dict) -> JobPosition | None:
        try:
            name = self._decode(item.get("name", ""), cmap)
            company = self._decode(item.get("cname", ""), cmap)
            if not name or not company:
                return None

            # 优先用数字字段（明文），fallback 到字体解码
            minsal_num = item.get("minsalary") or item.get("minsal")
            maxsal_num = item.get("maxsalary") or item.get("maxsal")
            try:
                if minsal_num and maxsal_num and str(minsal_num).isdigit():
                    salary = f"{minsal_num}-{maxsal_num}元/天"
                else:
                    minsal = self._decode(str(item.get("minsal", "")), cmap)
                    maxsal = self._decode(str(item.get("maxsal", "")), cmap)
                    salary = f"{minsal}-{maxsal}元/天" if minsal and maxsal else "面议"
            except Exception:
                salary = "面议"

            item_city = self._decode(item.get("city", ""), cmap) or city
            scale = self._decode(item.get("scale", ""), cmap)
            industry = self._decode(item.get("industry", ""), cmap)
            degree = self._decode(item.get("degree", ""), cmap)

            # day 优先用明文 day_num
            day_num = item.get("day_num") or item.get("day")
            try:
                if str(day_num).isdigit():
                    day = str(day_num)
                else:
                    day = self._decode(str(day_num), cmap)
            except Exception:
                day = ""

            tags = item.get("i_tags", []) or []
            has_conversion = any(
                any(k in t for k in ["转正", "留用", "return"])
                for t in tags
            )

            # 详情页 URL（用 uuid 拼接）
            uuid = item.get("uuid", "")
            apply_link = self.detail_url_tpl.format(uuid=uuid) if uuid else ""

            notes_parts = []
            if degree:
                notes_parts.append(degree)
            if day:
                notes_parts.append(f"{day}天/周")
            if scale:
                notes_parts.append(scale)
            notes = " | ".join(notes_parts[:3])

            desc_text = f"{name} {' '.join(tags)}".lower()
            return JobPosition(
                company=company,
                title=name,
                direction=self._infer_direction(name),
                industry=self._infer_industry(industry),
                city=item_city,
                salary=salary,
                responsibilities="",  # 由详情页补全
                requirements="",
                apply_link=apply_link,
                source=self.platform,
                has_conversion=has_conversion,
                target_grad="2027届" if "2027" in desc_text else "",
                notes=notes,
            )
        except Exception as e:
            logger.warning(f"实习僧岗位解析失败: {e}")
            return None


# ---------- BOSS 直聘 ----------

class BOSSFetcher(BaseFetcher):
    """
    BOSS 直聘抓取器 — 走 wapi/zpgeek/search/joblist.json 接口

    前置条件：用户从浏览器复制 cookie 到环境变量 BOSS_COOKIE。
    获取方式：
        1. 浏览器登录 https://www.zhipin.com
        2. F12 → Network → 搜索 "joblist" → 找到请求 → Headers → Cookie 全部复制
        3. 写入 .env: BOSS_COOKIE=...
    """
    platform = "BOSS直聘"
    base_url = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"

    CITY_CODES = {
        "北京": "101010100", "上海": "101020100", "杭州": "101210100",
        "深圳": "101280100", "广州": "101280101", "成都": "101270100",
        "南京": "101190100", "苏州": "190400100", "武汉": "101200100",
        "西安": "101110100", "长沙": "101250100", "重庆": "101040100",
        "天津": "101030100", "郑州": "101180100", "青岛": "101120200",
    }

    def __init__(self, timeout: int = 15, max_per_keyword: int = 30):
        super().__init__(timeout, max_per_keyword)
        self.cookie = os.environ.get("BOSS_COOKIE", "").strip()
        if not self.cookie:
            logger.warning(
                "BOSS_COOKIE 未配置，BOSS 直聘抓取大概率失败。"
                "请从浏览器 F12 复制 cookie 写入 .env"
            )

    def fetch(self, keyword: str, city: str) -> list[JobPosition]:
        city_code = self.CITY_CODES.get(city)
        if not city_code:
            logger.warning(f"BOSS 直聘未配置城市码：{city}，跳过")
            return []

        session = self._get_session()
        session.headers.update({
            "Cookie": self.cookie,
            "Referer": f"https://www.zhipin.com/web/geek/job?query={quote(keyword)}&city={city_code}",
            "Accept": "application/json, text/plain, */*",
        })

        positions: list[JobPosition] = []
        for page in range(1, 4):
            if len(positions) >= self.max_per_keyword:
                break

            params = {
                "scene": "1", "query": keyword, "city": city_code,
                "page": str(page), "pageSize": "30",
            }
            try:
                self._sleep()
                resp = session.get(self.base_url, params=params, timeout=self.timeout)
                data = resp.json()
            except Exception as e:
                logger.error(f"BOSS 直聘请求失败 [{keyword}/{city}/p{page}]: {e}")
                break

            if data.get("code") != 0:
                logger.error(
                    f"BOSS 直聘返回错误码: {data.get('code')} "
                    f"message: {data.get('message')} — 可能 cookie 过期或触发风控"
                )
                break

            job_list = data.get("zpData", {}).get("jobList", [])
            if not job_list:
                break

            for job in job_list:
                pos = self._parse_job(job, keyword, city)
                if pos:
                    positions.append(pos)
                if len(positions) >= self.max_per_keyword:
                    break

        logger.info(f"BOSS 直聘 [{keyword}/{city}] 抓取 {len(positions)} 个岗位")
        return positions

    def _parse_job(self, job: dict, keyword: str, city: str) -> JobPosition | None:
        try:
            job_name = job.get("jobName", "")
            brand_name = job.get("brandName", "")
            if not job_name or not brand_name:
                return None

            salary = job.get("salaryDesc", "面议")
            direction = self._infer_direction(job_name + " " + job.get("postDescription", ""))
            industry = self._infer_industry(job.get("brandIndustry", ""))

            skills = job.get("skills", [])
            job_labels = job.get("jobLabels", [])

            responsibilities = job.get("postDescription", "")[:300]
            requirements = "、".join(skills) if skills else ""

            desc_text = " ".join(job_labels + [job.get("jobName", "")])
            has_conversion = any(
                kw in desc_text for kw in ["转正", "留用", "return offer"]
            )

            encrypt_id = job.get("encryptJobId", "")
            apply_link = (
                f"https://www.zhipin.com/job_detail/{encrypt_id}.html"
                if encrypt_id else ""
            )

            return JobPosition(
                company=brand_name,
                title=job_name,
                direction=direction,
                industry=industry,
                city=city,
                salary=salary,
                responsibilities=responsibilities,
                requirements=requirements,
                apply_link=apply_link,
                source=self.platform,
                has_conversion=has_conversion,
                target_grad="2027届" if "2027" in desc_text else "",
                notes=" | ".join(job_labels[:3]) if job_labels else "",
            )
        except Exception as e:
            logger.warning(f"BOSS 岗位解析失败: {e}")
            return None


# ---------- BOSS 直聘（Playwright 接管真实浏览器） ----------

class BOSSPlaywrightFetcher(BaseFetcher):
    """
    BOSS 直聘抓取器（Playwright 版）— 接管用户已登录的 Chrome 浏览器

    优势：
    - 用真实浏览器 + 用户 Chrome profile，复用登录态，无需手动复制 cookie
    - 绕过 wapi 风控（页面渲染由浏览器完成，JS 校验自动通过）
    - 自动等待列表加载，稳定性高

    前置条件：
    1. 安装 Playwright: pip install playwright && playwright install chromium
    2. 用户 Chrome 已登录 BOSS 直聘（profile 路径自动检测）
       或通过 --chrome-profile 指定

    使用方式：
        fetcher = BOSSPlaywrightFetcher()
        positions = fetcher.fetch("数据分析", "杭州")
    """
    platform = "BOSS直聘"
    base_url = "https://www.zhipin.com/web/geek/job"

    CITY_CODES = BOSSFetcher.CITY_CODES

    def __init__(self, timeout: int = 30, max_per_keyword: int = 30,
                 chrome_channel: str = "chrome",
                 user_data_dir: str | None = None,
                 headless: bool = False,
                 cache_dir: str | None = "data/.fetch_cache",
                 cache_ttl: int = 3600 * 6):
        """
        chrome_channel: "chrome" / "msedge" / "chromium"
        user_data_dir: Chrome 用户数据目录，None 则自动检测
        headless: 是否无头（建议 False，BOSS 直聘检测无头）
        """
        super().__init__(timeout, max_per_keyword, cache_dir, cache_ttl)
        self.chrome_channel = chrome_channel
        self.user_data_dir = user_data_dir or self._detect_chrome_profile()
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @staticmethod
    def _detect_chrome_profile() -> str:
        """自动检测 Chrome 用户数据目录"""
        import os
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
            os.path.expanduser("~/Library/Application Support/Google/Chrome"),
            os.path.expanduser("~/.config/google-chrome"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return ""

    def _ensure_playwright(self):
        """启动 Playwright + 接管 Chrome（懒加载）"""
        if self._page is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise FetchError(
                "需要安装 Playwright: pip install playwright && playwright install chromium"
            )

        self._playwright = sync_playwright().start()

        launch_args = {
            "headless": self.headless,
            "channel": self.chrome_channel,
        }
        if self.user_data_dir:
            # 用 connect_over_cdp 接管已运行的 Chrome，或 launch_persistent_context
            # 这里用 launch_persistent_context（启动新窗口但复用 profile）
            import os
            os.makedirs(self.user_data_dir, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                channel=self.chrome_channel,
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        else:
            self._browser = self._playwright.chromium.launch(**launch_args)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()

        # 注入反检测脚本
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

    def fetch(self, keyword: str, city: str) -> list[JobPosition]:
        # 1. 先查缓存
        cache_key = self._cache_key("playwright", keyword, city, self.max_per_keyword)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info(f"BOSS Playwright [{keyword}/{city}] 缓存命中，{len(cached)} 个岗位")
            return cached

        city_code = self.CITY_CODES.get(city)
        if not city_code:
            logger.warning(f"BOSS 直聘未配置城市码：{city}，跳过")
            return []

        self._ensure_playwright()

        # 2. 访问搜索页
        url = f"{self.base_url}?query={quote(keyword)}&city={city_code}&page=1"
        logger.info(f"BOSS Playwright 访问: {url}")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            # 等待岗位列表加载
            self._page.wait_for_selector(".job-card-wrapper, .search-job-result li", timeout=15000)
        except Exception as e:
            logger.error(f"BOSS 页面加载失败: {e}")
            return []

        # 3. 滚动加载更多
        for _ in range(3):
            self._page.mouse.wheel(0, 3000)
            self._page.wait_for_timeout(1500)

        # 4. 解析岗位列表
        positions = self._parse_list_page(keyword, city)

        # 翻页（最多 3 页）
        for page_num in range(2, 4):
            if len(positions) >= self.max_per_keyword:
                break
            try:
                # 点击下一页
                next_btn = self._page.query_selector(".ui-pagination li.next:not(.disabled) a")
                if not next_btn:
                    break
                next_btn.click()
                self._page.wait_for_timeout(2000)
                self._page.wait_for_selector(".job-card-wrapper, .search-job-result li", timeout=10000)
                positions.extend(self._parse_list_page(keyword, city))
            except Exception as e:
                logger.debug(f"翻页失败 p{page_num}: {e}")
                break

        # 去重
        seen = set()
        unique = []
        for p in positions:
            key = (p.company, p.title, p.city)
            if key not in seen:
                seen.add(key)
                unique.append(p)
        positions = unique[:self.max_per_keyword]

        # 写缓存
        self._cache_set(cache_key, positions)
        logger.info(f"BOSS Playwright [{keyword}/{city}] 抓取 {len(positions)} 个岗位")
        return positions

    def _parse_list_page(self, keyword: str, city: str) -> list[JobPosition]:
        """从当前页面解析岗位列表"""
        positions = []
        try:
            cards = self._page.query_selector_all(".job-card-wrapper, .search-job-result li.job-card-wrapper")
            for card in cards:
                try:
                    pos = self._parse_card(card, keyword, city)
                    if pos:
                        positions.append(pos)
                except Exception as e:
                    logger.debug(f"卡片解析失败: {e}")
        except Exception as e:
            logger.error(f"列表解析失败: {e}")
        return positions

    def _parse_card(self, card, keyword: str, city: str) -> JobPosition | None:
        """解析单个岗位卡片"""
        try:
            # 职位名
            title_el = card.query_selector(".job-name, .job-title")
            title = title_el.inner_text().strip() if title_el else ""

            # 公司名
            company_el = card.query_selector(".company-name a, .company-info a")
            company = company_el.inner_text().strip() if company_el else ""

            if not title or not company:
                return None

            # 薪资
            salary_el = card.query_selector(".salary, .job-salary")
            salary = salary_el.inner_text().strip() if salary_el else "面议"

            # 详情页链接
            link_el = card.query_selector("a.job-card-left, a[ka='search-list-']")
            apply_link = ""
            if link_el:
                href = link_el.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    apply_link = "https://www.zhipin.com" + href
                else:
                    apply_link = href

            # 标签（经验/学历等）
            info_els = card.query_selector_all(".job-info .tag-list li, .job-card-info li")
            labels = [el.inner_text().strip() for el in info_els if el.inner_text().strip()]

            # HR 活跃度 / 公司规模等
            hr_el = card.query_selector(".hr-info .hr-text, .boss-name")
            hr_text = hr_el.inner_text().strip() if hr_el else ""

            desc_text = f"{title} {' '.join(labels)}".lower()
            has_conversion = any(k in desc_text for k in ["转正", "留用"])

            return JobPosition(
                company=company,
                title=title,
                direction=self._infer_direction(title),
                industry="互联网",
                city=city,
                salary=salary,
                responsibilities="",  # 列表页不含 JD
                requirements="、".join(labels),
                apply_link=apply_link,
                source=self.platform,
                has_conversion=has_conversion,
                target_grad="2027届" if "2027" in desc_text else "",
                notes=" | ".join(labels[:3]),
            )
        except Exception as e:
            logger.debug(f"卡片解析失败: {e}")
            return None

    def close(self):
        """关闭浏览器"""
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def __del__(self):
        self.close()


# ---------- 牛客网（旧 API 已失效，标记 deprecated） ----------

class NowcoderFetcher(BaseFetcher):
    """
    牛客网抓取器 — 已失效

    旧接口 https://www.nowcoder.com/np/cover/intern/search 已 404，
    新页面 /job/center 是 SSR 但翻页/详情触发滑块验证，纯 requests 不可行。
    如需牛客数据，建议用 Selenium/Playwright + 登录态。
    """
    platform = "牛客网"
    base_url = "https://www.nowcoder.com/job/center"

    def fetch(self, keyword: str, city: str) -> list[JobPosition]:
        logger.warning(
            "牛客网旧 API 已失效，新页面触发滑块验证，纯 requests 不可行。"
            "如需牛客数据，建议用 Selenium + 登录态。已跳过。"
        )
        return []


# ---------- 流水线 ----------

@dataclass
class FetcherPipeline:
    """多平台抓取流水线"""
    platforms: list[str]
    timeout: int = 15
    max_per_keyword: int = 30

    FETCHER_MAP = {
        "实习僧": ShixisengFetcher,
        "BOSS直聘": BOSSFetcher,
        "BOSS直聘-Playwright": BOSSPlaywrightFetcher,
        "牛客网": NowcoderFetcher,
    }

    def fetch(
        self,
        keywords: Iterable[str],
        cities: Iterable[str],
    ) -> list[JobPosition]:
        """执行多平台 × 多关键词 × 多城市抓取"""
        all_positions: list[JobPosition] = []
        seen_keys: set[tuple[str, str, str]] = set()

        for platform_name in self.platforms:
            fetcher_cls = self.FETCHER_MAP.get(platform_name)
            if not fetcher_cls:
                logger.warning(f"不支持的平台：{platform_name}")
                continue

            try:
                fetcher = fetcher_cls(
                    timeout=self.timeout,
                    max_per_keyword=self.max_per_keyword,
                )
            except Exception as e:
                logger.error(f"初始化 {platform_name} 抓取器失败: {e}")
                continue

            for keyword in keywords:
                for city in cities:
                    try:
                        positions = fetcher.fetch(keyword, city)
                    except Exception as e:
                        logger.error(f"{platform_name} 抓取异常 [{keyword}/{city}]: {e}")
                        continue

                    for pos in positions:
                        key = (pos.company, pos.title, pos.city)
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        all_positions.append(pos)

        logger.info(
            f"抓取完成：{len(self.platforms)} 个平台，"
            f"共 {len(all_positions)} 个岗位（去重后）"
        )
        return all_positions

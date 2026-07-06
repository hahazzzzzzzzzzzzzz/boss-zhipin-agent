# BOSS直聘求职Agent

专为2027届数据分析实习生打造的BOSS直聘岗位搜索、评分与招呼语生成Agent应用。

## 功能

- **实际岗位抓取**：支持 BOSS直聘 / 牛客网 / 实习僧 三平台抓取，限速 + 反风控
- **匹配度评分**：五维评分（技能/项目/方向/软技能/语义相似度），TF-IDF 轻量语义匹配
- **招呼语生成**：基于岗位 + 简历生成个性化招呼语，LLM + 规则双模式
- **多维度筛选**：按城市、薪资、转正机会等条件过滤
- **结构化输出**：自动生成 Excel 岗位汇总表，含匹配度标注
- **Web UI**：基于 Agent SDK 的现代化 Web 对话界面

## 项目结构

```
boss-zhipin-agent/
├── agent/                    # Python Agent核心
│   ├── __init__.py
│   ├── config.py            # 用户画像与搜索配置
│   ├── models.py            # 数据模型（JobPosition / SearchResult）
│   ├── fetcher.py           # 多平台岗位抓取器（BOSS/牛客/实习僧）
│   ├── matcher.py           # 五维匹配度评分器
│   ├── greeting.py          # 招呼语生成器（LLM + 规则双模式）
│   └── exporter.py          # Excel导出器
├── scripts/                  # CLI脚本
│   ├── boss_search.py       # 搜索入口（实际抓取 / 提示词模式）
│   └── generate_excel.py    # Excel生成
├── server/                   # Express后端
├── src/                      # React前端
├── data/                     # 数据目录
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt   # openpyxl, requests, beautifulsoup4
# 可选（LLM 模式招呼语）
pip install openai
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，关键配置：

```ini
# BOSS直聘抓取 Cookie（实际抓取模式必需）
# 获取方式：浏览器登录 zhipin.com → F12 → Network → 搜 "joblist" → 复制 Cookie
BOSS_COOKIE=...

# CodeBuddy LLM（招呼语 LLM 模式必需）
CODEBUDDY_API_KEY=...
```

### 3. 实际抓取岗位

```bash
# 抓取杭州+深圳 数据分析/策略运营 岗位，自动评分 + 导出 Excel
python scripts/boss_search.py --cities 杭州,深圳 --roles 数据分析,策略运营

# 仅牛客网（无需 Cookie，反爬弱）
python scripts/boss_search.py --platforms 牛客网 --cities 杭州,深圳,北京

# 详细日志
python scripts/boss_search.py -v
```

### 4. 仅生成提示词（无 Cookie 时）

```bash
python scripts/boss_search.py --prompt-only --output data/search_prompt.json
```

### 5. 招呼语生成

```bash
# 对抓取到的岗位批量生成招呼语（LLM 优先，失败回退规则）
python -m agent.greeting data/search_results.json

# 仅用规则模式（不依赖 LLM）
python -m agent.greeting data/search_results.json --mode rule
```

### 6. 匹配度评分（独立运行）

```bash
python -m agent.matcher data/search_results.json --top 20
```

### 7. 启动 Web 应用

```bash
npm run dev
# 前端: http://localhost:5173
# 后端: http://localhost:3001
```

## 模块说明

### fetcher.py — 岗位抓取

| 平台 | 接口 | 反爬难度 | 是否需要登录 |
|------|------|----------|--------------|
| BOSS直聘 | `wapi/zpgeek/search/joblist.json` | 高（需 Cookie + 限速） | 是 |
| 牛客网 | `np/cover/intern/search` | 低 | 否 |
| 实习僧 | SSR HTML 解析 | 中 | 否 |

### matcher.py — 五维匹配度评分

| 维度 | 权重 | 说明 |
|------|------|------|
| 技能匹配 | 35% | 加权关键词（LightGBM/SQL/χ² 等核心技能权重高） |
| 项目匹配 | 25% | 简历项目标签与 JD 文本的命中 |
| 方向匹配 | 15% | 岗位方向与求职目标一致性 |
| 软技能 | 5% | 沟通/团队/学习能力等 |
| 语义相似度 | 20% | TF-IDF + cosine（无需 sentence-transformers） |

### greeting.py — 招呼语生成

- **LLM 模式**：调用 CodeBuddy/OpenAI 兼容接口，按 80-120 字生成自然招呼语
- **规则模式**：内置模板 + 项目匹配，无 LLM 时兜底
- **简历摘要内置**，无需每次解析 PDF

## 技术栈

- **Python**: 3.10+ (openpyxl, requests, beautifulsoup4, openai)
- **前端**: React 18 + TypeScript + TDesign React + Tailwind CSS
- **后端**: Express 4 + CodeBuddy Agent SDK + SSE
- **数据库**: SQLite (better-sqlite3)

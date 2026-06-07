# BOSS直聘求职Agent

专为2027届数据分析实习生打造的BOSS直聘岗位搜索与投递Agent应用。

## 功能

- **智能岗位搜索**：在BOSS直聘、牛客网、实习僧等平台自动搜索数据分析实习岗位
- **多维度筛选**：按城市（杭州/深圳）、薪资、行业、转正机会等条件过滤
- **结构化输出**：自动生成Excel岗位汇总表，含匹配度标注
- **Web UI**：基于Agent SDK的现代化Web对话界面
- **浏览器自动化**：辅助完成在线沟通和简历投递

## 项目结构

```
boss-zhipin-agent/
├── agent/                    # Python Agent核心
│   ├── __init__.py
│   ├── config.py            # 用户画像与搜索配置
│   ├── models.py            # 数据模型
│   └── exporter.py          # Excel导出器
├── scripts/                  # CLI脚本
│   ├── boss_search.py       # 搜索入口
│   └── generate_excel.py    # Excel生成
├── server/                   # Express后端
│   ├── index.ts             # SSE服务器
│   └── db.ts                # SQLite数据库
├── src/                      # React前端
│   ├── App.tsx              # 主应用
│   ├── config.ts            # 应用配置
│   ├── components/          # UI组件
│   ├── hooks/               # React Hooks
│   └── utils/               # 工具函数
├── data/                     # 数据目录
│   ├── search_results.json  # 搜索结果
│   └── *.xlsx               # 岗位汇总表
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
# Python依赖
pip install openpyxl

# Node.js依赖
npm install
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 CODEBUDDY_API_KEY
```

### 3. 启动Web应用

```bash
npm run dev
# 前端: http://localhost:5173
# 后端: http://localhost:3001
```

### 4. 使用搜索脚本

```bash
# 搜索岗位
python scripts/boss_search.py --cities 杭州,深圳 --output data/results.json

# 生成Excel
python scripts/generate_excel.py data/results.json --output data/岗位汇总表.xlsx
```

## 技术栈

- **前端**: React 18 + TypeScript + TDesign React + Tailwind CSS
- **后端**: Express 4 + CodeBuddy Agent SDK + SSE
- **数据库**: SQLite (better-sqlite3)
- **Agent核心**: Python 3.13 + openpyxl

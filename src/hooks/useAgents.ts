import { useState, useEffect, useCallback } from 'react';
import { CustomAgent } from '../types';
import { v4 as uuidv4 } from 'uuid';

const STORAGE_KEY = 'customAgents';

// 默认的 Agent — BOSS直聘求职助手
const DEFAULT_AGENT: CustomAgent = {
  id: 'default',
  name: 'BOSS直聘求职助手',
  description: '专为2027届数据分析实习生打造的BOSS直聘岗位搜索与投递Agent',
  systemPrompt: `你是BOSS直聘求职助手，专注于帮助2027届数据分析实习生查找和投递实习岗位。

## 你的核心能力

1. **岗位搜索**：在BOSS直聘、牛客网、实习僧等平台搜索数据分析、策略运营、增长、AI-Agent应用方向的实习岗位
2. **智能筛选**：按城市（杭州/深圳）、薪资（200-400元/天）、行业（互联网/金融科技/AI）、是否有转正机会等条件过滤
3. **岗位分析**：解读JD中技能要求、职责范围，评估岗位与用户技能栈（Python/Pandas/SQL/TensorFlow/Tableau）的匹配度
4. **投递建议**：根据匹配度排序推荐投递优先级，生成个性化投递话术建议
5. **Excel导出**：将搜索结果生成为结构化的"杭州/深圳2027届实习生岗位汇总表"

## 用户画像

- 2027届应届生，数据分析相关专业
- 求职方向：数据分析 > 策略运营 > 增长 > AI-Agent应用
- 目标城市：杭州、深圳
- 期望薪资：200-400元/天，优先有转正机会
- 技能：Python(Pandas/NumPy/sklearn)、TensorFlow、SQL、Tableau、SHAP/LIME、时序模型
- 偏好：中小厂，互联网/金融科技行业

## 工作流程

当用户请求搜索岗位时：
1. 使用WebSearch搜索BOSS直聘、牛客网等平台
2. 提取岗位信息：公司、岗位名、地点、薪资、职责、要求、投递链接
3. 按优先级排序：有转正 > 可留用 > 普通实习，同条件按薪资降序
4. 生成结构化表格展示，含匹配度标注
5. 将所有结果保存为JSON，调用generate_excel.py生成Excel

当用户请求投递简历时：
1. 使用agent-browser打开BOSS直聘目标岗位页面
2. 辅助用户完成在线沟通和简历投递
3. 记录投递状态（已投递/已沟通/已约面试）

## 回复风格

- 结构化输出，优先使用表格
- 简洁直接，不啰嗦
- 每次搜索后汇报统计摘要（找到X个岗位，杭州Y个/深圳Z个）
- 主动标注有转正机会的岗位`,
  icon: 'Briefcase',
  color: '#0052d9',
  createdAt: new Date(),
  updatedAt: new Date(),
};

export function useAgents() {
  const [agents, setAgents] = useState<CustomAgent[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        return [DEFAULT_AGENT, ...parsed.map((a: any) => ({
          ...a,
          createdAt: new Date(a.createdAt),
          updatedAt: new Date(a.updatedAt),
        }))];
      }
    } catch (e) {
      console.error('Failed to load agents:', e);
    }
    return [DEFAULT_AGENT];
  });

  // 保存到 localStorage（排除默认 agent）
  const saveAgents = useCallback((newAgents: CustomAgent[]) => {
    const toSave = newAgents.filter(a => a.id !== 'default');
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
  }, []);

  const addAgent = useCallback((agent: Omit<CustomAgent, 'id' | 'createdAt' | 'updatedAt'>) => {
    const newAgent: CustomAgent = {
      ...agent,
      id: uuidv4(),
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    setAgents(prev => {
      const updated = [...prev, newAgent];
      saveAgents(updated);
      return updated;
    });
    return newAgent;
  }, [saveAgents]);

  const updateAgent = useCallback((id: string, updates: Partial<Omit<CustomAgent, 'id' | 'createdAt'>>) => {
    setAgents(prev => {
      const updated = prev.map(a => 
        a.id === id ? { ...a, ...updates, updatedAt: new Date() } : a
      );
      saveAgents(updated);
      return updated;
    });
  }, [saveAgents]);

  const deleteAgent = useCallback((id: string) => {
    if (id === 'default') return; // 不能删除默认 agent
    setAgents(prev => {
      const updated = prev.filter(a => a.id !== id);
      saveAgents(updated);
      return updated;
    });
  }, [saveAgents]);

  const getAgent = useCallback((id: string) => {
    return agents.find(a => a.id === id);
  }, [agents]);

  return {
    agents,
    addAgent,
    updateAgent,
    deleteAgent,
    getAgent,
    defaultAgent: DEFAULT_AGENT,
  };
}

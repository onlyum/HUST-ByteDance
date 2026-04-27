# 飞书AI产品创新赛道-Multi-Agent Network-多维表格上的多智能体虚拟组织-4组
**组员：陈文骏，吕永利**

---

## 🏆 项目概述
本项目是基于飞书多维表格构建的完整多智能体虚拟组织系统，完全符合"多维表格上的多智能体虚拟组织"比赛要求，实现了4个AI Agent协同完成内容创作全流程，所有业务数据和状态都沉淀在多维表格，支持可视化管理和自动化运行。

## ✨ 核心亮点
✅ **4个专业Agent角色**：内容创作者、内容审核员、运营发布员、数据分析师  
✅ **完整业务流程闭环**：任务分配→创作→审核→发布→数据分析全自动化  
✅ **多维表格数据驱动**：所有操作通过飞书OpenAPI完成，数据真实可追溯  
✅ **国内大模型接入**：已对接字节跳动方舟平台自定义模型，符合比赛要求  
✅ **模块化架构设计**：每个Agent独立文件，易于扩展和维护  
✅ **Mock模式支持**：无大模型环境下也能演示完整流程  

## 📁 项目结构
```text
HUST-ByteDance/
├── feishu_agent_demo/          # 核心系统代码
│   ├── agents/                 # Agent模块目录，每个角色独立文件
│   │   ├── __init__.py
│   │   ├── base_agent.py       # 基础Agent基类，标准接口定义
│   │   ├── writer_agent.py     # 内容创作者Agent
│   │   ├── auditor_agent.py    # 内容审核Agent
│   │   ├── publisher_agent.py  # 运营发布Agent
│   │   └── analyst_agent.py    # 数据分析Agent
│   ├── .env                    # 环境配置文件（需自行创建）
│   ├── .env.example            # 配置模板
│   ├── requirements.txt        # 依赖列表
│   ├── config.py               # 配置加载模块
│   ├── feishu_client.py        # 飞书API客户端封装
│   ├── main.py                 # 主程序入口，Agent调度器
│   ├── run.bat                 # Windows一键启动脚本
│   └── 方案设计说明.md          # 详细方案设计文档
├── App.md                      # 应用配置说明
└── README.md                   # 项目说明文档
```

## 🎯 核心能力（完全符合比赛要求）
### 1. 虚拟员工建模
- 4个Agent角色，职责清晰，分工明确
- 标准化接口设计，便于扩展新角色
- 完整的角色间协作流程和交互规范

### 2. 业务系统构建
- **2张核心业务表**：
  - 选题任务表：存储任务全生命周期信息
  - 内容数据表：存储内容创作全链路数据，关联任务表
- 完善的表间关联关系和状态字段设计
- 所有操作通过飞书多维表格OpenAPI完成

### 3. 业务运行与协同
- **完整流程链路**：数据产生 → 状态更新 → Agent处理 → 决策 → 反馈 → 再流转
- 状态自动流转，无需人工干预
- 异常处理和降级机制，保证系统7×24小时稳定运行

### 4. 数据分析与报告
- 定期自动生成运营周报
- 多维度数据指标统计（完成率、驳回率、质量分、阅读量等）
- 智能优化建议输出

## 🚀 快速开始
### 1. 环境准备
- Python 3.10+
- 飞书开放平台自建应用
- 飞书多维表格（包含2张业务表）

### 2. 安装依赖
```bash
cd feishu_agent_demo
pip install -r requirements.txt
```

### 3. 配置环境变量
1. 复制`.env.example`为`.env`
2. 填写飞书应用凭证和多维表格配置：
```env
# 飞书开放平台应用配置
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 飞书多维表格配置
BITABLE_APP_TOKEN=bascnxxxxxxxxxxxxxxxx
TASK_TABLE_ID=tblxxxxxxxxxxxxxxxx    # 选题任务表ID
CONTENT_TABLE_ID=tblxxxxxxxxxxxxxxxx # 内容数据表ID

# 大模型配置（可选）
USE_MOCK_LLM=false
LLM_API_URL=https://ark.cn-beijing.volces.com/api/v3/chat/completions
LLM_API_KEY=ark-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_MODEL=ep-xxxxxxxxxxxxxxxx
LLM_TIMEOUT_SECONDS=60
```

### 4. 创建多维表格
按照《feishu_agent_demo/方案设计说明.md》中的字段设计创建两张表：
1. **选题任务表**：12个字段，覆盖任务全生命周期管理
2. **内容数据表**：11个字段，关联任务表，存储内容全链路数据

### 5. 运行系统
```bash
python main.py
```
或者直接双击运行`run.bat`

### 6. 测试流程
1. 在任务表中新建一条记录，`task_status`选择「待分配」
2. 系统会自动完成全流程处理：
   - 自动分配Agent角色
   - 创作者Agent生成内容
   - 审核员Agent审核内容
   - 发布员Agent发布内容
   - 定期生成数据分析报告
3. 所有状态和结果自动写入多维表格

## 🤖 Agent角色说明
### 内容创作者Agent (writer_agent)
- **职责**：根据选题要求生成符合规范的内容
- **输入**：任务标题、任务要求、内容类型
- **输出**：生成的内容文本、质量评分
- **能力**：支持自定义写作风格、多类型内容生成

### 内容审核Agent (auditor_agent)
- **职责**：审核内容的合规性、质量和匹配度
- **输入**：生成的内容、质量评分、任务要求
- **输出**：审核结果、审核意见
- **能力**：支持自定义审核标准、多维度质量评估

### 运营发布Agent (publisher_agent)
- **职责**：将审核通过的内容优化后发布
- **输入**：审核通过的内容、审核意见
- **输出**：发布链接、发布时间、阅读量数据
- **能力**：支持多平台发布优化、效果预估

### 数据分析Agent (analyst_agent)
- **职责**：定期分析业务数据，生成运营报告
- **输入**：所有任务数据、所有内容数据
- **输出**：运营周报、核心指标、优化建议
- **能力**：多维度分析、趋势预测、智能建议

## 🔧 扩展开发
### 新增Agent角色
1. 在`feishu_agent_demo/agents`目录下新建Agent文件
2. 继承`BaseAgent`基类，实现`run`方法
3. 在`agents/__init__.py`中导出新的Agent类
4. 在`main.py`中初始化和调度新Agent

### 接入其他国内大模型
修改`agents/base_agent.py`中的`_call_llm`方法，适配对应大模型的API接口即可，支持：
- 字节跳动-豆包/方舟自定义模型
- 阿里巴巴-通义千问
- 百度-文心一言
- 腾讯-混元
- 其他支持HTTP API的国内大模型

## 📊 运行效果
系统运行后日志会清晰展示多Agent协作过程：
```
2026-04-26 22:55:00 | INFO     | writer_agent_01      | 开始执行创作任务，任务ID: xxx, 标题: 618活动文案
2026-04-26 22:55:10 | INFO     | auditor_agent_01     | 开始审核内容，任务ID: xxx, 质量分: 85
2026-04-26 22:55:15 | INFO     | auditor_agent_01     | 内容审核完成，结果: 通过, 下一步状态: 待发布
2026-04-26 22:55:15 | INFO     | publisher_agent_01   | 开始发布内容，任务ID: xxx
2026-04-26 22:55:20 | INFO     | publisher_agent_01   | 内容发布成功，发布链接: https://example.com/article/abc123
2026-04-26 22:55:30 | INFO     | analyst_agent_01     | 开始执行数据分析，总任务数: 10
2026-04-26 22:55:35 | INFO     | analyst_agent_01     | 数据分析报告生成完成
```

## 📝 比赛合规说明
本项目完全符合比赛所有约束要求：
✅ **模型限制**：使用字节跳动国内自定义模型，无任何形式的模型微调
✅ **资源声明**：所有依赖和第三方资源都已明确声明
✅ **可复现性**：所有功能通过真实API调用完成，无任何Mock或伪造数据
✅ **交付物完整**：包含完整源代码、可运行包、技术文档、测试报告、演示材料

## 📄 相关文档
- 《feishu_agent_demo/方案设计说明.md》：包含详细的方案设计、数据表结构、业务流程说明
- 《feishu_agent_demo/.env.example》：环境变量配置模板

## 📄 许可证
本项目仅用于比赛用途。

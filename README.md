# 飞书多维表格采购多Agent虚拟组织系统
**组员：陈文骏，吕永利**

---

## 项目概述
本项目基于飞书多维表格构建采购场景的多 Agent 虚拟组织。系统通过 4 个 Agent 协同完成需求解析、供应商选型、下单与物流追踪、效能分析，所有过程数据与操作日志都沉淀在 Bitable 中，可追溯、可审计、可扩展。

## 核心亮点
- 4 个采购角色 Agent：`Planner`、`SourcingAuditor`、`Tracker`、`Strategy`
- 4 张业务表联动：`Demands`、`Suppliers`、`Orders`、`Audit_Logs`
- 状态触发编排：按记录状态自动驱动流程，不依赖手工串行操作
- 通用飞书工具箱：`requests` 版鉴权、CRUD、429 退避重试、Link 字段适配
- 全链路审计：所有关键动作落库到 `Audit_Logs`

## 项目结构
```text
HUST-ByteDance/
├── feishu_agent_demo/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py           # Agent基类：LLM调用、跨表聚合、审计日志
│   │   ├── planner_agent.py        # 需求规划员
│   │   ├── sourcing_auditor.py     # 选型审计官
│   │   ├── tracker_agent.py        # 物流追踪员
│   │   └── strategy_agent.py       # 采购策略分析师
│   ├── script/
│   │   ├── sqlinit.py              # 按schema创建字段
│   │   ├── inject_mock_data.py     # 注入供应商/需求/日志测试数据
│   │   └── clean_demands.py        # 清理需求表，仅保留目标样例
│   ├── .env                        # 本地配置（不要提交）
│   ├── .env.example
│   ├── requirements.txt
│   ├── config.py                   # 状态、表ID、字段映射、配置加载
│   ├── feishu_bitable_toolbox.py   # 飞书多维表格通用封装
│   ├── main.py                     # 编排器入口
│   └── 方案设计说明.md
├── App.md
└── README.md
```

## 业务流程（状态触发）
1. `Demands.status = 待规划`：触发 `PlannerAgent`
2. `Demands.status = 已选型`：触发 `SourcingAuditorAgent`
3. `Orders.logistics_status in (待发货, 运输中, 异常)`：触发 `TrackerAgent`
4. 定时触发 `StrategyAgent`：生成采购效能与风险摘要

## 快速开始

### 1) 环境准备
- Python 3.10+
- 飞书开放平台自建应用（具备多维表格读写权限）
- 飞书多维表格 Base（含 `Demands/Suppliers/Orders/Audit_Logs` 四张表）

### 2) 安装依赖
```bash
cd feishu_agent_demo
pip install -r requirements.txt
```

### 3) 配置 `.env`
复制 `feishu_agent_demo/.env.example` 为 `.env`，至少填写：
```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
BITABLE_APP_TOKEN=xxx
POLL_INTERVAL_SECONDS=10
```

可选字段（建议保持默认）：
- `DEMAND_FIELD_STATUS=status`
- `DEMAND_FIELD_RECOMMENDED_SUPPLIERS=recommended_suppliers`
- `DEMAND_FIELD_CATEGORY=category`
- `ORDER_FIELD_LOGISTICS_STATUS=logistics_status`

### 4) 初始化与测试
```bash
# 1. 创建字段（按 script/sqlinit.py 内 schema）
python script/sqlinit.py

# 2. 注入 mock 数据
python script/inject_mock_data.py

# 3. （可选）清理需求表，仅保留 DEM-20260426-01
python script/clean_demands.py

# 4. 启动编排器
python main.py
```

## Agent 说明

### PlannerAgent
- 输入：`Demands.source_instruction`
- 输出：推进需求状态到 `已选型`，并写审计日志

### SourcingAuditorAgent
- 输入：需求记录
- 决策：优先用 `recommended_suppliers`；为空时按 `category` 匹配 `Suppliers.main_business`（多选包含逻辑）
- 输出：创建订单并推进需求状态到 `已下单`

### TrackerAgent
- 输入：`Orders.logistics_status`
- 输出：物流状态更新与异常重试计数；避免“异常 -> 异常”无限循环

### StrategyAgent
- 输入：全量需求与订单
- 输出：采购 KPI 与风险摘要日志

## 运行排障
- `FieldNameNotFound`：表字段名与脚本字段不一致，优先检查 `sqlinit.py` 是否成功执行
- `LinkFieldConvFail`：关联字段值格式错误，Link 字段应传 `record_id` 字符串数组
- `candidate_count=0`：需求无推荐供应商且按 `category -> main_business` 未命中

## 相关文档
- `feishu_agent_demo/方案设计说明.md`
- `feishu_agent_demo/.env.example`

## 许可证
本项目仅用于比赛与教学演示。

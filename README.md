# 飞书多维表格采购多 Agent 虚拟组织系统

**组员：陈文骏，吕永利**

---

## 项目概述

本项目基于**飞书多维表格（Bitable）**与**飞书开放平台**能力，搭建采购场景下的多 Agent 协同演示系统：需求结构化、寻源辩论与审批、订单与物流跟单、策略看板与审计日志均在表中沉淀，便于追溯与扩展。

运行时由 **`main.py`** 同时拉起：

- **编排轮询**：按 `Demands` / `Orders` 状态触发各 Agent；
- **飞书长连接（WebSocket）**：接收机器人私聊/群聊消息，完成 IM 建单、查询与「触发审批」等指令。

---

## 功能特性

| 能力 | 说明 |
|------|------|
| 多 Agent | **Planner**（需求）、**SourcingAuditor**（寻源辩论 + 审批卡片）、**Tracker**（物流跟单）、**Strategy**（定期 KPI） |
| 数据底座 | **Demands / Suppliers / Orders / Audit_Logs** 四表联动；可选 **Personnel、Debate_History、Business_Rules、Interaction_Memory** |
| 编排模式 | 状态触发型轮询，默认间隔见 `POLL_INTERVAL_SECONDS` |
| IM 入口 | 意图路由（采购申请 / 查询 / 闲聊）、自然语言建单、业务化回复（单号仅展示 `demand_code`） |
| 审批链 | `MULTI_STAGE_APPROVAL`：主管 → 采购对接 → 运输 → 卡片回调建 **Orders**；关闭则为单卡「待审批」 |
| 自动寻源 | `AUTO_RUN_AUDIT_DEBATE=true` 时，编排器每轮最多自动处理 1 条「待辩论」，等价于后台触发辩论与挂起审批 |
| 物流跟单 | **不接真实承运商**；按编排周期更新 `logistics_status`；**异常** 时审计 + 关联需求 `notes` 上报 |
| 工具层 | `feishu_bitable_toolbox`：租户令牌、CRUD、429 退避、Link 字段等 |

更细的设计与表结构见 **`feishu_agent_demo/方案设计说明.md`**。

---

## 仓库结构

```text
HUST-ByteDance-1.2/
├── README.md                      # 本说明
├── App.md                         # （若存在）补充材料，默认不入库时可忽略
├── feishu_agent_demo/
│   ├── main.py                    # 入口：编排循环 + WS 线程
│   ├── config.py                  # 状态枚举、表 ID、字段映射、load_settings
│   ├── feishu_bitable_toolbox.py  # 多维表格 API 封装
│   ├── feishu_client_ws.py        # 飞书 WS 事件、卡片回调、建单等
│   ├── feishu_ws_card_patch.py  # 卡片/交互相关补丁
│   ├── handler/
│   │   └── bot_handler.py         # IM 消息：意图分类、建单、查询、触发审批
│   ├── agents/
│   │   ├── base_agent.py
│   │   ├── planner_agent.py
│   │   ├── sourcing_auditor.py
│   │   ├── tracker_agent.py
│   │   └── strategy_agent.py
│   ├── script/
│   │   ├── sqlinit.py             # 按 schema 创建/对齐字段（新环境建议先跑）
│   │   ├── inject_mock_data.py    # 演示数据
│   │   ├── inject_personnel_mock.py
│   │   ├── clean_demands.py
│   │   └── …                      # 其它辅助脚本
│   ├── tests/
│   ├── .env.example               # 环境变量模板（勿提交真实密钥）
│   ├── requirements.txt
│   ├── 方案设计说明.md
│   └── 运行.bat                   # Windows 快捷启动（可选）
└── .gitignore
```

**请勿将 `feishu_agent_demo/.env` 提交到 Git**（根目录 `.gitignore` 已忽略 `.env`）。

---

## 业务流程（与实现对齐）

1. **PR（需求）**  
   - 表内：`待规划` → **PlannerAgent.run** → 预算等业务规则预审通过后 → **`待辩论`**。  
   - IM：**BotHandler** 调用 **PlannerAgent.parse_and_create** 写入 `Demands`，初始多为 **`待规划`**，随后由编排器同上推进。

2. **寻源与审批**  
   - **`待辩论`** → **SourcingAuditorAgent.run_audit_debate**（由 `AUTO_RUN_AUDIT_DEBATE` 自动排队，或用户发送 **`触发审批` + 需求编号 `DEM-…`**）→ 写辩论/推荐、状态进入审批链。  
   - **多阶段**：`待主管审批` → `待采购确认` → `待运输审批` → 最后一环通过后 **WS 回调创建 Orders**。  
   - **单阶段**：一张「待审批」卡片，通过后建单（行为以 `feishu_client_ws` 与配置为准）。

3. **PO + 物流**  
   - **TrackerAgent** 对 `待发货` / `运输中` / `异常` 订单做表内跟单；异常时落审计并写关联需求备注。

4. **看板**  
   - **StrategyAgent** 按间隔（代码内约 12 小时）扫描需求与订单，写摘要类日志。

`Demands.status` 等单选值需与 **`config.BusinessStatus`** 及 **`script/sqlinit.py`** 中选项一致；新 Base 请先跑 **`sqlinit.py`** 或手工对齐选项。

---

## 环境要求

- **Python 3.10+**
- 飞书**自建应用**：开启机器人、IM、多维表格等所需权限（以开放平台文档为准）
- 飞书**多维表格**：至少包含 Demands / Suppliers / Orders / Audit_Logs；多阶段审批需 **Personnel** 等扩展表时，在 `.env` 中配置对应 `TABLE_ID_*`

---

## 快速开始

### 1. 安装依赖

```bash
cd feishu_agent_demo
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
copy .env.example .env
# 或: cp .env.example .env
```

在 **`.env`** 中至少填写（详见 **`.env.example` 注释**）：

- `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
- `BITABLE_APP_TOKEN`
- `TABLE_ID_DEMANDS` / `TABLE_ID_SUPPLIERS` / `TABLE_ID_ORDERS` / `TABLE_ID_LOGS`
- `POLL_INTERVAL_SECONDS`（默认 10）
- 按需：`AUTO_RUN_AUDIT_DEBATE`、`MULTI_STAGE_APPROVAL`、`USE_MOCK_LLM`、LLM URL/Key、`TABLE_ID_PERSONNEL` 等

### 3. 初始化表字段与演示数据（推荐）

```bash
cd feishu_agent_demo
python script/sqlinit.py
python script/inject_mock_data.py
# 多阶段审批演示可配合 Personnel：
# python script/inject_personnel_mock.py
```

### 4. 启动

```bash
python main.py
```

- 主线程：编排轮询。  
- 子线程：飞书 WebSocket（需应用具备事件订阅与网络连通）。

Windows 也可使用项目内 **`运行.bat`**（若已配置好 Python 路径与目录）。

---

## 常用操作说明

| 场景 | 操作 |
|------|------|
| IM 提交采购申请 | 私聊/群内发送自然语言需求（系统会分类为「采购申请」并建单） |
| 手动推进辩论/审批 | 发送 `触发审批 DEM-xxxxxxxx` 或仅发送一行需求编号（与 `BotHandler` 解析规则一致） |
| 关闭自动辩论 | `.env` 设置 `AUTO_RUN_AUDIT_DEBATE=false`，仅靠 IM「触发审批」启动 |
| 多阶段审批 | `MULTI_STAGE_APPROVAL=true`，并在 **Personnel** 中配置各环节飞书 `open_id` |

---

## Agent 与核心模块（摘要）

| 模块 | 职责 |
|------|------|
| **PlannerAgent** | 表内：`待规划` → 解析指令 → `待辩论`（含 Business_Rules 预算预审等）。IM：`parse_and_create` 建需求。 |
| **SourcingAuditorAgent** | 寻源辩论、推荐供应商、推送/重发审批卡片；与 WS 卡片回调协同建单。 |
| **TrackerAgent** | 订单物流状态跟单；异常上报（审计 + 需求 `notes`）。 |
| **StrategyAgent** | 定期 KPI / 风险摘要。 |
| **FeishuWebSocketClient** | 接收消息、卡片交互、写表与发 IM。 |
| **FeishuBitableToolbox** | 令牌、记录 CRUD、筛选迭代等。 |

---

## 运行排障

- **LLM 超时 / 辩论失败**：提高 `.env` 中 `LLM_TIMEOUT_SECONDS`、`LLM_CONNECT_TIMEOUT_SECONDS`；失败时审计中常有降级说明（如按信用分选型）。  
- **`FieldNameNotFound` / 单选不匹配**：确认已执行 **`script/sqlinit.py`** 且列名与 **`config` / `.env` 字段映射** 一致。  
- **卡片收不到 / 无按钮**：检查机器人 IM 权限、用户是否曾与机器人单聊、开放平台事件订阅与 **`feishu_client_ws`** 日志。  
- **`candidate_count=0`**：需求无推荐供应商且按品类未匹配到 `Suppliers`。  
- **WS 连不上**：检查企业网络、应用长连接地址与订阅事件是否启用。

---

## 相关文档

- **`feishu_agent_demo/方案设计说明.md`** — 表结构、五阶段映射、流程简图  
- **`feishu_agent_demo/.env.example`** — 全部可配置项说明  
- **`feishu_agent_demo/tests/采购流程测试用例.md`** — 测试要点  

---

## 许可证

本项目仅用于比赛与教学演示。

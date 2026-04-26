# 飞书多维表格 Agent Demo

这是一个基于飞书多维表格（Base）与飞书开放平台 API 构建的本地可运行 Agent 引擎 Demo，用于演示“外部 Python 大脑”如何轮询任务、调用智能体处理，并将结果写回多维表格。

## 1. 项目简介

这个项目适合以下场景：

- 参加“飞书多维表格 + AI Agent / Multi-Agent”类比赛时，快速搭一个能演示完整闭环的原型系统。
- 把飞书多维表格当作“任务面板”或“组织控制台”，由 Python 程序在本地或服务器上持续消费任务。
- 未来把 Demo 扩展成真正的“虚拟组织”，例如文案 Agent、审核 Agent、排期 Agent、数据分析 Agent 协同工作。

当前 Demo 实现的能力包括：

- 使用 `.env` 安全读取飞书应用凭证与多维表格参数。
- 使用官方 `lark-oapi` SDK 自动完成飞书 API 鉴权。
- 定时轮询多维表格中“状态 = 待处理”的记录。
- 调用一个简单的 `ContentWriterAgent` 执行任务。
- 将处理结果写回多维表格，并把状态更新为 `处理中` / `待审核` / `处理失败`。
- 预留未来接入真实大模型 API 的清晰扩展位置。

## 2. 目录结构

项目目录如下：

```text
feishu_agent_demo/
├── .env.example
├── requirements.txt
├── config.py
├── feishu_client.py
├── agent_logic.py
├── main.py
└── README.md
```

每个文件职责如下：

- `.env.example`：环境变量模板，告诉你需要配置哪些参数。
- `requirements.txt`：项目依赖列表。
- `config.py`：负责读取 `.env`、校验配置、生成 `Settings` 对象。
- `feishu_client.py`：负责初始化飞书 SDK，并封装“查记录 / 更新记录”方法。
- `agent_logic.py`：负责模拟 Agent 的工作过程，并预留真实大模型调用位置。
- `main.py`：负责轮询调度、日志输出、异常处理、串联整个流程。
- `README.md`：项目说明文档。

## 3. 环境准备

### 3.1 Python 版本

本项目要求：

- Python 3.10 或更高版本

你可以在终端中执行以下命令确认版本：

```bash
python --version
```

如果输出类似如下，即可继续：

```text
Python 3.10.x
```

### 3.2 安装 Python

如果你的电脑还没有安装 Python，可以按以下方式准备：

1. 打开 Python 官网：[https://www.python.org/downloads/](https://www.python.org/downloads/)
2. 下载 Python 3.10+ 安装包
3. 安装时勾选 “Add Python to PATH”
4. 安装完成后重新打开终端，执行：

```bash
python --version
```

### 3.3 创建虚拟环境（强烈推荐）

为了避免不同项目之间的依赖冲突，建议使用 `venv`。

在项目目录 `feishu_agent_demo` 下执行：

```bash
python -m venv .venv
```

#### Windows PowerShell 激活方式

```powershell
.\.venv\Scripts\Activate.ps1
```

#### Windows CMD 激活方式

```bat
.\.venv\Scripts\activate.bat
```

#### macOS / Linux 激活方式

```bash
source .venv/bin/activate
```

激活后，终端前面通常会出现类似 `(.venv)` 的前缀。

## 4. 依赖安装

进入项目目录后，执行：

```bash
pip install -r requirements.txt
```

本项目主要依赖如下：

- `lark-oapi`：飞书官方开放平台 Python SDK
- `python-dotenv`：从 `.env` 文件读取配置
- `requests`：预留用于调用外部大模型 HTTP API

## 5. 飞书应用配置指南

这一部分非常关键。这个 Demo 想跑起来，必须先在飞书开放平台创建一个应用，并拿到 `App ID` 和 `App Secret`。

### 5.1 创建飞书开放平台应用

1. 打开飞书开放平台：[https://open.feishu.cn/](https://open.feishu.cn/)
2. 登录你的飞书账号
3. 进入“开发者后台”
4. 选择“创建企业自建应用”
5. 填写应用名称、应用描述、图标等信息
6. 创建成功后，进入应用详情页

### 5.2 获取 App ID 和 App Secret

进入应用详情页后，一般可以在“凭证与基础信息”或类似名称的页面找到：

- `App ID`
- `App Secret`

将它们填入你的 `.env` 文件中：

```env
FEISHU_APP_ID=你的_App_ID
FEISHU_APP_SECRET=你的_App_Secret
```

如果你当前工作区里已经有一个 `App.md` 文件记录了这两个值，可以只把它们复制进 `.env`，不要继续把明文密钥保存在普通文档中，更不要提交到公共仓库。

### 5.3 配置应用权限

进入应用后台的“权限管理”页面，为你的应用申请多维表格相关权限。

不同版本的飞书开放平台界面、不同租户类型、不同 API 版本中，权限名称可能会有细微差别，但思路是一致的：你的应用必须拥有“读取多维表格记录”和“写入多维表格记录”的能力。

你应至少关注以下这类权限：

- `bitable:app:read`
- `bitable:app:write`

在某些控制台界面中，也可能出现：

- `bitable:app`
- Base / Bitable 相关的“读记录”“写记录”“读取表格结构”等更细粒度权限

如果你看到的名称和本文不完全一致，请优先选择“多维表格 / Base / Bitable 的读写权限”，核心目标是不变的：

- 可以读取记录
- 可以更新记录

建议顺手检查是否还需要以下能力：

- 查看应用是否已安装到当前企业或团队
- 权限是否已提交审核并通过
- 目标多维表格是否允许当前应用访问

### 5.4 应用可用范围与安装

有些情况下，即使权限已经勾选，应用仍然无法访问目标多维表格，常见原因包括：

- 应用还没有安装到当前企业
- 权限还没有生效
- 多维表格没有共享给对应应用或当前租户

建议你逐项确认：

1. 应用已经在当前飞书组织内可用
2. 权限申请已经通过
3. 目标多维表格就在这个组织下
4. 已在目标 Base 中通过“左上角 ... -> 更多 -> 添加文档应用”把该应用加进来
5. 添加时授予了“可编辑”权限，而不是只读权限

如果接口返回权限不足、找不到记录或 token 无效，优先从这几个点排查。

## 6. 多维表格准备

### 6.1 创建测试用多维表格

为了测试这个 Demo，你需要先在飞书中新建一个多维表格（Base）。

建议新建一个用于比赛演示的 Base，例如：

- Base 名称：`Agent 任务中心`
- 表名称：`内容生产任务`

### 6.2 建议字段设计

最少准备以下字段：

| 字段名 | 类型 | 示例值 | 说明 |
| --- | --- | --- | --- |
| `任务标题` | 单行文本 | 春季活动宣传文案 | Agent 生成内容的主题 |
| `状态` | 单选 | 待处理 | 用于驱动自动化流程 |
| `输出结果` | 多行文本 | （留空） | 用于写回 Agent 处理结果 |

为了更方便调试，建议把 `状态` 字段的选项预先建好：

- `待处理`
- `处理中`
- `待审核`
- `处理失败`

### 6.3 推荐扩展字段（可选）

虽然本 Demo 最小只需要三个字段，但如果你想在比赛中展示得更完整，建议额外加一些字段，例如：

| 字段名 | 类型 | 用途 |
| --- | --- | --- |
| `任务说明` | 多行文本 | 补充背景信息 |
| `目标受众` | 单行文本 | 指定文案面向的人群 |
| `风格要求` | 单选 | 正式 / 活泼 / 专业 / 极简 |
| `创建时间` | 系统字段 | 方便演示任务生命周期 |
| `负责人` | 人员字段 | 模拟组织分工 |

后续如果你新增这些字段，只需要修改 `agent_logic.py` 中的提示词构造逻辑即可。

### 6.4 获取 BITABLE_APP_TOKEN

打开你的多维表格页面后，浏览器地址栏通常会类似这样：

```text
https://xxx.feishu.cn/base/bascnxxxxxxxxxxxxxx?table=tblxxxxxxxxxxxxxx
```

这里通常可以提取出两个关键值：

- Base Token / App Token：`bascnxxxxxxxxxxxxxx`
- Table ID：`tblxxxxxxxxxxxxxx`

然后填入 `.env`：

```env
BITABLE_APP_TOKEN=bascnxxxxxxxxxxxxxx
TABLE_ID=tblxxxxxxxxxxxxxx
```

注意：

- 有些场景下你看到的 token 前缀可能不是 `bascn`，以实际页面为准。
- 不要把整个 URL 填进去，只填 token 和 table_id。

## 7. 配置 .env 文件

### 7.1 从模板复制

在项目目录下，将 `.env.example` 复制为 `.env`。

#### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

#### macOS / Linux

```bash
cp .env.example .env
```

### 7.2 填写示例

把 `.env` 改成如下格式：

```env
FEISHU_APP_ID=你的_App_ID
FEISHU_APP_SECRET=你的_App_Secret
BITABLE_APP_TOKEN=你的_Bitable_App_Token
TABLE_ID=你的_Table_ID

POLL_INTERVAL_SECONDS=10

TITLE_FIELD_NAME=任务标题
STATUS_FIELD_NAME=状态
OUTPUT_FIELD_NAME=输出结果

PENDING_STATUS=待处理
PROCESSING_STATUS=处理中
REVIEW_STATUS=待审核
FAILED_STATUS=处理失败

USE_MOCK_LLM=true
LLM_API_URL=
LLM_API_KEY=
LLM_MODEL=mock-model
LLM_TIMEOUT_SECONDS=30
```

### 7.3 关键字段说明

- `FEISHU_APP_ID`：飞书开放平台应用 ID
- `FEISHU_APP_SECRET`：飞书开放平台应用密钥
- `BITABLE_APP_TOKEN`：多维表格的 Base Token
- `TABLE_ID`：要操作的数据表 ID
- `POLL_INTERVAL_SECONDS`：轮询间隔，默认 10 秒
- `TITLE_FIELD_NAME`：任务标题字段名
- `STATUS_FIELD_NAME`：状态字段名
- `OUTPUT_FIELD_NAME`：输出结果字段名
- `USE_MOCK_LLM`：是否启用本地 Mock 模型
- `LLM_API_URL`：真实模型接口地址
- `LLM_API_KEY`：真实模型密钥
- `LLM_MODEL`：真实模型名称

## 8. 运行说明

### 8.1 启动程序

在项目目录中执行：

```bash
python main.py
```

### 8.2 程序运行流程

程序启动后会持续循环执行以下步骤：

1. 读取 `.env` 配置
2. 初始化飞书 SDK Client
3. 每 10 秒轮询一次多维表格
4. 只拉取 `状态 = 待处理` 的记录
5. 将该记录状态改为 `处理中`
6. 调用 `ContentWriterAgent` 生成模拟文案
7. 将输出内容写入 `输出结果`
8. 将状态更新为 `待审核`

如果处理失败，则程序会尝试把状态写成 `处理失败`，并将错误信息回填到 `输出结果` 字段中。

### 8.3 典型控制台日志

正常情况下，你会看到类似日志：

```text
2026-04-25 21:30:00 | INFO | Main | 飞书多维表格 Agent Demo 已启动。
2026-04-25 21:30:00 | INFO | Main | 开始新一轮任务轮询。
2026-04-25 21:30:01 | INFO | FeishuBitableClient | 待处理任务拉取完成，共获取到 1 条记录。
2026-04-25 21:30:01 | INFO | TaskProcessor | 开始处理记录，record_id=recxxxxx，title=春季活动宣传文案
2026-04-25 21:30:03 | INFO | TaskProcessor | 记录处理完成，record_id=recxxxxx，title=春季活动宣传文案
2026-04-25 21:30:03 | INFO | Main | 休眠 10 秒后进入下一轮。
```

### 8.4 停止程序

在终端按：

```text
Ctrl + C
```

程序会捕获 `KeyboardInterrupt` 并安全退出。

## 9. 核心代码逻辑说明

### 9.1 `config.py`

职责：

- 加载 `.env`
- 校验必填项
- 统一输出 `Settings`

好处：

- 主程序不再散落 `os.getenv`
- 配置集中管理
- 更适合后期扩展

### 9.2 `feishu_client.py`

职责：

- 初始化飞书官方 SDK
- 查询待处理任务
- 更新记录状态与输出结果

这里使用的是飞书官方 `lark-oapi`，并通过：

```python
lark.Client.builder().app_id(...).app_secret(...).build()
```

来创建客户端。SDK 会自动处理 `tenant_access_token`，因此你不需要自己手写鉴权请求。

### 9.3 `agent_logic.py`

职责：

- 扮演一个“内容写作虚拟员工”
- 接收任务字典
- 生成结果文本

当前默认逻辑是：

- 读取任务标题
- 等待 2 秒模拟推理耗时
- 返回一段拼接好的演示文案

如果你后面要接入真实大模型，请重点修改：

- `_call_real_llm_api()`
- `_extract_content_from_response()`
- `_build_prompt()`

### 9.4 `main.py`

职责：

- 定时轮询
- 串联飞书客户端与 Agent
- 输出日志
- 捕获异常

整个程序最重要的流程在这里：

```text
待处理 -> 处理中 -> 待审核
```

这就是一个最简版的 Agent 工作流。

## 10. 如何接入真实大模型

当前项目默认开启：

```env
USE_MOCK_LLM=true
```

如果你想切换到真实模型：

1. 把 `.env` 改为：

```env
USE_MOCK_LLM=false
LLM_API_URL=你的模型接口地址
LLM_API_KEY=你的模型密钥
LLM_MODEL=你的模型名
```

2. 打开 `agent_logic.py`
3. 修改 `_call_real_llm_api()` 中的请求头和请求体
4. 按你的模型厂商返回格式修改 `_extract_content_from_response()`

### 10.1 适合替换的国内模型方向

你后续可以把这里替换为：

- 智谱 GLM
- DeepSeek
- 通义千问
- Kimi
- 其他支持 HTTP API 的国内大模型服务

## 11. 常见问题排查

### 11.1 缺少环境变量

现象：

- 程序启动立即报错
- 提示缺少 `FEISHU_APP_ID` 或 `TABLE_ID`

排查：

- 是否已经创建 `.env`
- `.env` 是否放在 `feishu_agent_demo` 根目录
- 变量名是否拼写正确

### 11.2 飞书接口提示权限不足

现象：

- SDK 返回权限错误
- 无法读取或写入多维表格

排查：

- 应用是否已经添加多维表格读写权限
- 权限是否已生效
- 应用是否安装到对应组织
- 目标 Base 是否在当前应用可访问范围内

### 11.3 获取不到待处理记录

现象：

- 程序正常运行，但一直打印“本轮没有待处理任务”

排查：

- 表格里是否真的有 `状态 = 待处理` 的记录
- 字段名是否确实叫 `状态`
- `.env` 中 `STATUS_FIELD_NAME` / `PENDING_STATUS` 是否与表格完全一致

### 11.4 状态写回失败

现象：

- 能读取记录，但无法更新状态或输出结果
- 典型报错：`code=91403, msg=Forbidden`

排查：

- `OUTPUT_FIELD_NAME` 和 `STATUS_FIELD_NAME` 是否填对
- 应用是否具备写权限
- 单选字段中是否存在 `处理中` / `待审核` / `处理失败` 这些选项
- 飞书开放平台中的多维表格读写权限是否已经发布生效
- 目标 Base 是否已经通过“添加文档应用”把你的自建应用加入，并授予“可编辑”权限

## 12. 适合在比赛中怎么讲

如果你在比赛答辩中介绍这个 Demo，可以用下面这套话术思路：

1. 飞书多维表格作为“组织任务面板”
2. Python 服务作为“外部大脑”
3. 表格中的每一行记录就是一份待处理任务
4. 外部服务周期性轮询待办任务
5. 不同 Agent 负责不同岗位职责
6. 结果再写回飞书，形成可视化闭环

当前这个仓库先实现了一个 `ContentWriterAgent`，但你完全可以继续扩展为：

- `ResearchAgent`
- `ReviewAgent`
- `ScheduleAgent`
- `DataAnalystAgent`

这样就能逐步演化为一个真正的 Multi-Agent 虚拟组织系统。

## 13. 下一步扩展建议

如果你想把这个 Demo 做得更像正式作品，建议继续做下面几件事：

1. 增加更多 Agent，并根据表格字段路由不同类型任务
2. 把单线程串行处理改成并发处理
3. 把日志输出到文件
4. 增加失败重试机制
5. 增加审核 Agent、总结 Agent、消息通知 Agent
6. 接入真实大模型，并把 Prompt 模板做成可配置
7. 把轮询改成更优雅的调度方式，例如 APScheduler 或任务队列

## 14. 结语

这个 Demo 的定位不是“生产级系统”，而是一个非常适合比赛展示和功能验证的最小闭环原型。

它的优势在于：

- 容易理解
- 容易跑通
- 容易演示
- 容易继续扩展

你可以先用它完成比赛原型，再逐步把它演进成更完整的多智能体系统。

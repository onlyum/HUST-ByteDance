"""
配置加载模块（采购供应链版）。

- 保留：从 .env 读取飞书凭证 / Bitable 定位 / LLM 配置。
- BusinessStatus；TABLE_IDS 中核心四表从环境变量读取（见 .env.example）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# 以当前文件所在目录作为项目根目录，便于稳定地定位 .env 文件。
BASE_DIR = Path(__file__).resolve().parent

# 显式加载项目目录下的 .env 文件。
# 如果 .env 不存在，load_dotenv 不会报错，但后续缺失变量时我们会主动抛异常。
load_dotenv(BASE_DIR / ".env")


def _get_required_env(name: str) -> str:
    """
    读取一个必填环境变量。

    如果变量为空，立刻抛出带中文提示的异常，方便使用者快速定位配置问题。
    """
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(
            f"缺少必填环境变量：{name}。"
            f"请先参考 .env.example 创建 .env，并填写正确的配置。"
        )
    return value


def _get_int_env(name: str, default: int) -> int:
    """
    读取整数类型环境变量。

    例如轮询间隔、请求超时时间这类配置，适合统一从这里解析。
    """
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，当前值为：{raw_value}") from exc


def _get_bool_env(name: str, default: bool) -> bool:
    """
    读取布尔类型环境变量。

    支持常见写法：true/false、1/0、yes/no、y/n。
    """
    raw_value = os.getenv(name, "").strip().lower()
    if not raw_value:
        return default

    if raw_value in {"1", "true", "yes", "y", "on"}:
        return True
    if raw_value in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(f"环境变量 {name} 必须是布尔值，当前值为：{raw_value}")


class BusinessStatus:
    DEMAND_PENDING = "待规划"
    DEMAND_PENDING_DEBATE = "待辩论"
    # 单阶段审批（MULTI_STAGE_APPROVAL=false）仍用「待审批」一张卡完成下单
    DEMAND_PENDING_APPROVAL = "待审批"
    # 多阶段：主管 → 运输 → 采购确认下单（需在多维表格 status 单选中增加这些选项）
    DEMAND_PENDING_APPROVAL_SUPERVISOR = "待主管审批"
    DEMAND_PENDING_APPROVAL_LOGISTICS = "待运输审批"
    # 采购部寻源后、发运前：采购在卡片中确认并持有供方/需求方对接信息（原「待下单确认」可逐步迁移为此状态）
    DEMAND_PENDING_PURCHASE_CONFIRM = "待采购确认"
    SUPPLIER_SELECTED = "已选型"
    ORDER_PLACED = "已下单"
    DEMAND_REJECTED = "已驳回"
    LOGISTICS_ABNORMAL = "异常"


TABLE_IDS = {
    "demands": _get_required_env("TABLE_ID_DEMANDS"),
    "suppliers": _get_required_env("TABLE_ID_SUPPLIERS"),
    "orders": _get_required_env("TABLE_ID_ORDERS"),
    "logs": _get_required_env("TABLE_ID_LOGS"),
    "personnel": os.getenv("TABLE_ID_PERSONNEL", "").strip(),
    "debate_history": os.getenv("TABLE_ID_DEBATE_HISTORY", "").strip(),
    "business_rules": os.getenv("TABLE_ID_BUSINESS_RULES", "").strip(),
    "interaction_memory": os.getenv("TABLE_ID_INTERACTION_MEMORY", "").strip(),
}


@dataclass(frozen=True)
class ProcurementSettings:
    # 飞书开放平台应用凭证
    feishu_app_id: str
    feishu_app_secret: str

    # Base 定位
    bitable_app_token: str

    # 编排参数
    poll_interval_seconds: int
    # 为 True 时，主循环每轮对「待辩论」自动跑 run_audit_debate（每轮最多 1 条），无需 IM「触发审批」
    auto_run_audit_debate: bool
    # 为 True：审批链为 待主管审批→待采购确认→待运输审批→建单；为 False：单卡「待审批」一键同意即下单
    multi_stage_approval: bool

    # 采购域字段名（与 Bitable 列名保持一致）
    demand_field_status: str
    demand_field_source_instruction: str
    demand_field_recommended_suppliers: str
    demand_field_budget_amount: str
    demand_field_category: str
    demand_field_demand_code: str
    demand_field_item_name: str
    demand_field_spec: str
    demand_field_quantity: str
    demand_field_uom: str
    demand_field_department: str
    demand_field_requester: str
    demand_field_currency: str
    demand_field_need_by_date: str
    demand_field_priority: str
    # 新建需求时业务编号前缀，如 DEM、DLM（生成示例 DEM-20260506-143052-0427）
    demand_code_prefix: str

    order_field_logistics_status: str
    order_field_expected_delivery_date: str
    order_field_demand: str
    order_field_supplier: str

    # 审批：未在 Personnel 表匹配到负责人时回退的 open_id（可选）
    mock_personnel_feishu_open_id: str

    # 大模型配置
    use_mock_llm: bool
    llm_api_url: str
    llm_api_key: str
    llm_model: str
    llm_connect_timeout_seconds: int
    llm_timeout_seconds: int
    # 为 True 时在请求体中加入 response_format=json_object（OpenAI 兼容 / 部分 Ark 网关支持）
    llm_json_mode: bool


def load_settings() -> ProcurementSettings:
    return ProcurementSettings(
        feishu_app_id=_get_required_env("FEISHU_APP_ID"),
        feishu_app_secret=_get_required_env("FEISHU_APP_SECRET"),
        bitable_app_token=_get_required_env("BITABLE_APP_TOKEN"),
        poll_interval_seconds=_get_int_env("POLL_INTERVAL_SECONDS", default=10),
        auto_run_audit_debate=_get_bool_env("AUTO_RUN_AUDIT_DEBATE", default=True),
        multi_stage_approval=_get_bool_env("MULTI_STAGE_APPROVAL", default=False),

        # Demands
        demand_field_status=os.getenv("DEMAND_FIELD_STATUS", "status").strip() or "status",
        demand_field_source_instruction=os.getenv("DEMAND_FIELD_SOURCE_INSTRUCTION", "source_instruction").strip() or "source_instruction",
        demand_field_recommended_suppliers=os.getenv("DEMAND_FIELD_RECOMMENDED_SUPPLIERS", "recommended_suppliers").strip() or "recommended_suppliers",
        demand_field_budget_amount=os.getenv("DEMAND_FIELD_BUDGET_AMOUNT", "budget_amount").strip() or "budget_amount",
        demand_field_category=os.getenv("DEMAND_FIELD_CATEGORY", "category").strip() or "category",
        demand_field_demand_code=os.getenv("DEMAND_FIELD_DEMAND_CODE", "demand_code").strip() or "demand_code",
        demand_field_item_name=os.getenv("DEMAND_FIELD_ITEM_NAME", "item_name").strip() or "item_name",
        demand_field_spec=os.getenv("DEMAND_FIELD_SPEC", "spec").strip() or "spec",
        demand_field_quantity=os.getenv("DEMAND_FIELD_QUANTITY", "quantity").strip() or "quantity",
        demand_field_uom=os.getenv("DEMAND_FIELD_UOM", "uom").strip() or "uom",
        demand_field_department=os.getenv("DEMAND_FIELD_DEPARTMENT", "department").strip() or "department",
        demand_field_requester=os.getenv("DEMAND_FIELD_REQUESTER", "requester").strip() or "requester",
        demand_field_currency=os.getenv("DEMAND_FIELD_CURRENCY", "currency").strip() or "currency",
        demand_field_need_by_date=os.getenv("DEMAND_FIELD_NEED_BY_DATE", "need_by_date").strip() or "need_by_date",
        demand_field_priority=os.getenv("DEMAND_FIELD_PRIORITY", "priority").strip() or "priority",
        demand_code_prefix=os.getenv("DEMAND_CODE_PREFIX", "DEM").strip() or "DEM",

        # Orders
        order_field_logistics_status=os.getenv("ORDER_FIELD_LOGISTICS_STATUS", "logistics_status").strip() or "logistics_status",
        order_field_expected_delivery_date=os.getenv("ORDER_FIELD_EXPECTED_DELIVERY_DATE", "expected_delivery_date").strip() or "expected_delivery_date",
        order_field_demand=os.getenv("ORDER_FIELD_DEMAND", "demand").strip() or "demand",
        order_field_supplier=os.getenv("ORDER_FIELD_SUPPLIER", "supplier").strip() or "supplier",

        mock_personnel_feishu_open_id=os.getenv("MOCK_PERSONNEL_FEISHU_OPEN_ID", "").strip(),

        use_mock_llm=_get_bool_env("USE_MOCK_LLM", default=True),
        llm_api_url=os.getenv("LLM_API_URL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", "mock-model").strip() or "mock-model",
        llm_connect_timeout_seconds=_get_int_env("LLM_CONNECT_TIMEOUT_SECONDS", default=10),
        llm_timeout_seconds=_get_int_env("LLM_TIMEOUT_SECONDS", default=120),
        llm_json_mode=_get_bool_env("LLM_JSON_MODE", default=False),
    )

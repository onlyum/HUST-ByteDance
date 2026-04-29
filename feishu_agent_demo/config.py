"""
配置加载模块（采购供应链版）。

- 保留：从 .env 读取飞书凭证 / Bitable 定位 / LLM 配置。
- 新增：BusinessStatus / TABLE_IDS（你已拿到 tblID，直接绑定）。
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
    SUPPLIER_SELECTED = "已选型"
    ORDER_PLACED = "已下单"
    LOGISTICS_ABNORMAL = "异常"


TABLE_IDS = {
    "demands": "tblttFySYyrRGgrV",
    "suppliers": "tblPHfNK7UejrktF",
    "orders": "tblIeEj0nwODLH8o",
    "logs": "tblB0ulWocd4vrgF",
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

    # 采购域字段名（与 Bitable 列名保持一致）
    demand_field_status: str
    demand_field_source_instruction: str
    demand_field_recommended_suppliers: str
    demand_field_budget_amount: str
    demand_field_category: str

    order_field_logistics_status: str
    order_field_expected_delivery_date: str
    order_field_demand: str
    order_field_supplier: str

    # 大模型配置
    use_mock_llm: bool
    llm_api_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int


def load_settings() -> ProcurementSettings:
    return ProcurementSettings(
        feishu_app_id=_get_required_env("FEISHU_APP_ID"),
        feishu_app_secret=_get_required_env("FEISHU_APP_SECRET"),
        bitable_app_token=_get_required_env("BITABLE_APP_TOKEN"),
        poll_interval_seconds=_get_int_env("POLL_INTERVAL_SECONDS", default=10),

        # Demands
        demand_field_status=os.getenv("DEMAND_FIELD_STATUS", "status").strip() or "status",
        demand_field_source_instruction=os.getenv("DEMAND_FIELD_SOURCE_INSTRUCTION", "source_instruction").strip() or "source_instruction",
        demand_field_recommended_suppliers=os.getenv("DEMAND_FIELD_RECOMMENDED_SUPPLIERS", "recommended_suppliers").strip() or "recommended_suppliers",
        demand_field_budget_amount=os.getenv("DEMAND_FIELD_BUDGET_AMOUNT", "budget_amount").strip() or "budget_amount",
        demand_field_category=os.getenv("DEMAND_FIELD_CATEGORY", "category").strip() or "category",

        # Orders
        order_field_logistics_status=os.getenv("ORDER_FIELD_LOGISTICS_STATUS", "logistics_status").strip() or "logistics_status",
        order_field_expected_delivery_date=os.getenv("ORDER_FIELD_EXPECTED_DELIVERY_DATE", "expected_delivery_date").strip() or "expected_delivery_date",
        order_field_demand=os.getenv("ORDER_FIELD_DEMAND", "demand").strip() or "demand",
        order_field_supplier=os.getenv("ORDER_FIELD_SUPPLIER", "supplier").strip() or "supplier",

        use_mock_llm=_get_bool_env("USE_MOCK_LLM", default=True),
        llm_api_url=os.getenv("LLM_API_URL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", "mock-model").strip() or "mock-model",
        llm_timeout_seconds=_get_int_env("LLM_TIMEOUT_SECONDS", default=30),
    )

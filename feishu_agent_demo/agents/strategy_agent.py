"""
Strategy Agent（效能评估/风险看板）
聚合需求/订单/供应商数据，生成采购效能指标与风险看板摘要，写入审计日志表。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from config import ProcurementSettings, TABLE_IDS
from feishu_bitable_toolbox import FeishuBitableToolbox

from .base_agent import BaseAgent


class StrategyAgent(BaseAgent):
    AGENT_TYPE = "strategy_agent"
    AGENT_NAME = "采购策略分析师"

    def __init__(self, agent_id: str, settings: ProcurementSettings, bitable: FeishuBitableToolbox) -> None:
        super().__init__(agent_id, settings, bitable)

    def run(self, *, demands: List[Dict[str, Any]], orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_demands = len(demands)
        total_orders = len(orders)
        abnormal_orders = 0
        for o in orders:
            f = o.get("fields") or {}
            if isinstance(f, dict) and f.get(self.settings.order_field_logistics_status) == "异常":
                abnormal_orders += 1

        dashboard = {
            "generated_at_ms": int(time.time() * 1000),
            "kpi": {
                "total_demands": total_demands,
                "total_orders": total_orders,
                "abnormal_orders": abnormal_orders,
                "abnormal_rate": (abnormal_orders / total_orders) if total_orders else 0.0,
            },
        }

        self.log_to_audit_table(
            action="read",
            target_table="Audit_Logs",
            target_record_id="strategy_dashboard",
            result="success",
            message="Strategy generated procurement KPI dashboard",
            detail=dashboard,
        )
        return dashboard


"""
Tracker Agent（执行/物流追踪）
模拟下单执行，并持续追踪全球物流状态，异常时回写订单与需求状态。
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, Tuple

from config import BusinessStatus, ProcurementSettings
from feishu_bitable_toolbox import FeishuBitableToolbox

from .base_agent import BaseAgent


class TrackerAgent(BaseAgent):
    AGENT_TYPE = "tracker_agent"
    AGENT_NAME = "物流追踪员"

    def __init__(self, agent_id: str, settings: ProcurementSettings, bitable: FeishuBitableToolbox) -> None:
        super().__init__(agent_id, settings, bitable)

    @staticmethod
    def _parse_retry_count(exception_reason: Any) -> int:
        text = str(exception_reason or "")
        m = re.search(r"AUTO_RETRY_(\d+)", text)
        if not m:
            return 0
        try:
            return int(m.group(1))
        except ValueError:
            return 0

    def run(self, order_record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        order_record_id = str(order_record.get("record_id", ""))
        fields = order_record.get("fields") or {}
        if not isinstance(fields, dict):
            fields = {}

        current = str(fields.get(self.settings.order_field_logistics_status, "") or "")
        retry_count = self._parse_retry_count(fields.get("exception_reason"))

        # Mock：按概率推进状态，并避免“异常->异常”无限循环
        next_status = current
        roll = random.random()
        next_retry_count = retry_count
        order_status_update: Dict[str, Any] = {}

        if current in ("待发货", ""):
            next_status = "运输中" if roll > 0.1 else "异常"
            next_retry_count = 1 if next_status == "异常" else 0
        elif current == "运输中":
            next_status = "已送达" if roll > 0.2 else "异常"
            next_retry_count = retry_count + 1 if next_status == "异常" else 0
        elif current == "异常":
            # 异常优先恢复；连续 3 次异常则自动取消订单，避免死循环
            if retry_count >= 3:
                next_status = "异常"
                order_status_update = {"order_status": "已取消"}
                next_retry_count = retry_count
            else:
                next_status = "运输中" if roll > 0.2 else "异常"
                next_retry_count = retry_count + 1 if next_status == "异常" else retry_count

        update_fields = {
            self.settings.order_field_logistics_status: next_status,
            "exception_reason": (f"AUTO_RETRY_{next_retry_count}" if next_status == "异常" else "无"),
        }
        update_fields.update(order_status_update)

        self.log_to_audit_table(
            action="update",
            target_table="Orders",
            target_record_id=order_record_id,
            result="success",
            message=f"Tracker updated logistics_status: {current} -> {next_status}",
            detail={
                "previous": current,
                "next": next_status,
                "retry_count": retry_count,
                "next_retry_count": next_retry_count,
                "order_status_update": order_status_update,
            },
            order_record_id=order_record_id,
        )

        # 返回“异常”供 orchestrator 触发额外处理
        return update_fields, (BusinessStatus.LOGISTICS_ABNORMAL if next_status == "异常" else next_status)


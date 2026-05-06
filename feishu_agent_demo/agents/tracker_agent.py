"""
Tracker Agent（执行/物流追踪）
对已生成订单按编排周期轮询更新 logistics_status，在多维表中体现「在途跟踪」；
不对物理里程碑做额外人工审查（无承运商轨迹解析）。
不接真实物流 API；异常状态由业务在表中标注或由外部同步写入，Tracker 负责异常上报（审计 + 关联需求备注 + 日志）。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from config import TABLE_IDS, BusinessStatus, ProcurementSettings
from feishu_bitable_toolbox import FeishuBitableToolbox

from .base_agent import BaseAgent

# 同一订单在「运输中」下连续被 Tracker 扫描的次数达到该值后，推进为「已送达」（演示跟单节拍）
_TRANSIT_SCANS_BEFORE_DELIVERED = 2
# 同一订单处于「异常」时，重复写入审计/备注的最小间隔（秒），避免编排 tick 刷屏
_ABNORMAL_REPORT_MIN_INTERVAL_S = 1800.0


class TrackerAgent(BaseAgent):
    AGENT_TYPE = "tracker_agent"
    AGENT_NAME = "物流追踪员"

    def __init__(self, agent_id: str, settings: ProcurementSettings, bitable: FeishuBitableToolbox) -> None:
        super().__init__(agent_id, settings, bitable)
        # 进程内：订单在「运输中」已累计的扫描次数（重启后重新累计）
        self._in_transit_scan_count: Dict[str, int] = {}
        self._abnormal_last_report_ts: Dict[str, float] = {}

    @staticmethod
    def _link_record_ids(val: Any) -> List[str]:
        out: List[str] = []
        if val is None:
            return out
        if isinstance(val, list):
            for item in val:
                out.extend(TrackerAgent._link_record_ids(item))
            return out
        if isinstance(val, dict):
            if isinstance(val.get("link_record_ids"), list):
                out.extend(str(x).strip() for x in val["link_record_ids"] if isinstance(x, str) and str(x).strip())
            out.extend(TrackerAgent._link_record_ids(val.get("value")))
        return out

    def _first_demand_record_id(self, fields: Dict[str, Any]) -> str:
        raw = fields.get(self.settings.order_field_demand)
        ids = self._link_record_ids(raw)
        return ids[0] if ids else ""

    def _report_logistics_abnormal(self, order_record_id: str, fields: Dict[str, Any]) -> None:
        now = time.time()
        last = self._abnormal_last_report_ts.get(order_record_id, 0.0)
        if now - last < _ABNORMAL_REPORT_MIN_INTERVAL_S:
            return
        self._abnormal_last_report_ts[order_record_id] = now

        reason = str(fields.get("exception_reason") or "").strip() or "未分类"
        demand_id = self._first_demand_record_id(fields)
        brief = f"订单 {order_record_id[:12]}… 物流异常，原因：{reason}"

        self.logger.warning("[物流异常上报] %s demand=%s", brief, demand_id or "-")

        self.log_to_audit_table(
            action="error",
            target_table="Orders",
            target_record_id=order_record_id,
            result="fail",
            message="物流异常上报",
            detail={"logistics_status": "异常", "exception_reason": reason, "demand_record_id": demand_id},
            demand_record_id=demand_id or None,
            order_record_id=order_record_id,
        )

        if not demand_id:
            return
        try:
            demand = self.bitable.get_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["demands"],
                record_id=demand_id,
            )
            df = demand.get("fields") if isinstance(demand, dict) else {}
            if not isinstance(df, dict):
                df = {}
            prev = str(df.get("notes") or "").strip()
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            line = f"[{stamp}] {brief}"
            merged = (prev + ("\n" if prev else "") + line)[-2000:]
            self.bitable.update_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["demands"],
                record_id=demand_id,
                fields={"notes": merged},
            )
        except Exception as exc:
            self.logger.warning("物流异常上报：写入需求备注失败 demand=%s err=%s", demand_id, exc)

    def run(self, order_record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        order_record_id = str(order_record.get("record_id", ""))
        fields = order_record.get("fields") or {}
        if not isinstance(fields, dict):
            fields = {}

        current = str(fields.get(self.settings.order_field_logistics_status, "") or "")

        if current == "异常":
            self._report_logistics_abnormal(order_record_id, fields)
            return {}, BusinessStatus.LOGISTICS_ABNORMAL

        next_status = current
        update_fields: Dict[str, Any] = {}

        if current in ("待发货", ""):
            next_status = "运输中"
            self._in_transit_scan_count.pop(order_record_id, None)
            update_fields = {self.settings.order_field_logistics_status: next_status}
        elif current == "运输中":
            n = self._in_transit_scan_count.get(order_record_id, 0) + 1
            self._in_transit_scan_count[order_record_id] = n
            if n >= _TRANSIT_SCANS_BEFORE_DELIVERED:
                next_status = "已送达"
                self._in_transit_scan_count.pop(order_record_id, None)
                update_fields = {
                    self.settings.order_field_logistics_status: next_status,
                    "exception_reason": "无",
                }
                detail_scans = n
            else:
                next_status = "运输中"
                update_fields = {}
                detail_scans = n
        else:
            return {}, current

        if not update_fields:
            return {}, next_status

        detail: Dict[str, Any] = {"previous": current, "next": next_status}
        if current == "运输中":
            detail["in_transit_scans"] = detail_scans

        self.log_to_audit_table(
            action="update",
            target_table="Orders",
            target_record_id=order_record_id,
            result="success",
            message=f"Tracker 跟单更新 logistics_status: {current} -> {next_status}",
            detail=detail,
            order_record_id=order_record_id,
        )

        return update_fields, next_status

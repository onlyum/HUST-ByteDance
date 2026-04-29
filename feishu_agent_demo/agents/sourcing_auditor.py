"""
Sourcing Auditor（选型审计/比价）
对候选供应商做资质审查与比价决策，输出选型结果并触发下单（创建订单）。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from config import BusinessStatus, ProcurementSettings, TABLE_IDS
from feishu_bitable_toolbox import FeishuBitableToolbox

from .base_agent import BaseAgent


class SourcingAuditorAgent(BaseAgent):
    AGENT_TYPE = "sourcing_auditor"
    AGENT_NAME = "选型审计官"

    def __init__(self, agent_id: str, settings: ProcurementSettings, bitable: FeishuBitableToolbox) -> None:
        super().__init__(agent_id, settings, bitable)

    def _search_suppliers_by_category(self, category_from_demand: str) -> List[str]:
        """
        按 Suppliers.main_business（多选字段）做包含匹配，返回候选供应商 record_id。
        """
        if not category_from_demand:
            return []

        # 多选字段过滤：contains 逻辑
        filter_query = f'CurrentValue.[main_business].contains("{category_from_demand}")'
        candidate_ids: List[str] = []

        # 先尝试服务端过滤
        for rec in self.bitable.iter_records(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["suppliers"],
            filter_formula=filter_query,
            fields=["main_business", "credit_score", "status"],
            max_pages=5,
        ):
            rid = rec.get("record_id")
            if isinstance(rid, str):
                candidate_ids.append(rid)

        if candidate_ids:
            return candidate_ids

        # 部分租户/版本对 contains 支持不稳定时，降级为本地包含匹配
        for rec in self.bitable.iter_records(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["suppliers"],
            fields=["main_business", "credit_score", "status"],
            max_pages=10,
        ):
            fields = rec.get("fields") or {}
            if not isinstance(fields, dict):
                continue
            mb = fields.get("main_business")
            hit = False
            if isinstance(mb, list):
                for item in mb:
                    if isinstance(item, str) and item == category_from_demand:
                        hit = True
                        break
                    if isinstance(item, dict) and str(item.get("text", "")) == category_from_demand:
                        hit = True
                        break
            elif isinstance(mb, str) and mb == category_from_demand:
                hit = True
            if hit and isinstance(rec.get("record_id"), str):
                candidate_ids.append(rec["record_id"])
        return candidate_ids

    def _pick_supplier(self, supplier_record_ids: List[str]) -> Optional[str]:
        # 简化：按 credit_score 最高选（读取供应商上下文）
        best_id: Optional[str] = None
        best_score: float = float("-inf")
        for sid in supplier_record_ids:
            ctx = self.get_supplier_context(sid)
            score = ctx.get("credit_score")
            try:
                score_f = float(score)
            except Exception:
                score_f = 0.0
            if score_f > best_score:
                best_score = score_f
                best_id = sid
        return best_id

    def run(self, demand_record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        demand_record_id = str(demand_record.get("record_id", ""))
        demand_fields = demand_record.get("fields") or {}
        if not isinstance(demand_fields, dict):
            demand_fields = {}

        # 优先走显式推荐供应商 link
        candidates_raw = demand_fields.get(self.settings.demand_field_recommended_suppliers)
        candidate_ids: List[str] = []
        if isinstance(candidates_raw, list):
            for obj in candidates_raw:
                if isinstance(obj, dict) and isinstance(obj.get("record_id"), str):
                    candidate_ids.append(obj["record_id"])
                elif isinstance(obj, str):
                    candidate_ids.append(obj)

        # 如果无推荐供应商，则按需求分类去 Suppliers.main_business 做包含匹配
        if not candidate_ids:
            category_from_demand = str(demand_fields.get(self.settings.demand_field_category, "") or "")
            candidate_ids = self._search_suppliers_by_category(category_from_demand)

        chosen_supplier = self._pick_supplier(candidate_ids) if candidate_ids else None
        if not chosen_supplier:
            self.log_to_audit_table(
                action="recommend",
                target_table="Demands",
                target_record_id=demand_record_id,
                result="fail",
                message="No candidate suppliers to audit",
                detail={
                    "candidate_count": len(candidate_ids),
                    "category_from_demand": str(demand_fields.get(self.settings.demand_field_category, "") or ""),
                },
                demand_record_id=demand_record_id,
            )
            return {}, BusinessStatus.SUPPLIER_SELECTED

        # 创建订单（Orders.demand 一对一；Orders.supplier 多对一）
        order_fields: Dict[str, Any] = {
            "order_code": f"PO-{int(time.time())}",
            self.settings.order_field_demand: demand_record_id,
            self.settings.order_field_supplier: chosen_supplier,
            self.settings.order_field_logistics_status: "待发货",
        }
        order_record_id = self.bitable.add_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["orders"],
            fields=order_fields,
            link_fields=[self.settings.order_field_demand, self.settings.order_field_supplier],
        )

        self.log_to_audit_table(
            action="order",
            target_table="Orders",
            target_record_id=order_record_id,
            result="success",
            message="Sourcing auditor selected supplier and placed order",
            detail={"chosen_supplier": chosen_supplier, "candidate_ids": candidate_ids},
            demand_record_id=demand_record_id,
            supplier_record_id=chosen_supplier,
            order_record_id=order_record_id,
        )

        # 推进需求状态
        update_fields = {self.settings.demand_field_status: BusinessStatus.ORDER_PLACED}
        return update_fields, BusinessStatus.ORDER_PLACED


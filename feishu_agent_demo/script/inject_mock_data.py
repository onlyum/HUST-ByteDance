from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List

# Ensure project root (feishu_agent_demo/) is importable when running from script/
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import TABLE_IDS, load_settings  # noqa: E402
from feishu_bitable_toolbox import FeishuBitableToolbox  # noqa: E402


mock_suppliers: List[Dict[str, Any]] = [
    {
        "supplier_name": "全球光学 (Global Optics)",
        "supplier_code": "SUP-001",
        "credit_score": 98,
        "supplier_level": "A",
        "status": "启用",
        "main_business": ["原材料"],
        "contact_name": "王工",
        "contact_phone": "13800000001",
        "contact_email": "sales@globaloptics.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "核心传感科技 (Sensor Pro)",
        "supplier_code": "SUP-004",
        "credit_score": 92,
        "supplier_level": "A",
        "status": "启用",
        "main_business": ["原材料"],
        "contact_name": "李经理",
        "contact_phone": "13800000002",
        "contact_email": "bd@sensorpro.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
]

mock_demands: List[Dict[str, Any]] = [
    {
        "demand_code": "DEM-20260426-01",
        "source_instruction": "采购红外 CMOS 传感器 500 个，预算 10 万，交付 2026-05-20，需可开票。",
        "requester": "张三",
        "department": "研发",
        "category": "原材料",
        "item_name": "红外 CMOS 传感器",
        "spec": "1/2.7 inch, 640x512, -20~70℃",
        "quantity": 500,
        "uom": "个",
        "budget_amount": 100000,
        "currency": "CNY",
        "priority": "P1",
        "status": "待规划",
        "need_by_date": 1747680000000,  # 2026-05-20 毫秒时间戳
        "notes": "需提供 RoHS / REACH 证明，优先现货。",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    }
]


def inject_mock_data() -> None:
    settings = load_settings()
    client = FeishuBitableToolbox(app_id=settings.feishu_app_id, app_secret=settings.feishu_app_secret)

    print("--- 开始注入 Mock 数据 ---")

    # 1) 注入供应商
    supplier_record_ids: List[str] = []
    for s in mock_suppliers:
        rid = client.add_record(
            app_token=settings.bitable_app_token,
            table_id=TABLE_IDS["suppliers"],
            fields=s,
        )
        supplier_record_ids.append(rid)
        print(f"注入供应商成功: {s.get('supplier_name')} record_id={rid}")

    # 2) 注入需求，并写入推荐供应商 Link（list[str] -> 自动归一化为 [{'record_id': ...}]）
    for d in mock_demands:
        fields = dict(d)
        fields["recommended_suppliers"] = supplier_record_ids
        rid = client.add_record(
            app_token=settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            fields=fields,
            link_fields=["recommended_suppliers"],
        )
        print(f"注入采购需求成功: {d.get('item_name')} record_id={rid} (已关联 {len(supplier_record_ids)} 家供应商)")

    # 3) 记录初始系统日志（如果 Logs 表没有这些列，请按你的表结构删减字段）
    log_fields = {
        "log_id": f"LOG-{int(time.time())}",
        "timestamp": int(time.time() * 1000),
        "agent_name": "system",
        "action": "create",
        "target_table": "Suppliers",
        "target_record_id": "-",
        "demand": None,
        "supplier": None,
        "order": None,
        "result": "success",
        "error_code": "",
        "message": "初始化种子数据完成，系统进入待命状态。",
        "detail_json": "{}",
    }
    log_id = client.add_record(
        app_token=settings.bitable_app_token,
        table_id=TABLE_IDS["logs"],
        fields={k: v for k, v in log_fields.items() if v is not None},
        link_fields=[],
    )
    print(f"写入运行日志成功: record_id={log_id}")

    print("--- Mock 数据注入完成 ---")


if __name__ == "__main__":
    inject_mock_data()


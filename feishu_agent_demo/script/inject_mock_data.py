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
        "quality_score": 98,
        "cost_score": 62,
        "lead_time_days": 5,
        "user_rating": 5,
        "risk_level": "低",
        "user_review_detail": "战略级伙伴，配合度极高，曾多次协助紧急调货。",
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
        "supplier_name": "核心传感 (Sensor Pro)",
        "supplier_code": "SUP-002",
        "credit_score": 92,
        "quality_score": 89,
        "cost_score": 85,
        "lead_time_days": 12,
        "user_rating": 4,
        "risk_level": "低",
        "user_review_detail": "性能稳定，成本优势明显，是目前主流型号的首选。",
        "supplier_level": "A",
        "status": "启用",
        "main_business": ["原材料"],
        "contact_name": "李经理",
        "contact_phone": "13800000002",
        "contact_email": "bd@sensorpro.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "极速电路 (Fast PCB)",
        "supplier_code": "SUP-003",
        "credit_score": 85,
        "quality_score": 82,
        "cost_score": 88,
        "lead_time_days": 3,
        "user_rating": 3,
        "risk_level": "中",
        "user_review_detail": "交期非常快，但大批量产时良率偶有波动。",
        "supplier_level": "B",
        "status": "启用",
        "main_business": ["备品备件"],
        "contact_name": "周工",
        "contact_phone": "13800000003",
        "contact_email": "sales@fastpcb.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "稳健原材料 (Stable Raw)",
        "supplier_code": "SUP-004",
        "credit_score": 95,
        "quality_score": 96,
        "cost_score": 45,
        "lead_time_days": 10,
        "user_rating": 4,
        "risk_level": "低",
        "user_review_detail": "价格偏贵，但材料一致性极好，从未出过质量事故。",
        "supplier_level": "A",
        "status": "启用",
        "main_business": ["原材料"],
        "contact_name": "赵经理",
        "contact_phone": "13800000004",
        "contact_email": "bd@stableraw.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "创新微电子 (Inno Micro)",
        "supplier_code": "SUP-005",
        "credit_score": 78,
        "quality_score": 92,
        "cost_score": 70,
        "lead_time_days": 45,
        "user_rating": 2,
        "risk_level": "高",
        "user_review_detail": "技术很强，但财务状况不稳定，售后响应极慢。",
        "supplier_level": "C",
        "status": "启用",
        "main_business": ["原材料"],
        "contact_name": "孙工",
        "contact_phone": "13800000005",
        "contact_email": "sales@innomicro.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "精密模组 (Precision Mod)",
        "supplier_code": "SUP-006",
        "credit_score": 90,
        "quality_score": 94,
        "cost_score": 55,
        "lead_time_days": 7,
        "user_rating": 5,
        "risk_level": "低",
        "user_review_detail": "王工团队技术支持很给力，复杂结构件的首选。",
        "supplier_level": "A",
        "status": "启用",
        "main_business": ["备品备件"],
        "contact_name": "王工",
        "contact_phone": "13800000006",
        "contact_email": "bd@precisionmod.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "惠民配件 (HuiMin Part)",
        "supplier_code": "SUP-007",
        "credit_score": 70,
        "quality_score": 65,
        "cost_score": 98,
        "lead_time_days": 4,
        "user_rating": 1,
        "risk_level": "中",
        "user_review_detail": "便宜但质量差，且发生过货不对板的违约记录。",
        "supplier_level": "D",
        "status": "启用",
        "main_business": ["备品备件"],
        "contact_name": "钱经理",
        "contact_phone": "13800000007",
        "contact_email": "sales@huiminpart.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "巅峰科技 (Peak Tech)",
        "supplier_code": "SUP-008",
        "credit_score": 94,
        "quality_score": 95,
        "cost_score": 50,
        "lead_time_days": 15,
        "user_rating": 4,
        "risk_level": "低",
        "user_review_detail": "激光雷达专家，除了贵和排产久，没别的问题。",
        "supplier_level": "A",
        "status": "启用",
        "main_business": ["设备"],
        "contact_name": "郑工",
        "contact_phone": "13800000008",
        "contact_email": "bd@peaktech.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "智能方案商 (AI)",
        "supplier_code": "SUP-009",
        "credit_score": 80,
        "quality_score": 80,
        "cost_score": 82,
        "lead_time_days": 20,
        "user_rating": 3,
        "risk_level": "中",
        "user_review_detail": "沟通成本较高，方案调整反应速度一般。",
        "supplier_level": "B",
        "status": "启用",
        "main_business": ["服务"],
        "contact_name": "陈经理",
        "contact_phone": "13800000009",
        "contact_email": "sales@aiplan.example",
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    },
    {
        "supplier_name": "长胜物流 (EverWin)",
        "supplier_code": "SUP-010",
        "credit_score": 88,
        "quality_score": 88,
        "cost_score": 75,
        "lead_time_days": 2,
        "user_rating": 4,
        "risk_level": "低",
        "user_review_detail": "包装极其扎实，物流损耗率为全库最低。",
        "supplier_level": "A",
        "status": "启用",
        "main_business": ["服务"],
        "contact_name": "刘经理",
        "contact_phone": "13800000010",
        "contact_email": "bd@everwinlogistics.example",
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


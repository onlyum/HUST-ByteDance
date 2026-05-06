"""
向「负责人表 / Personnel」注入 Mock 行。

前置：
- 已执行 script/sqlinit.py 创建 Personnel 表字段（见 sqlinit 中 Personnel 段）。
- .env 中配置 TABLE_ID_PERSONNEL。
- .env 中配置 MOCK_PERSONNEL_FEISHU_OPEN_ID（所有行的 feishu_open_id 共用该值，便于本地联调审批卡片）。

运行：
    cd feishu_agent_demo
    python script/inject_personnel_mock.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import TABLE_IDS, load_settings  # noqa: E402
from feishu_bitable_toolbox import FeishuBitableToolbox  # noqa: E402


def _now_ms() -> int:
    return int(time.time() * 1000)


def _build_rows(shared_open_id: str) -> List[Dict[str, Any]]:
    """
    字段与 sqlinit Personnel 一致；多审批人拆分 managed_categories，便于按品类路由。
    所有行的 feishu_open_id 均为 shared_open_id（演示时卡片都发到同一飞书账号）。
    """
    ts = _now_ms()
    return [
        {
            "staff_id": "PERS-001",
            "name": "张审批",
            "feishu_open_id": shared_open_id,
            "department": "采购部",
            "role": "Approver",
            "managed_categories": ["电子料", "原材料"],
            "created_at": ts,
            "updated_at": ts,
        },
        {
            "staff_id": "PERS-002",
            "name": "李审批",
            "feishu_open_id": shared_open_id,
            "department": "质量部",
            "role": "Approver",
            "managed_categories": ["光学件", "辅料"],
            "created_at": ts,
            "updated_at": ts,
        },
        {
            "staff_id": "PERS-003",
            "name": "王审批",
            "feishu_open_id": shared_open_id,
            "department": "设备工程部",
            "role": "Approver",
            "managed_categories": ["设备", "服务"],
            "created_at": ts,
            "updated_at": ts,
        },
        {
            "staff_id": "PERS-004",
            "name": "赵审批",
            "feishu_open_id": shared_open_id,
            "department": "供应链部",
            "role": "Approver",
            "managed_categories": ["包装", "其他"],
            "created_at": ts,
            "updated_at": ts,
        },
        {
            "staff_id": "PERS-005",
            "name": "钱采购",
            "feishu_open_id": shared_open_id,
            "department": "采购执行",
            "role": "Purchaser",
            "managed_categories": ["原材料", "辅料"],
            "created_at": ts,
            "updated_at": ts,
        },
        {
            "staff_id": "PERS-006",
            "name": "孙财务",
            "feishu_open_id": shared_open_id,
            "department": "财务部",
            "role": "Finance",
            "managed_categories": ["其他"],
            "created_at": ts,
            "updated_at": ts,
        },
    ]


def inject_personnel_mock() -> None:
    open_id = os.getenv("MOCK_PERSONNEL_FEISHU_OPEN_ID", "").strip()
    if not open_id:
        raise ValueError(
            "请先在 .env 设置 MOCK_PERSONNEL_FEISHU_OPEN_ID（可与机器人私聊后从日志复制 open_id）。"
        )

    personnel_table_id = str(TABLE_IDS.get("personnel") or "").strip()
    if not personnel_table_id:
        raise ValueError("请先在 .env 设置 TABLE_ID_PERSONNEL，与 config.TABLE_IDS['personnel'] 对应。")

    settings = load_settings()
    client = FeishuBitableToolbox(app_id=settings.feishu_app_id, app_secret=settings.feishu_app_secret)
    rows = _build_rows(open_id)

    print("--- 开始注入 Personnel Mock（feishu_open_id 全部相同）---")
    print(f"open_id={open_id}")
    print(f"table_id={personnel_table_id}")

    for row in rows:
        rid = client.add_record(
            app_token=settings.bitable_app_token,
            table_id=personnel_table_id,
            fields=row,
        )
        print(f"注入成功: staff_id={row.get('staff_id')} name={row.get('name')} role={row.get('role')} record_id={rid}")

    print("--- Personnel Mock 注入完成 ---")


if __name__ == "__main__":
    inject_personnel_mock()

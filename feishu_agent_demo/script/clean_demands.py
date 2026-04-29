from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import TABLE_IDS, load_settings  # noqa: E402
from feishu_bitable_toolbox import FeishuBitableToolbox  # noqa: E402


KEEP_DEMAND_CODE = "DEM-20260426-01"


def clean_demands() -> None:
    settings = load_settings()
    client = FeishuBitableToolbox(app_id=settings.feishu_app_id, app_secret=settings.feishu_app_secret)

    deleted = 0
    kept = 0
    for rec in client.iter_records(
        app_token=settings.bitable_app_token,
        table_id=TABLE_IDS["demands"],
        fields=["demand_code"],
        max_pages=20,
    ):
        rid = rec.get("record_id")
        fields = rec.get("fields") or {}
        if not isinstance(rid, str) or not isinstance(fields, dict):
            continue
        demand_code = str(fields.get("demand_code", "") or "")
        if demand_code == KEEP_DEMAND_CODE:
            kept += 1
            continue
        client.delete_record(
            app_token=settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            record_id=rid,
        )
        deleted += 1

    print(f"保留 demand_code={KEEP_DEMAND_CODE}: {kept} 条")
    print(f"已删除其他需求记录: {deleted} 条")


if __name__ == "__main__":
    clean_demands()


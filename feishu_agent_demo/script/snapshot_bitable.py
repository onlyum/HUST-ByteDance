"""
读取当前 Base 中 config.TABLE_IDS 涉及的表：字段列表、记录数、首条记录样例。
用于注入/联调前确认「表现在什么样」，再决定下一步（补字段、清表、注入 mock 等）。

用法（在 feishu_agent_demo 目录）:
    python script/snapshot_bitable.py
    python script/snapshot_bitable.py --json   # 输出机器可读 JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import TABLE_IDS, load_settings  # noqa: E402
from feishu_bitable_toolbox import FeishuBitableToolbox, FeishuHttpError  # noqa: E402


TABLE_LABELS: Dict[str, str] = {
    "demands": "需求 Demands",
    "suppliers": "供应商 Suppliers",
    "orders": "订单 Orders",
    "logs": "审计日志 Audit_Logs",
    "personnel": "负责人 Personnel",
    "debate_history": "辩论记录 Debate_History",
    "business_rules": "业务规则 Business_Rules",
    "interaction_memory": "交互记忆 Interaction_Memory",
}

# 单表最多翻页计数，避免超大表长时间阻塞（达上限显示为 {cap}+）
_COUNT_PAGE_SIZE = 200
_COUNT_MAX_PAGES = 100


def _collect_all_fields(
    client: FeishuBitableToolbox, *, app_token: str, table_id: str
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        items, page_token, has_more = client.list_table_fields(
            app_token=app_token,
            table_id=table_id,
            page_size=200,
            page_token=page_token,
        )
        for it in items:
            if isinstance(it, dict):
                out.append(it)
        if not has_more or not page_token:
            break
    return out


def _count_records(
    client: FeishuBitableToolbox, *, app_token: str, table_id: str
) -> Tuple[str, bool]:
    total = 0
    pages = 0
    page_token: Optional[str] = None
    capped = False
    while pages < _COUNT_MAX_PAGES:
        items, page_token, has_more = client.list_records(
            app_token=app_token,
            table_id=table_id,
            page_size=_COUNT_PAGE_SIZE,
            page_token=page_token,
        )
        total += len(items)
        pages += 1
        if not has_more or not page_token:
            return str(total), capped
    return f"{_COUNT_PAGE_SIZE * _COUNT_MAX_PAGES}+", True


def _short_value(value: Any, max_len: int = 72) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        one = value.replace("\n", " ").strip()
        return one if len(one) <= max_len else one[: max_len - 3] + "..."
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(isinstance(x, dict) and "record_id" in x for x in value):
            ids = [str(x.get("record_id", ""))[:8] for x in value[:3]]
            suffix = f", +{len(value) - 3}…" if len(value) > 3 else ""
            return "[" + ", ".join(ids) + suffix + "]"
        return f"[{len(value)} 项]"
    if isinstance(value, dict):
        keys = list(value.keys())[:4]
        return "{" + ", ".join(keys) + ("…" if len(value) > 4 else "") + "}"
    return str(type(value).__name__)


def _first_record_sample(client: FeishuBitableToolbox, *, app_token: str, table_id: str) -> Optional[Dict[str, Any]]:
    items, _, _ = client.list_records(
        app_token=app_token,
        table_id=table_id,
        page_size=1,
    )
    if not items or not isinstance(items[0], dict):
        return None
    rec = items[0]
    rid = rec.get("record_id")
    fields = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
    # 优先展示主键/常用列，其余按名字排序取前 12 个
    preferred = [
        "staff_id",
        "supplier_code",
        "demand_code",
        "order_code",
        "log_id",
        "status",
        "name",
        "supplier_name",
        "item_name",
        "category",
        "role",
        "feishu_open_id",
    ]
    shown: Dict[str, str] = {}
    for key in preferred:
        if key in fields:
            shown[key] = _short_value(fields.get(key))
    for key in sorted(fields.keys()):
        if key in shown:
            continue
        if len(shown) >= 12:
            break
        shown[key] = _short_value(fields.get(key))
    return {"record_id": rid, "fields_preview": shown}


def _field_type_label(meta: Dict[str, Any]) -> str:
    t = meta.get("type")
    if isinstance(t, int):
        return str(t)
    if t is not None:
        return str(t)
    ui = meta.get("ui_type")
    return str(ui) if ui is not None else "?"


def snapshot_one_table(
    client: FeishuBitableToolbox,
    *,
    app_token: str,
    logical_key: str,
    table_id: str,
) -> Dict[str, Any]:
    label = TABLE_LABELS.get(logical_key, logical_key)
    row: Dict[str, Any] = {
        "key": logical_key,
        "label": label,
        "table_id": table_id,
        "ok": False,
        "error": None,
        "field_count": 0,
        "fields": [],
        "record_count": None,
        "record_count_capped": False,
        "sample": None,
    }
    try:
        raw_fields = _collect_all_fields(client, app_token=app_token, table_id=table_id)
        field_rows = []
        for it in raw_fields:
            if not isinstance(it, dict):
                continue
            name = it.get("field_name")
            if not isinstance(name, str):
                continue
            field_rows.append(
                {
                    "field_name": name,
                    "field_id": it.get("field_id"),
                    "type": _field_type_label(it),
                }
            )
        field_rows.sort(key=lambda x: x["field_name"])
        row["field_count"] = len(field_rows)
        row["fields"] = field_rows

        cnt, capped = _count_records(client, app_token=app_token, table_id=table_id)
        row["record_count"] = cnt
        row["record_count_capped"] = capped

        row["sample"] = _first_record_sample(client, app_token=app_token, table_id=table_id)
        row["ok"] = True
    except FeishuHttpError as exc:
        row["error"] = str(exc)
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def print_text_report(rows: List[Dict[str, Any]], app_token_hint: str) -> None:
    print("=" * 72)
    print("飞书多维表格快照（config.TABLE_IDS）")
    print(f"BITABLE_APP_TOKEN: {app_token_hint[:6]}…{app_token_hint[-4:]}" if len(app_token_hint) > 10 else f"BITABLE_APP_TOKEN: {app_token_hint}")
    print("=" * 72)

    for row in rows:
        if row.get("skipped"):
            print(f"\n[{row['key']}] {row.get('label')} — 未配置 table_id（.env 留空或缺省）")
            continue
        print(f"\n### {row['label']}  [{row['key']}]")
        print(f"    table_id: {row['table_id']}")
        if not row.get("ok"):
            print(f"    ERROR: {row.get('error')}")
            continue
        print(f"    字段数: {row['field_count']}  |  记录数: {row['record_count']}" + ("（已达扫描上限，实际可能更多）" if row.get("record_count_capped") else ""))
        if row["fields"]:
            print("    字段:")
            for f in row["fields"]:
                print(f"      - {f['field_name']}  (type={f['type']})")
        sample = row.get("sample")
        if sample:
            print(f"    样例 record_id: {sample.get('record_id')}")
            for k, v in (sample.get("fields_preview") or {}).items():
                print(f"      · {k}: {v}")
        else:
            print("    样例: （无记录）")

    print("\n" + "=" * 72)
    print("下一步可参考：缺表则建表并 sqlinit；缺数据则 inject_mock / inject_personnel_mock；")
    print("Personnel 需 TABLE_ID_PERSONNEL + MOCK_PERSONNEL_FEISHU_OPEN_ID。")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="快照 Base 表结构与数据概况")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    settings = load_settings()
    client = FeishuBitableToolbox(app_id=settings.feishu_app_id, app_secret=settings.feishu_app_secret)
    app_token = settings.bitable_app_token

    rows: List[Dict[str, Any]] = []
    for key in [
        "demands",
        "suppliers",
        "orders",
        "logs",
        "personnel",
        "debate_history",
        "business_rules",
        "interaction_memory",
    ]:
        tid = str(TABLE_IDS.get(key) or "").strip()
        if not tid:
            rows.append(
                {
                    "key": key,
                    "label": TABLE_LABELS.get(key, key),
                    "skipped": True,
                }
            )
            continue
        rows.append(snapshot_one_table(client, app_token=app_token, logical_key=key, table_id=tid))

    token_hint = app_token
    if args.json:
        payload = {
            "bitable_app_token_suffix": token_hint[-6:] if len(token_hint) > 6 else token_hint,
            "tables": rows,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text_report(rows, token_hint)

    if any(not r.get("skipped") and not r.get("ok") for r in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

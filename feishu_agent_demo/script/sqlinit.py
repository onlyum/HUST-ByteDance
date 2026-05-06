import requests
import time
import json
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================= 配置区 =================
APP_ID = "cli_a9660be8fc615cdb"
APP_SECRET = "rmnLNYmsUIgn2OOx8Yjsdc3crvR7TILB"
APP_TOKEN = "IMWGbbzIlay7AXsiEooch4bnnY9"

# table_id 可能被误粘贴成 "tblxxx&view=..."，这里做一次标准化。
def _normalize_table_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    # 常见误粘贴：tblxxxx&view=vewxxxx
    if "&" in raw:
        raw = raw.split("&", 1)[0].strip()
    return raw

# 之前获取的 Table ID 映射
TABLE_MAP = {
    "Demands": "tblttFySYyrRGgrV",
    "Orders": "tblIeEj0nwODLH8o",
    "Suppliers": "tblPHfNK7UejrktF",
    "Audit_Logs": "tblB0ulWocd4vrgF",
    # 新增扩展表（请先在 Bitable 中创建空表并填入 table_id）
    "Personnel": "tblW4srFXM2PKG3E",
    "Debate_History": "tblyFV7WHN29lhhQ",
    "Business_Rules": "tblTrEbfN5ifqbtq",
    "Interaction_Memory": "tblRQIuD6uburRFG",
}

# 统一标准化 table_id
TABLE_MAP = {k: _normalize_table_id(v) for k, v in TABLE_MAP.items()}

# 字段类型映射表 (飞书 API 标准)
TYPE_MAP = {
    "text": 1,
    "number": 2,
    "single_select": 3,
    "multi_select": 4,
    "date": 5,
    "link": 18,
    "formula": 20
}

class BitableFieldCreator:
    def __init__(self, app_id, app_secret, app_token):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.verify_ssl = os.getenv("FEISHU_VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no", "off"}
        self.session = requests.Session()
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST", "PUT", "DELETE"),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.token = self._get_tenant_access_token()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _get_tenant_access_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        response = self.session.post(url, json=payload, timeout=20, verify=self.verify_ssl)
        return response.json().get("tenant_access_token")

    def create_field(self, table_id, field_data):
        table_id = _normalize_table_id(table_id)
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields"
        
        # 构建基础 Payload
        payload = {
            "field_name": field_data["name"],
            "type": TYPE_MAP.get(field_data["type"], 1)
        }

        # 处理选择项
        if field_data["type"] in ["single_select", "multi_select"] and "options" in field_data:
            payload["property"] = {"options": [{"name": opt} for opt in field_data["options"]]}
        
        # 处理关联记录
        elif field_data["type"] == "link":
            target_table_name = field_data["link"]["table"]
            target_table_id = _normalize_table_id(TABLE_MAP.get(target_table_name, ""))
            if target_table_id:
                payload["property"] = {
                    "table_id": target_table_id,
                    "multiple": field_data["link"].get("relation") == "many_to_many"
                }
            else:
                print(f"跳过关联字段 {field_data['name']}：未找到目标表 ID")
                return

        response = self.session.post(url, headers=self.headers, json=payload, timeout=20, verify=self.verify_ssl)
        data = response.json()
        # 字段已存在时跳过（幂等）
        msg = str(data.get("msg") or "")
        if "FieldNameDuplicated" in msg:
            return {"code": 0, "msg": "FieldNameDuplicated", "_skipped": True}
        return data

# ================= 业务逻辑区 =================

# 你的 JSON Schema 数据
schema_data = {
  "base": "HUSTByteDance",
  "tables": [
    {
      "name": "Demands",
      "display_name": "采购需求表",
      "primary_field": "demand_code",
      "fields": [
        { "name": "demand_code", "type": "text" },
        { "name": "source_instruction", "type": "text" },
        { "name": "requester", "type": "text" },
        { "name": "department", "type": "single_select", "options": ["研发", "生产", "采购", "运营", "财务", "行政", "其他"] },
        { "name": "category", "type": "single_select", "options": ["原材料", "辅料", "包装", "备品备件", "设备", "服务", "其他"] },
        { "name": "item_name", "type": "text" },
        { "name": "spec", "type": "text" },
        { "name": "quantity", "type": "number" },
        { "name": "uom", "type": "single_select", "options": ["件", "个", "台", "套", "箱", "kg", "g", "m", "㎡", "L", "其他"] },
        { "name": "budget_amount", "type": "number" },
        { "name": "currency", "type": "single_select", "options": ["CNY", "USD", "EUR", "HKD", "JPY"] },
        { "name": "priority", "type": "single_select", "options": ["P0", "P1", "P2", "P3"] },
        { "name": "need_by_date", "type": "date" },
        { "name": "status", "type": "single_select", "options": ["待规划", "待辩论", "待审批", "待主管审批", "待采购确认", "待运输审批", "待下单确认", "已选型", "已询价", "已下单", "已到货", "已关闭", "已取消", "已驳回"] },
        { "name": "recommended_suppliers", "type": "link", "link": { "table": "Suppliers", "relation": "many_to_many" } },
        { "name": "notes", "type": "text" },
        { "name": "created_at", "type": "date" },
        { "name": "updated_at", "type": "date" },
        { "name": "demand_summary", "type": "formula" }
      ]
    },
    {
      "name": "Suppliers",
      "display_name": "供应商库",
      "primary_field": "supplier_name",
      "fields": [
        { "name": "supplier_name", "type": "text" },
        { "name": "supplier_code", "type": "text" },
        { "name": "credit_score", "type": "number" },
        { "name": "quality_score", "type": "number" },
        { "name": "cost_score", "type": "number" },
        { "name": "lead_time_days", "type": "number" },
        { "name": "user_rating", "type": "number" },
        { "name": "risk_level", "type": "single_select", "options": ["低", "中", "高"] },
        { "name": "user_review_detail", "type": "text" },
        { "name": "main_business", "type": "multi_select", "options": ["原材料", "辅料", "包装", "备品备件", "设备", "服务", "其他"] },
        { "name": "supplier_level", "type": "single_select", "options": ["A", "B", "C", "D"] },
        { "name": "status", "type": "single_select", "options": ["启用", "禁用", "黑名单"] },
        { "name": "contact_name", "type": "text" },
        { "name": "contact_phone", "type": "text" },
        { "name": "contact_email", "type": "text" },
        { "name": "recommended_for_demands", "type": "link", "link": { "table": "Demands", "relation": "many_to_many" } },
        { "name": "created_at", "type": "date" },
        { "name": "updated_at", "type": "date" },
        { "name": "supplier_profile", "type": "formula" }
      ]
    },
    {
      "name": "Orders",
      "display_name": "采购订单表",
      "primary_field": "order_code",
      "fields": [
        { "name": "order_code", "type": "text" },
        { "name": "demand", "type": "link", "link": { "table": "Demands", "relation": "one_to_one" } },
        { "name": "supplier", "type": "link", "link": { "table": "Suppliers", "relation": "many_to_one" } },
        { "name": "order_amount", "type": "number" },
        { "name": "currency", "type": "single_select", "options": ["CNY", "USD", "EUR", "HKD", "JPY"] },
        { "name": "order_status", "type": "single_select", "options": ["草稿", "已确认", "已取消", "已完成"] },
        { "name": "logistics_status", "type": "single_select", "options": ["待发货", "运输中", "异常", "已送达"] },
        { "name": "expected_delivery_date", "type": "date" },
        { "name": "tracking_no", "type": "text" },
        { "name": "exception_reason", "type": "single_select", "options": ["无", "延迟", "丢失", "破损", "清关", "地址问题", "其他"] },
        { "name": "created_at", "type": "date" },
        { "name": "updated_at", "type": "date" },
        { "name": "order_brief", "type": "formula" }
      ]
    },
    {
      "name": "Audit_Logs",
      "display_name": "运行日志表",
      "primary_field": "log_id",
      "fields": [
        { "name": "log_id", "type": "text" },
        { "name": "timestamp", "type": "date" },
        { "name": "agent_name", "type": "single_select", "options": ["planner_agent", "sourcing_agent", "sourcing_auditor", "buyer_agent", "auditor_agent", "tracker_agent", "strategy_agent", "system"] },
        { "name": "action", "type": "single_select", "options": ["create", "read", "update", "recommend", "select", "quote", "order", "ship", "deliver", "error"] },
        { "name": "target_table", "type": "single_select", "options": ["Demands", "Suppliers", "Orders", "Audit_Logs"] },
        { "name": "target_record_id", "type": "text" },
        { "name": "demand", "type": "link", "link": { "table": "Demands", "relation": "many_to_one" } },
        { "name": "supplier", "type": "link", "link": { "table": "Suppliers", "relation": "many_to_one" } },
        { "name": "order", "type": "link", "link": { "table": "Orders", "relation": "many_to_one" } },
        { "name": "result", "type": "single_select", "options": ["success", "fail", "skipped"] },
        { "name": "error_code", "type": "text" },
        { "name": "message", "type": "text" },
        { "name": "detail_json", "type": "text" }
      ]
    },
    {
      "name": "Personnel",
      "display_name": "负责人表",
      "primary_field": "staff_id",
      "fields": [
        { "name": "staff_id", "type": "text" },
        { "name": "name", "type": "text" },
        { "name": "feishu_open_id", "type": "text" },
        { "name": "department", "type": "text" },
        { "name": "role", "type": "single_select", "options": ["Approver", "Purchaser", "Logistics", "Finance", "Other"] },
        { "name": "managed_categories", "type": "multi_select", "options": ["电子料", "光学件", "原材料", "辅料", "包装", "设备", "服务", "其他"] },
        { "name": "created_at", "type": "date" },
        { "name": "updated_at", "type": "date" }
      ]
    },
    {
      "name": "Debate_History",
      "display_name": "决策辩论记录表",
      "primary_field": "debate_id",
      "fields": [
        { "name": "debate_id", "type": "text" },
        { "name": "demand_id", "type": "link", "link": { "table": "Demands", "relation": "many_to_one" } },
        { "name": "agent_identity", "type": "single_select", "options": ["成本专家", "质量专家", "供应链风险官", "其他"] },
        { "name": "stance", "type": "text" },
        { "name": "argument_content", "type": "text" },
        { "name": "score_impact", "type": "number" },
        { "name": "timestamp", "type": "date" }
      ]
    },
    {
      "name": "Business_Rules",
      "display_name": "业务映射规则表",
      "primary_field": "rule_type",
      "fields": [
        { "name": "rule_type", "type": "single_select", "options": ["审批阈值", "优先级定义", "其他"] },
        { "name": "condition_key", "type": "text" },
        { "name": "condition_value", "type": "text" },
        { "name": "target_action", "type": "text" },
        { "name": "is_active", "type": "single_select", "options": ["true", "false"] },
        { "name": "updated_at", "type": "date" }
      ]
    },
    {
      "name": "Interaction_Memory",
      "display_name": "会话记忆与上下文表",
      "primary_field": "message_id",
      "fields": [
        { "name": "message_id", "type": "text" },
        { "name": "chat_id", "type": "text" },
        { "name": "user_id", "type": "text" },
        { "name": "related_record_id", "type": "text" },
        { "name": "summary", "type": "text" },
        { "name": "last_interaction", "type": "date" }
      ]
    }
  ],
  "relations": [
    { "from": "Demands.recommended_suppliers", "to": "Suppliers.recommended_for_demands", "type": "many_to_many" },
    { "from": "Orders.demand", "to": "Demands", "type": "one_to_one" }
  ]
}

creator = BitableFieldCreator(APP_ID, APP_SECRET, APP_TOKEN)

def run_setup(schema):
    # 第一遍：创建非关联、非公式字段
    print("--- 正在创建基础字段 ---")
    for table_cfg in schema["tables"]:
        t_id = TABLE_MAP.get(table_cfg["name"])
        if not t_id:
            print(f"跳过表[{table_cfg['display_name']}]：未配置 table_id")
            continue
        for field in table_cfg["fields"]:
            # 跳过主键（通常建表时已自动生成第一个字段）和 复杂字段
            if field["name"] == table_cfg["primary_field"] or field["type"] in ["link", "formula"]:
                continue
            
            res = creator.create_field(t_id, field)
            status = "成功" if res.get("code") == 0 else f"失败({res.get('msg')})"
            print(f"表[{table_cfg['display_name']}] 创建字段[{field['name']}]: {status}")
            time.sleep(0.5) # 避开限流

    # 第二遍：创建关联记录字段
    print("\n--- 正在建立表间关联 ---")
    for table_cfg in schema["tables"]:
        t_id = TABLE_MAP.get(table_cfg["name"])
        if not t_id:
            continue
        for field in table_cfg["fields"]:
            if field["type"] == "link":
                res = creator.create_field(t_id, field)
                status = "成功" if res.get("code") == 0 else f"失败({res.get('msg')})"
                print(f"表[{table_cfg['display_name']}] 创建关联[{field['name']}]: {status}")
                time.sleep(0.5)

if __name__ == "__main__":
    # 将你提供的 JSON 赋值给 schema_data 后运行
    run_setup(schema_data)
    # pass
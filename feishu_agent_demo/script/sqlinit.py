import requests
import time
import json

# ================= 配置区 =================
APP_ID = "cli_a9660be8fc615cdb"
APP_SECRET = "rmnLNYmsUIgn2OOx8Yjsdc3crvR7TILB"
APP_TOKEN = "IMWGbbzIlay7AXsiEooch4bnnY9"

# 之前获取的 Table ID 映射
TABLE_MAP = {
    "Demands": "tblttFySYyrRGgrV",
    "Orders": "tblIeEj0nwODLH8o",
    "Suppliers": "tblPHfNK7UejrktF",
    "Audit_Logs": "tblB0ulWocd4vrgF"
}

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
        self.token = self._get_tenant_access_token()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8"
        }

    def _get_tenant_access_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        response = requests.post(url, json=payload)
        return response.json().get("tenant_access_token")

    def create_field(self, table_id, field_data):
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
            target_table_id = TABLE_MAP.get(target_table_name)
            if target_table_id:
                payload["property"] = {
                    "table_id": target_table_id,
                    "multiple": field_data["link"].get("relation") == "many_to_many"
                }
            else:
                print(f"跳过关联字段 {field_data['name']}：未找到目标表 ID")
                return

        response = requests.post(url, headers=self.headers, json=payload)
        return response.json()

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
        { "name": "status", "type": "single_select", "options": ["待规划", "已选型", "已询价", "已下单", "已到货", "已关闭", "已取消"] },
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
        { "name": "agent_name", "type": "single_select", "options": ["planner_agent", "sourcing_agent", "buyer_agent", "auditor_agent", "system"] },
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
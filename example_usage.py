"""外部 Python 程序调用示例。"""

from api_client import ApiClient, insert_response_by_uri


client = ApiClient.from_config_file(
    api_key="请替换为真实的 API Key",
    config_file="api_config.json",
    timeout=20,
)

# 接口一：传入 query 参数。
users_response = client.call(
    "查询用户",
    query={"page": 1, "page_size": 20, "active": True},
)
print(users_response.data)

# 接口二：传入接口专属 header 与 query；公共 x-api-key 会自动加入且不可被覆盖。
orders_response = client.call(
    "查询订单",
    headers={"X-Request-Id": "request-001"},
    query={"status": "paid", "created_after": "2026-01-01"},
)
print(orders_response.status_code)

# 接口三：仅传 query 参数。
products_response = client.call("查询商品", query={"category": "book"})

# 接口四：URL 模板中的 path 参数 order_id 会经过 URL 编码。
order_response = client.call("查询单个订单", path={"order_id": "ORD/10001"})

# 将响应插入 MongoDB。执行此段前需安装依赖：pip install pymongo
insert_result = insert_response_by_uri(
    mongo_uri="mongodb://localhost:27017",
    database="api_data",
    collection_name="responses",
    response=order_response,
    extra_document={"source": "example_usage"},
)
print(f"已插入 MongoDB，文档 ID：{insert_result.inserted_id}")

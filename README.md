# 四接口 GET 请求客户端

该程序提供一个可由外部 Python 程序 `import` 的接口客户端。它固定承载 **4 个** GET 接口，并支持：

- 通过 JSON 文件配置基础地址和四个 URL；URL 可使用 `{参数名}` 定义 path 参数。
- 由调用方传入 `query`、接口专属 `header`、`path` 参数。
- 自动加入公共请求头 `x-api-key`；调用方额外传入同名 header 也不会覆盖该公共密钥。
- 标准化返回状态码、实际请求 URL、响应头和 JSON/文本响应体。
- 将响应插入现有 MongoDB Collection，或按 MongoDB URI 临时连接后写入。

## 文件

| 文件 | 用途 |
| --- | --- |
| `api_client.py` | 可被外部程序导入的客户端模块 |
| `api_config.example.json` | 四接口 URL 配置模板 |
| `example_usage.py` | 调用及写入 MongoDB 的完整示例 |

## 配置接口

复制 `api_config.example.json` 为 `api_config.json`，填写真实服务地址与四个接口路径：

```powershell
Copy-Item api_config.example.json api_config.json
```

配置必须恰好具有四个 `endpoints`。每个接口的 `url` 可以是：

- 相对于 `base_url` 的路径，例如 `/v1/orders/{order_id}`；
- 完整地址，例如 `https://other-api.example.com/v1/orders/{order_id}`。

`{order_id}` 表示 path 参数占位符。调用时传入 `path={"order_id": "ORD/10001"}`，值会自动进行 URL 编码。

## 在外部程序中调用

```python
from api_client import ApiClient

client = ApiClient.from_config_file(
    api_key="真实 API Key",
    config_file="api_config.json",
)

response = client.call(
    "查询单个订单",
    path={"order_id": "ORD-10001"},
    query={"include": "items"},
    headers={"X-Request-Id": "request-001"},
)

print(response.status_code)
print(response.data)
```

也可不使用配置文件，直接通过字典传入四个 URL：

```python
from api_client import ApiClient

client = ApiClient(
    api_key="真实 API Key",
    base_url="https://api.example.com",
    endpoints={
        "接口一": "/v1/users",
        "接口二": "/v1/orders",
        "接口三": "/v1/products",
        "接口四": "/v1/orders/{order_id}",
    },
)
```

## MongoDB 写入

### 传入已有 Collection

应用已自行管理 MongoDB 连接时，推荐传入已有的 `Collection`：

```python
from pymongo import MongoClient

mongo_client = MongoClient("mongodb://localhost:27017")
collection = mongo_client["api_data"]["responses"]
response, result = client.call_and_insert(
    "查询用户",
    collection,
    query={"page": 1},
    extra_document={"task_id": "task-001"},
)
print(result.inserted_id)
```

### 传入 MongoDB URI

先安装依赖：

```powershell
pip install pymongo
```

再调用：

```python
from api_client import insert_response_by_uri

result = insert_response_by_uri(
    mongo_uri="mongodb://localhost:27017",
    database="api_data",
    collection_name="responses",
    response=response,
)
```

写入文档包括接口名称、实际请求 URL、HTTP 状态码、响应头、响应体 `data` 以及 UTC 时间 `fetched_at`。`extra_document` 可用于附加业务字段。

## 错误处理

网络连接失败或非 2xx HTTP 状态会抛出 `ApiRequestError`。异常对象含有 `status_code` 和 `body`（如服务端返回响应体）。配置问题或其他客户端错误会抛出 `ApiClientError`。

```python
from api_client import ApiRequestError

try:
    response = client.call("查询用户", query={"page": 1})
except ApiRequestError as error:
    print(error.status_code, error.body)
```

"""可配置的 GET 接口客户端，支持公共 API Key、路径/查询/请求头参数及 MongoDB 写入。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


JsonValue = Any


class ApiClientError(Exception):
    """接口客户端基础异常。"""


class ApiRequestError(ApiClientError):
    """接口请求失败时抛出。"""

    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class EndpointConfig:
    """单个 GET 接口的配置。url 可为完整 URL 或相对 base_url 的路径模板。"""

    name: str
    url: str


@dataclass(frozen=True)
class ApiResponse:
    """一次接口调用的标准化响应。"""

    endpoint: str
    url: str
    status_code: int
    headers: Mapping[str, str]
    data: JsonValue


def load_endpoint_config(config_file: str | Path) -> tuple[str, dict[str, EndpointConfig]]:
    """读取 JSON 配置文件，返回基础 URL 与接口配置。"""
    try:
        content = Path(config_file).read_text(encoding="utf-8")
        config = json.loads(content)
    except OSError as error:
        raise ApiClientError(f"无法读取接口配置文件：{config_file}") from error
    except json.JSONDecodeError as error:
        raise ApiClientError(f"接口配置文件不是有效的 JSON：{config_file}") from error

    base_url = config.get("base_url", "")
    endpoint_items = config.get("endpoints")
    if not isinstance(base_url, str) or not isinstance(endpoint_items, Mapping):
        raise ApiClientError("接口配置必须包含字符串 base_url 和对象 endpoints")

    endpoints: dict[str, EndpointConfig] = {}
    for name, value in endpoint_items.items():
        if not isinstance(name, str) or not isinstance(value, Mapping) or not isinstance(value.get("url"), str):
            raise ApiClientError("每个接口必须配置名称和字符串类型的 url")
        endpoints[name] = EndpointConfig(name=name, url=value["url"])

    if len(endpoints) != 4:
        raise ApiClientError(f"当前配置包含 {len(endpoints)} 个接口；本程序要求恰好配置 4 个接口")
    return base_url, endpoints


class ApiClient:
    """调用配置中四个 GET 接口的客户端。"""

    def __init__(
        self,
        api_key: str,
        endpoints: Mapping[str, EndpointConfig | str],
        *,
        base_url: str = "",
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key 不能为空")
        if len(endpoints) != 4:
            raise ValueError(f"endpoints 必须恰好包含 4 个接口，当前为 {len(endpoints)} 个")
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")

        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._endpoints = {
            name: config if isinstance(config, EndpointConfig) else EndpointConfig(name=name, url=config)
            for name, config in endpoints.items()
        }

    @classmethod
    def from_config_file(
        cls,
        api_key: str,
        config_file: str | Path,
        *,
        timeout: float = 30.0,
    ) -> "ApiClient":
        """从 JSON 文件创建客户端。"""
        base_url, endpoints = load_endpoint_config(config_file)
        return cls(api_key, endpoints, base_url=base_url, timeout=timeout)

    def call(
        self,
        endpoint: str,
        *,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        path: Mapping[str, Any] | None = None,
    ) -> ApiResponse:
        """调用指定接口；query、headers、path 均由调用方按需传入。"""
        config = self._endpoints.get(endpoint)
        if config is None:
            available = "、".join(self._endpoints)
            raise ApiClientError(f"未找到接口“{endpoint}”，可用接口：{available}")

        url = self._build_url(config.url, path or {}, query or {})
        request_headers: MutableMapping[str, str] = {
            "Accept": "application/json",
            **dict(headers or {}),
            "x-api-key": self._api_key,
        }
        request = Request(url=url, headers=dict(request_headers), method="GET")

        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw_body = response.read()
                response_headers = dict(response.headers.items())
                return ApiResponse(
                    endpoint=endpoint,
                    url=url,
                    status_code=response.status,
                    headers=response_headers,
                    data=self._decode_body(raw_body, response_headers),
                )
        except HTTPError as error:
            raw_body = error.read()
            body = self._decode_body(raw_body, dict(error.headers.items()) if error.headers else {})
            raise ApiRequestError(
                f"接口“{endpoint}”请求失败，HTTP 状态码：{error.code}",
                status_code=error.code,
                body=body,
            ) from error
        except URLError as error:
            raise ApiRequestError(f"接口“{endpoint}”无法连接：{error.reason}") from error

    def call_and_insert(
        self,
        endpoint: str,
        collection: Any,
        *,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        path: Mapping[str, Any] | None = None,
        extra_document: Mapping[str, Any] | None = None,
    ) -> tuple[ApiResponse, Any]:
        """调用接口并将标准化响应插入已创建的 MongoDB Collection。"""
        response = self.call(endpoint, query=query, headers=headers, path=path)
        result = insert_response(collection, response, extra_document=extra_document)
        return response, result

    def _build_url(self, configured_url: str, path: Mapping[str, Any], query: Mapping[str, Any]) -> str:
        try:
            encoded_path = {key: quote(str(value), safe="") for key, value in path.items()}
            url = configured_url.format_map(_PathValues(encoded_path))
        except KeyError as error:
            raise ApiClientError(f"接口 URL 缺少 path 参数：{error.args[0]}") from error

        if not url.startswith(("https://", "http://")):
            if not self._base_url:
                raise ApiClientError("相对接口 URL 需要配置 base_url")
            url = urljoin(self._base_url.rstrip("/") + "/", url.lstrip("/"))

        if query:
            normalized_query = {
                key: [self._query_value(item) for item in value] if isinstance(value, (list, tuple)) else self._query_value(value)
                for key, value in query.items()
                if value is not None
            }
            separator = "&" if "?" in url else "?"
            encoded_query = urlencode(normalized_query, doseq=True)
            if encoded_query:
                url = f"{url}{separator}{encoded_query}"
        return url

    @staticmethod
    def _query_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _decode_body(raw_body: bytes, headers: Mapping[str, str]) -> JsonValue:
        if not raw_body:
            return None
        text = raw_body.decode("utf-8", errors="replace")
        content_type = next((value for key, value in headers.items() if key.lower() == "content-type"), "")
        if "json" in content_type.lower():
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


class _PathValues(dict[str, str]):
    """在 URL 模板缺少参数时提供清晰错误。"""

    def __missing__(self, key: str) -> str:
        raise KeyError(key)


def response_to_document(
    response: ApiResponse,
    *,
    extra_document: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """将接口响应转换为可写入 MongoDB 的文档。"""
    document: dict[str, Any] = {
        "endpoint": response.endpoint,
        "url": response.url,
        "status_code": response.status_code,
        "response_headers": dict(response.headers),
        "data": response.data,
        "fetched_at": datetime.now(timezone.utc),
    }
    if extra_document:
        document.update(extra_document)
    return document


def insert_response(
    collection: Any,
    response: ApiResponse,
    *,
    extra_document: Mapping[str, Any] | None = None,
) -> Any:
    """将响应插入 pymongo Collection；collection 必须提供 insert_one 方法。"""
    if not hasattr(collection, "insert_one"):
        raise TypeError("collection 必须是提供 insert_one 方法的 MongoDB Collection")
    return collection.insert_one(response_to_document(response, extra_document=extra_document))


def insert_response_by_uri(
    mongo_uri: str,
    database: str,
    collection_name: str,
    response: ApiResponse,
    *,
    extra_document: Mapping[str, Any] | None = None,
) -> Any:
    """使用 MongoDB 连接串创建短连接并插入响应；需安装 pymongo。"""
    try:
        from pymongo import MongoClient
    except ImportError as error:
        raise ApiClientError("使用 MongoDB URI 写入前，请执行：pip install pymongo") from error

    client = MongoClient(mongo_uri)
    try:
        collection = client[database][collection_name]
        return insert_response(collection, response, extra_document=extra_document)
    finally:
        client.close()

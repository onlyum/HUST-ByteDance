from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple, Union

import requests


Json = Dict[str, Any]


class FeishuHttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None, response_json: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_json = response_json


class FeishuRateLimitedError(FeishuHttpError):
    pass


@dataclass
class _TokenState:
    token: str
    expires_at_epoch: float


class FeishuBitableToolbox:
    """
    A minimal, requests-based Feishu Bitable toolbox:
    - tenant_access_token auto fetch + cache + refresh
    - Bitable record CRUD wrappers
    - 429 exponential backoff retry
    - Link(User/Record) field normalization helpers
    """

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        base_url: str = "https://open.feishu.cn",
        timeout_seconds: float = 15.0,
        token_refresh_skew_seconds: float = 60.0,
        max_retries_429: int = 6,
        backoff_base_seconds: float = 0.5,
        backoff_cap_seconds: float = 8.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._token_refresh_skew = token_refresh_skew_seconds
        self._max_retries_429 = max_retries_429
        self._backoff_base = backoff_base_seconds
        self._backoff_cap = backoff_cap_seconds
        self._session = session or requests.Session()
        self._token_state: Optional[_TokenState] = None

    # -------------------------
    # Auth (tenant access token)
    # -------------------------
    def _get_tenant_access_token(self) -> str:
        now = time.time()
        if self._token_state and now < (self._token_state.expires_at_epoch - self._token_refresh_skew):
            return self._token_state.token

        url = f"{self._base_url}/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self._app_id, "app_secret": self._app_secret}
        resp = self._session.post(url, json=payload, timeout=self._timeout)
        data = self._safe_json(resp)
        if resp.status_code != 200 or not isinstance(data, dict) or data.get("code", 0) != 0:
            raise FeishuHttpError(
                "Failed to get tenant_access_token",
                status_code=resp.status_code,
                response_json=data,
            )

        token = str(data["tenant_access_token"])
        expire = int(data.get("expire", 0))  # seconds
        expires_at = now + max(0, expire)
        self._token_state = _TokenState(token=token, expires_at_epoch=expires_at)
        return token

    # -------------
    # HTTP utilities
    # -------------
    def _safe_json(self, resp: requests.Response) -> Any:
        try:
            return resp.json()
        except Exception:
            return {"_raw_text": resp.text}

    def _auth_headers(self) -> Dict[str, str]:
        token = self._get_tenant_access_token()
        return {"Authorization": f"Bearer {token}"}

    def _parse_retry_after_seconds(self, resp: requests.Response) -> Optional[float]:
        value = resp.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _sleep_backoff(self, attempt: int, retry_after_seconds: Optional[float]) -> None:
        if retry_after_seconds is not None and retry_after_seconds > 0:
            time.sleep(min(retry_after_seconds, self._backoff_cap))
            return

        # full jitter exponential backoff
        cap = self._backoff_cap
        base = self._backoff_base
        upper = min(cap, base * (2 ** attempt))
        time.sleep(random.uniform(0.0, upper))

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
        allow_retry_429: bool = True,
    ) -> Json:
        url = f"{self._base_url}{path}"

        last_error: Optional[Exception] = None
        retries = self._max_retries_429 if allow_retry_429 else 0
        for attempt in range(retries + 1):
            headers: Dict[str, str] = {}
            headers.update(self._auth_headers())
            headers["Content-Type"] = "application/json; charset=utf-8"
            if extra_headers:
                headers.update(dict(extra_headers))

            try:
                resp = self._session.request(
                    method=method.upper(),
                    url=url,
                    params=dict(params) if params else None,
                    json=dict(json_body) if json_body else None,
                    headers=headers,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                # network errors: do not silently retry unless explicitly needed
                break

            if resp.status_code == 429 and allow_retry_429 and attempt < retries:
                self._sleep_backoff(attempt=attempt, retry_after_seconds=self._parse_retry_after_seconds(resp))
                continue

            data = self._safe_json(resp)

            # Feishu OpenAPI uses HTTP 200 with {code!=0} for business errors.
            if resp.status_code >= 400:
                if resp.status_code == 429:
                    raise FeishuRateLimitedError(
                        "Rate limited (HTTP 429)",
                        status_code=resp.status_code,
                        response_json=data,
                    )
                raise FeishuHttpError(
                    f"HTTP error: {resp.status_code}",
                    status_code=resp.status_code,
                    response_json=data,
                )

            if isinstance(data, dict) and data.get("code", 0) != 0:
                raise FeishuHttpError(
                    f"Feishu OpenAPI error: code={data.get('code')} msg={data.get('msg')}",
                    status_code=resp.status_code,
                    response_json=data,
                )

            if not isinstance(data, dict):
                raise FeishuHttpError(
                    "Unexpected response json type",
                    status_code=resp.status_code,
                    response_json=data,
                )
            return data

        if last_error:
            raise FeishuHttpError(f"Request failed: {last_error}") from last_error
        raise FeishuHttpError("Request failed")

    # -----------------------
    # Complex field adapters
    # -----------------------
    @staticmethod
    def _normalize_link_value(value: Any) -> Any:
        """
        Normalize Bitable Link field value for write operations.
        Feishu Bitable expects link values as a list of record_id strings: ["recxxx", ...]

        Accepts:
        - "recxxx"
        - ["rec1", "rec2"]
        - [{"record_id": "rec1"}, {"record_id": "rec2"}]
        - {"record_id": "rec1"}
        - {"record_ids": ["rec1", "rec2"]}
        """
        if value is None:
            return None
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            if "record_id" in value and isinstance(value["record_id"], str):
                return [value["record_id"]]
            if "record_ids" in value and isinstance(value["record_ids"], list):
                record_ids = [x for x in value["record_ids"] if isinstance(x, str)]
                return record_ids
            return value
        if isinstance(value, list):
            if all(isinstance(x, str) for x in value):
                return value
            if all(isinstance(x, dict) for x in value):
                out: List[str] = []
                for obj in value:
                    rid = obj.get("record_id")
                    if isinstance(rid, str):
                        out.append(rid)
                    elif "record_ids" in obj and isinstance(obj["record_ids"], list):
                        out.extend(x for x in obj["record_ids"] if isinstance(x, str))
                return out
            return value
        return value

    @staticmethod
    def _normalize_user_value(value: Any, *, user_id_key: str = "id") -> Any:
        """
        Normalize Bitable User field value to a list of objects with a stable id key.

        Accepts:
        - "ou_xxx" (or open_id/union_id depending on user_id_key)
        - ["ou_1", "ou_2"]
        - [{"id": "ou_1"}, {"id": "ou_2"}]
        """
        if value is None:
            return None
        if isinstance(value, str):
            return [{user_id_key: value}]
        if isinstance(value, dict):
            if user_id_key in value and isinstance(value[user_id_key], str):
                return [{user_id_key: value[user_id_key]}]
            return value
        if isinstance(value, list):
            if all(isinstance(x, str) for x in value):
                return [{user_id_key: x} for x in value]
            if all(isinstance(x, dict) for x in value):
                out: List[Dict[str, str]] = []
                for obj in value:
                    v = obj.get(user_id_key)
                    if isinstance(v, str):
                        out.append({user_id_key: v})
                return out
            return value
        return value

    def normalize_fields(
        self,
        fields: Mapping[str, Any],
        *,
        link_fields: Optional[Iterable[str]] = None,
        user_fields: Optional[Iterable[str]] = None,
        user_id_key: str = "id",
    ) -> Dict[str, Any]:
        """
        Normalize fields for write operations.

        link_fields: names of Bitable "Link" columns.
        user_fields: names of Bitable "User/People" columns.
        """
        link_set: Set[str] = set(link_fields or [])
        user_set: Set[str] = set(user_fields or [])

        normalized: Dict[str, Any] = dict(fields)
        for k in link_set:
            if k in normalized:
                normalized[k] = self._normalize_link_value(normalized[k])
        for k in user_set:
            if k in normalized:
                normalized[k] = self._normalize_user_value(normalized[k], user_id_key=user_id_key)
        return normalized

    # ----------------
    # Bitable CRUD API
    # ----------------
    def list_table_fields(
        self,
        *,
        app_token: str,
        table_id: str,
        page_size: int = 200,
        page_token: Optional[str] = None,
    ) -> Tuple[List[Json], Optional[str], bool]:
        """
        Returns: (items, next_page_token, has_more)
        Each item contains field meta (including 'field_name' and 'field_id').
        """
        params: Dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        data = self._request(
            "GET",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            params=params,
        )
        payload = data.get("data") or {}
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise FeishuHttpError("Unexpected field items type", response_json=data)
        next_token = payload.get("page_token") if isinstance(payload.get("page_token"), str) else None
        has_more = bool(payload.get("has_more"))
        return items, next_token, has_more

    def get_table_field_names(self, *, app_token: str, table_id: str, max_pages: int = 10) -> Set[str]:
        names: Set[str] = set()
        page_token: Optional[str] = None
        pages = 0
        while True:
            items, page_token, has_more = self.list_table_fields(
                app_token=app_token,
                table_id=table_id,
                page_size=200,
                page_token=page_token,
            )
            for it in items:
                if isinstance(it, dict) and isinstance(it.get("field_name"), str):
                    names.add(it["field_name"])
            pages += 1
            if pages >= max_pages:
                break
            if not has_more or not page_token:
                break
        return names

    def add_record(
        self,
        *,
        app_token: str,
        table_id: str,
        fields: Mapping[str, Any],
        link_fields: Optional[Iterable[str]] = None,
        user_fields: Optional[Iterable[str]] = None,
        user_id_key: str = "id",
    ) -> str:
        body = {"fields": self.normalize_fields(fields, link_fields=link_fields, user_fields=user_fields, user_id_key=user_id_key)}
        data = self._request(
            "POST",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            json_body=body,
        )
        record = (data.get("data") or {}).get("record") or {}
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise FeishuHttpError("Missing record_id in create response", response_json=data)
        return record_id

    def update_record(
        self,
        *,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: Mapping[str, Any],
        link_fields: Optional[Iterable[str]] = None,
        user_fields: Optional[Iterable[str]] = None,
        user_id_key: str = "id",
    ) -> None:
        body = {"fields": self.normalize_fields(fields, link_fields=link_fields, user_fields=user_fields, user_id_key=user_id_key)}
        self._request(
            "PUT",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
            json_body=body,
        )

    def delete_record(self, *, app_token: str, table_id: str, record_id: str) -> None:
        self._request(
            "DELETE",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        )

    def get_record(self, *, app_token: str, table_id: str, record_id: str) -> Json:
        data = self._request(
            "GET",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        )
        record = (data.get("data") or {}).get("record")
        if not isinstance(record, dict):
            raise FeishuHttpError("Missing record in get response", response_json=data)
        return record

    def list_records(
        self,
        *,
        app_token: str,
        table_id: str,
        page_size: int = 100,
        page_token: Optional[str] = None,
        filter_formula: Optional[str] = None,
        sort: Optional[str] = None,
        view_id: Optional[str] = None,
        fields: Optional[Sequence[str]] = None,
    ) -> Tuple[List[Json], Optional[str], bool]:
        """
        Returns: (items, next_page_token, has_more)
        """
        params: Dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        if filter_formula:
            params["filter"] = filter_formula
        if sort:
            params["sort"] = sort
        if view_id:
            params["view_id"] = view_id
        if fields:
            params["fields"] = ",".join(fields)

        data = self._request(
            "GET",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            params=params,
        )

        payload = data.get("data") or {}
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise FeishuHttpError("Unexpected items type", response_json=data)
        next_token = payload.get("page_token") if isinstance(payload.get("page_token"), str) else None
        has_more = bool(payload.get("has_more"))
        return items, next_token, has_more

    def iter_records(
        self,
        *,
        app_token: str,
        table_id: str,
        page_size: int = 100,
        filter_formula: Optional[str] = None,
        sort: Optional[str] = None,
        view_id: Optional[str] = None,
        fields: Optional[Sequence[str]] = None,
        max_pages: Optional[int] = None,
    ) -> Iterable[Json]:
        page_token: Optional[str] = None
        pages = 0
        while True:
            items, page_token, has_more = self.list_records(
                app_token=app_token,
                table_id=table_id,
                page_size=page_size,
                page_token=page_token,
                filter_formula=filter_formula,
                sort=sort,
                view_id=view_id,
                fields=fields,
            )
            for it in items:
                if isinstance(it, dict):
                    yield it

            pages += 1
            if max_pages is not None and pages >= max_pages:
                return
            if not has_more or not page_token:
                return


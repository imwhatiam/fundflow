"""开盘啦 HTTP 请求：POST 表单 + 响应解码，不承担重试或持久化。"""

import json
import re

import requests

from .constants import HEADERS, KAIPANLA_HQ_URL


def decode_response_text(text):
    """还原 App 接口的 raw_unicode_escape 编码并剔除控制字符。"""
    decoded = text.encode("utf-8").decode("raw_unicode_escape")
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", decoded)
    return json.loads(cleaned)


class KaipanlaHttpClient:
    """发送单次 POST 请求；失败时向调用方抛出 requests/JSON 异常。"""

    def __init__(self, timeout=15, session=None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def post_json(self, params, *, timeout=None):
        """发送单次请求并解析 JSON，向调用方抛出异常。"""
        body = "&".join(f"{k}={v}" for k, v in params.items()) + "&"
        response = self.session.post(
            KAIPANLA_HQ_URL,
            data=body,
            headers=HEADERS,
            timeout=timeout or self.timeout,
        )
        response.raise_for_status()
        return decode_response_text(response.text)

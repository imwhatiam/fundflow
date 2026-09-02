"""东方财富 HTTP 请求；不承担重试、间隔或数据持久化。"""

import threading

import requests

from .constants import EASTMONEY_CLIST_URL, HEADERS


class EastmoneyHttpClient:
    """发送单次请求，并在连接错误后重建自有 Session。"""

    def __init__(self, timeout=10, session=None):
        self.timeout = timeout
        self._owns_session = session is None
        self._provided_session = session
        self._session_local = threading.local()

    def get_json(self, params, *, timeout):
        """发送单次 GET 请求，失败时向调用方抛出 requests/JSON 异常。"""
        session = self._get_session()
        response = session.get(
            EASTMONEY_CLIST_URL,
            params=params,
            headers=HEADERS,
            timeout=min(self.timeout, timeout),
        )
        response.raise_for_status()
        return response.json()

    def rebuild_session_after_connection_error(self):
        """仅替换当前线程的自有 Session；外部提供的 Session 不被关闭。"""
        if not self._owns_session:
            return

        session = getattr(self._session_local, "session", None)
        if session is not None:
            session.close()
        self._session_local.session = requests.Session()

    def _get_session(self):
        if not self._owns_session:
            return self._provided_session

        session = getattr(self._session_local, "session", None)
        if session is None:
            session = requests.Session()
            self._session_local.session = session
        return session

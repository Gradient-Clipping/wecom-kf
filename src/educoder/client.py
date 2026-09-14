"""Main EduCoder API client."""

from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any

import requests

from .auth import API_BASE, CACHE_DIR, DEFAULT_TIMEOUT, build_edu_headers, extract_keys
from .auth import safe_json
from .exceptions import EduCoderError
from .utils import display, mask_phone, mask_tail


class EduCoderClient:
    """
    Reusable EduCoder API client.

    The client owns one ``requests.Session`` so login cookies are reused for
    later signed API calls.
    """

    def __init__(
        self,
        account: str | None = None,
        password: str | None = None,
        *,
        session: requests.Session | None = None,
        api_base: str = API_BASE,
        cache_dir: str | Path = CACHE_DIR,
        timeout: float = DEFAULT_TIMEOUT,
        verbose: bool = False,
        log_sensitive: bool = False,
    ) -> None:
        self.account = account
        self.password = password
        self.session = session or requests.Session()
        self.api_base = api_base.rstrip("/")
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.verbose = verbose
        self.log_sensitive = log_sensitive
        self._keys: dict[str, Any] | None = None
        self.login_result: dict[str, Any] | None = None
        self.user_info: dict[str, Any] | None = None
        self._courses_api: Any | None = None
        self._shixun_homeworks_api: Any | None = None
        self._tasks_api: Any | None = None
        self._answer_bank_api: Any | None = None

    @classmethod
    def from_env(cls, **kwargs: Any) -> "EduCoderClient":
        from .env import credentials_from_env

        account, password = credentials_from_env()
        return cls(account, password, **kwargs)

    @classmethod
    def from_dotenv(
        cls,
        path: str | Path = ".env",
        *,
        override: bool = False,
        **kwargs: Any,
    ) -> "EduCoderClient":
        from .env import load_env_file

        load_env_file(path, override=override)
        return cls.from_env(**kwargs)

    @property
    def session_cookie(self) -> str | None:
        return self.session.cookies.get("_educoder_session")

    @property
    def autologin_token(self) -> str | None:
        return self.session.cookies.get("autologin_trustie")

    @property
    def courses(self) -> Any:
        if self._courses_api is None:
            from .courses import CoursesAPI

            self._courses_api = CoursesAPI(self)
        return self._courses_api

    @property
    def shixun_homeworks(self) -> Any:
        if self._shixun_homeworks_api is None:
            from .shixun_homeworks import ShixunHomeworksAPI

            self._shixun_homeworks_api = ShixunHomeworksAPI(self)
        return self._shixun_homeworks_api

    @property
    def tasks(self) -> Any:
        if self._tasks_api is None:
            from .tasks import TasksAPI

            self._tasks_api = TasksAPI(self)
        return self._tasks_api

    @property
    def answer_bank(self) -> Any:
        if self._answer_bank_api is None:
            from .answer_bank import AnswerBankAPI

            self._answer_bank_api = AnswerBankAPI(self)
        return self._answer_bank_api

    def refresh_keys(self, *, force_refresh: bool = False) -> dict[str, Any]:
        self._keys = extract_keys(
            force_refresh=force_refresh,
            cache_dir=self.cache_dir,
            verbose=self.verbose,
        )
        return self._keys

    def build_headers(self, method: str) -> dict[str, str]:
        if self._keys is None:
            self.refresh_keys()
        return build_edu_headers(
            method,
            self.session,
            keys=self._keys,
            cache_dir=self.cache_dir,
            verbose=self.verbose,
        )

    def url_for(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.api_base}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        signed: bool = True,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        request_headers = self.build_headers(method) if signed else {}
        if headers:
            request_headers.update(headers)
        return self.session.request(
            method,
            self.url_for(path),
            headers=request_headers,
            timeout=self.timeout if timeout is None else timeout,
            **kwargs,
        )

    def request_json(
        self,
        method: str,
        path: str,
        *,
        signed: bool = True,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = self.request(
            method,
            path,
            signed=signed,
            headers=headers,
            timeout=timeout,
            **kwargs,
        )
        return safe_json(response)

    def login(
        self,
        account: str | None = None,
        password: str | None = None,
        *,
        autologin: bool = True,
    ) -> dict[str, Any]:
        account = account if account is not None else self.account
        password = password if password is not None else self.password
        if not account or not password:
            raise ValueError("account and password are required")

        self.account = account
        self.password = password
        login_label = account if self.log_sensitive else mask_tail(account)
        self._log(f"[*] Logging in ({login_label})...")
        result = self.request_json(
            "POST",
            "/api/accounts/login.json",
            json={
                "login": account,
                "password": password,
                "autologin": autologin,
            },
        )

        if result.get("user_id"):
            self.login_result = result
            self._log(
                "    [OK] Logged in: "
                f"name={display(result.get('name'))}, "
                f"user_id={display(result.get('user_id'))}, "
                f"school={display(result.get('school'))}"
            )
            if self.log_sensitive:
                self._log(
                    "    Auth: "
                    f"session={display(self.session_cookie)}, "
                    f"autologin_token={display(self.autologin_token)}"
                )
            return result

        msg = result.get("message", "") or json.dumps(result, ensure_ascii=False)
        raise EduCoderError(f"Login rejected: {msg}")

    def get_user_info(self, school_id: int = 1) -> dict[str, Any]:
        self._log(f"[*] Fetching user info (school={school_id})...")
        result = self.request_json(
            "GET",
            "/api/users/get_user_info.json",
            params={"school": school_id},
        )

        if result.get("user_id"):
            self.user_info = result
            self._log(
                "    [OK] User info: "
                f"login_no={display(result.get('login'))}, "
                f"username={display(result.get('username'))}, "
                f"real_name={display(result.get('real_name'))}, "
                f"phone={mask_phone(result.get('phone'))}, "
                f"school={display(result.get('school_name'))}, "
                f"identity={display(result.get('user_identity'))}, "
                f"grade={display(result.get('grade'))}"
            )
            if self.log_sensitive:
                self._log(
                    "    Sensitive: "
                    f"phone={display(result.get('phone'))}, "
                    f"student_id={display(result.get('student_id'))}"
                )
            return result

        msg = result.get("message", "") or json.dumps(result, ensure_ascii=False)
        raise EduCoderError(f"get_user_info failed: {msg}")

    def ensure_logged_in(self, *, school_id: int = 1) -> dict[str, Any]:
        if self.login_result is None:
            self.login()
        if self.user_info is None:
            self.get_user_info(school_id=school_id)
        return self.user_info or {}

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    def clone(self) -> "EduCoderClient":
        """Independent HTTP session with the current login; no new login request.

        Authenticate the parent before cloning. Close each clone's session when
        done. This avoids sharing a mutable requests.Session between workers.
        """
        if self.user_info is None or self._keys is None:
            raise ValueError("Authenticate the client before creating worker clones")
        session = requests.Session()
        session.cookies.update(self.session.cookies)
        session.headers.update(self.session.headers)
        session.proxies.update(self.session.proxies)
        session.verify = self.session.verify
        session.cert = self.session.cert
        session.trust_env = self.session.trust_env
        client = EduCoderClient(
            session=session, api_base=self.api_base, cache_dir=self.cache_dir,
            timeout=self.timeout, verbose=self.verbose, log_sensitive=self.log_sensitive,
        )
        client._keys = copy.deepcopy(self._keys)
        client.login_result = copy.deepcopy(self.login_result)
        client.user_info = copy.deepcopy(self.user_info)
        return client

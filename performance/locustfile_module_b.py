#!/usr/bin/env python3
"""
Extensive Locust workload for Module B.

This scenario is a supplementary benchmark track that complements the
notebook-driven correctness runner. It mixes read-heavy traffic with controlled
write paths (like/comment/follow round-trips) to model realistic usage.

Environment variables (optional):
- MODULE_B_USERNAMES: comma-separated emails for login pool
- MODULE_B_PASSWORD: password for all test users
- MODULE_B_POST_ID: default post id for detail/comment/like endpoints
- MODULE_B_TARGET_MEMBER_ID: member id used in follow/profile tasks
- MODULE_B_SEARCH_TERMS: comma-separated search terms
"""

from __future__ import annotations

import importlib
import json
import os
import random
import threading
import time
from typing import Any

_locust = importlib.import_module("locust")
HttpUser = _locust.HttpUser
between = _locust.between
task = _locust.task


DEFAULT_USERNAMES = [
    "rahul.sharma@iitgn.ac.in",
    "priya.patel@iitgn.ac.in",
    "ananya.singh@iitgn.ac.in",
    "neha.desai@iitgn.ac.in",
    "aditya.verma@iitgn.ac.in",
]
DEFAULT_SEARCH_TERMS = ["rahul", "ananya", "iitgn", "faculty", "student"]
DEFAULT_PASSWORD = "password123"
DEFAULT_POST_ID = 1
DEFAULT_TARGET_MEMBER_ID = 19


def _parse_csv_list(raw: str, fallback: list[str]) -> list[str]:
    parsed = [v.strip() for v in raw.split(",") if v.strip()]
    return parsed if parsed else fallback


def _safe_int(raw: str, fallback: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _safe_json(response) -> dict[str, Any]:
    try:
        if not response.text:
            return {}
        return response.json()
    except json.JSONDecodeError:
        return {"detail": response.text[:1000]}


USERNAMES = _parse_csv_list(
    os.getenv("MODULE_B_USERNAMES", ",".join(DEFAULT_USERNAMES)),
    DEFAULT_USERNAMES,
)
PASSWORD = os.getenv("MODULE_B_PASSWORD", DEFAULT_PASSWORD)
POST_ID = _safe_int(os.getenv("MODULE_B_POST_ID", str(DEFAULT_POST_ID)), DEFAULT_POST_ID)
TARGET_MEMBER_ID = _safe_int(
    os.getenv("MODULE_B_TARGET_MEMBER_ID", str(DEFAULT_TARGET_MEMBER_ID)),
    DEFAULT_TARGET_MEMBER_ID,
)
SEARCH_TERMS = _parse_csv_list(
    os.getenv("MODULE_B_SEARCH_TERMS", ",".join(DEFAULT_SEARCH_TERMS)),
    DEFAULT_SEARCH_TERMS,
)


class ModuleBUser(HttpUser):
    wait_time = between(0.2, 1.2)

    _user_index = 0
    _user_index_lock = threading.Lock()

    @classmethod
    def _next_username(cls) -> str:
        with cls._user_index_lock:
            username = USERNAMES[cls._user_index % len(USERNAMES)]
            cls._user_index += 1
            return username

    def on_start(self) -> None:
        self.username = self._next_username()
        self.password = PASSWORD
        self.post_id = POST_ID
        self.target_member_id = TARGET_MEMBER_ID
        self.member_id = 0
        self.session_token = ""
        self._login()

    def on_stop(self) -> None:
        if self.session_token:
            self.client.post("/logout", headers=self._headers(), name="/logout")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.session_token:
            headers["session-token"] = self.session_token
        return headers

    def _ensure_session(self) -> None:
        if not self.session_token:
            self._login()

    def _login(self) -> None:
        payload = {"username": self.username, "password": self.password}
        with self.client.post("/login", json=payload, name="/login", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"Login failed: HTTP {resp.status_code}")
                self.session_token = ""
                return

            body = _safe_json(resp)
            token = body.get("session_token")
            if not token:
                resp.failure("Login response missing session_token")
                self.session_token = ""
                return

            self.session_token = str(token)
            resp.success()

        auth_body = self._request("GET", "/isAuth", name="/isAuth", valid_statuses=(200,))
        self.member_id = _safe_int(str(auth_body.get("member_id", 0)), 0)

    def _request(
        self,
        method: str,
        path: str,
        *,
        name: str,
        payload: dict[str, Any] | None = None,
        valid_statuses: tuple[int, ...] = (200,),
        allow_retry: bool = True,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "headers": self._headers(),
            "name": name,
        }
        if payload is not None:
            kwargs["json"] = payload

        with self.client.request(method, path, catch_response=True, **kwargs) as resp:
            if resp.status_code == 401 and allow_retry:
                # Expired/invalid token; relogin once and retry request.
                resp.success()
                self._login()
                return self._request(
                    method,
                    path,
                    name=name,
                    payload=payload,
                    valid_statuses=valid_statuses,
                    allow_retry=False,
                )

            if resp.status_code in valid_statuses:
                resp.success()
                return _safe_json(resp)

            details = _safe_json(resp).get("detail", "")
            resp.failure(f"Unexpected status {resp.status_code}. {details}")
            return _safe_json(resp)

    @task(10)
    def browse_posts(self) -> None:
        self._ensure_session()
        offset = random.randint(0, 800)
        self._request(
            "GET",
            f"/posts?limit=20&offset={offset}",
            name="/posts",
            valid_statuses=(200,),
        )

    @task(6)
    def view_post_detail(self) -> None:
        self._ensure_session()
        self._request(
            "GET",
            f"/posts/{self.post_id}",
            name="/posts/[post_id]",
            valid_statuses=(200, 404),
        )

    @task(6)
    def view_post_comments(self) -> None:
        self._ensure_session()
        self._request(
            "GET",
            f"/posts/{self.post_id}/comments",
            name="/posts/[post_id]/comments (GET)",
            valid_statuses=(200, 404),
        )

    @task(4)
    def view_member_profile(self) -> None:
        self._ensure_session()
        candidates = [self.target_member_id]
        if self.member_id > 0:
            candidates.append(self.member_id)
        member_id = random.choice(candidates)
        self._request(
            "GET",
            f"/portfolio/{member_id}",
            name="/portfolio/[member_id]",
            valid_statuses=(200, 404),
        )

    @task(4)
    def view_member_posts(self) -> None:
        self._ensure_session()
        candidates = [self.target_member_id]
        if self.member_id > 0:
            candidates.append(self.member_id)
        member_id = random.choice(candidates)
        self._request(
            "GET",
            f"/members/{member_id}/posts?limit=20&offset=0",
            name="/members/[member_id]/posts",
            valid_statuses=(200, 404),
        )

    @task(3)
    def search_members(self) -> None:
        self._ensure_session()
        q = random.choice(SEARCH_TERMS)
        self._request(
            "GET",
            f"/members/search?q={q}&limit=20",
            name="/members/search",
            valid_statuses=(200, 400),
        )

    @task(2)
    def toggle_like(self) -> None:
        self._ensure_session()
        self._request(
            "POST",
            f"/posts/{self.post_id}/like/toggle",
            name="/posts/[post_id]/like/toggle",
            valid_statuses=(200, 404),
        )

    @task(1)
    def comment_round_trip(self) -> None:
        self._ensure_session()
        payload = {
            "content": f"[locust] comment from {self.username} at {int(time.time() * 1000)}"
        }
        created = self._request(
            "POST",
            f"/posts/{self.post_id}/comments",
            name="/posts/[post_id]/comments (POST)",
            payload=payload,
            valid_statuses=(200, 404),
        )
        comment_id = created.get("comment_id")
        if isinstance(comment_id, int) and comment_id > 0:
            self._request(
                "DELETE",
                f"/comments/{comment_id}",
                name="/comments/[comment_id] (DELETE)",
                valid_statuses=(200, 404),
            )

    @task(1)
    def follow_round_trip(self) -> None:
        self._ensure_session()
        if self.member_id <= 0 or self.member_id == self.target_member_id:
            return

        self._request(
            "POST",
            f"/members/{self.target_member_id}/follow",
            name="/members/[member_id]/follow (POST)",
            valid_statuses=(200,),
        )
        self._request(
            "DELETE",
            f"/members/{self.target_member_id}/follow",
            name="/members/[member_id]/follow (DELETE)",
            valid_statuses=(200, 404),
        )

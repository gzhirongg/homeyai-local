"""
OneMapService
=============
A fault-tolerant wrapper around the OneMap Singapore API.

Features:
- Dual-account credentials for automatic failover.
- JWT token caching (file-based) to avoid redundant logins.
- Rolling 250 req/min rate limiter.
- Self-healing: on 429 / auth failures, rotates credentials and retries.
- Designed for use in Prefect @task contexts (logger-aware).
"""

from __future__ import annotations

import json
import os
import time
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent.parent  # backend root

# Load .env if vars not already set (for standalone script use)
for _env_candidate in [_HERE / ".env", _HERE.parent / ".env"]:
    if _env_candidate.exists():
        for _line in _env_candidate.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                k, _, v = _line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        break

ONEMAP_AUTH_URL = "https://www.onemap.gov.sg/api/auth/post/getToken"
ONEMAP_SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
ONEMAP_ROUTE_URL = "https://www.onemap.gov.sg/api/public/routingsvc/route"

# Discover accounts dynamically based on environment variables
ACCOUNTS = []
_email_base = os.getenv("ONEMAP_EMAIL")
_pwd_base = os.getenv("ONEMAP_PASSWORD")
if _email_base and _pwd_base:
    ACCOUNTS.append({"email": _email_base, "password": _pwd_base})

# Scan for ONEMAP_EMAIL_1, ONEMAP_EMAIL_2, etc.
for i in range(1, 20):  # Check up to 20 potential suffixes
    email = os.getenv(f"ONEMAP_EMAIL_{i}")
    pwd = os.getenv(f"ONEMAP_PASSWORD_{i}")
    if email and pwd and not any(acc["email"] == email for acc in ACCOUNTS):
        ACCOUNTS.append({"email": email, "password": pwd})

if not ACCOUNTS:
    ACCOUNTS.append({"email": "", "password": ""}) # fallback

TOKEN_CACHE_PATH = _HERE / ".onemap_token_v2.json"

# OneMap states tokens expire after 3 days; we refresh 1 hour early.
TOKEN_EXPIRY_BUFFER_SECS = 3600

# Rate limit: 250 requests per 60 seconds
RATE_LIMIT_REQUESTS = 250
RATE_LIMIT_WINDOW_SECS = 60.0


# ---------------------------------------------------------------------------
# OneMapService
# ---------------------------------------------------------------------------

class OneMapService:
    """Thread-safe, rate-limited, auto-rotating OneMap API client."""

    def __init__(self, logger=None):
        self._global_lock = threading.Lock()
        self._logger = logger  # Prefect get_run_logger() or None
        
        self._account_states = []
        for acc in ACCOUNTS:
            self._account_states.append({
                "email": acc["email"],
                "password": acc["password"],
                "token": None,
                "token_expiry": 0.0,
                "timestamps": deque(),
                "is_valid": True
            })
            
        self._load_cached_tokens()

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log(self, level: str, msg: str) -> None:
        if self._logger:
            getattr(self._logger, level, self._logger.info)(msg)
        else:
            print(f"[OneMapService][{level.upper()}] {msg}")

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _load_cached_tokens(self) -> None:
        """Load tokens from disk cache if they exist and are not expired."""
        try:
            if TOKEN_CACHE_PATH.exists():
                cache_data = json.loads(TOKEN_CACHE_PATH.read_text())
                for state in self._account_states:
                    c = cache_data.get(state["email"])
                    if c:
                        expiry = float(c.get("expiry", 0))
                        if time.time() < expiry - TOKEN_EXPIRY_BUFFER_SECS:
                            state["token"] = c["token"]
                            state["token_expiry"] = expiry
                            self._log("info", f"Loaded cached token for {state['email']}")
        except Exception as e:
            self._log("warning", f"Could not load token cache: {e}")

    def _save_token_cache(self) -> None:
        try:
            cache_data = {}
            for state in self._account_states:
                if state["token"]:
                    cache_data[state["email"]] = {
                        "token": state["token"],
                        "expiry": state["token_expiry"],
                    }
            TOKEN_CACHE_PATH.write_text(json.dumps(cache_data))
        except Exception as e:
            self._log("warning", f"Could not save token cache: {e}")

    def _refresh_token(self, idx: int) -> None:
        """Authenticate with OneMap and store the new JWT token for specific account."""
        state = self._account_states[idx]
        if not state["email"] or not state["password"] or not state["is_valid"]:
            raise RuntimeError(f"No valid OneMap credentials found for account index {idx}.")

        self._log("warning", f"Requesting new OneMap token (account #{idx}: {state['email']})")
        resp = requests.post(ONEMAP_AUTH_URL, json={"email": state["email"], "password": state["password"]}, timeout=15)
        
        if resp.status_code == 400:
            self._log("critical", f"Account #{idx} ({state['email']}) failed authentication (400 Bad Request). Disabling account.")
            state["is_valid"] = False
            return

        resp.raise_for_status()
        data = resp.json()
        
        with self._global_lock:
            state["token"] = data["access_token"]
            state["token_expiry"] = float(data.get("expiry_timestamp", time.time() + 72 * 3600))
            self._save_token_cache()
            
        self._log("info", f"Token refreshed for {state['email']}. Expires {datetime.fromtimestamp(state['token_expiry'], tz=timezone.utc).isoformat()}")

    def _ensure_valid_token(self, idx: int) -> None:
        state = self._account_states[idx]
        if not state["token"] or time.time() > state["token_expiry"] - TOKEN_EXPIRY_BUFFER_SECS:
            self._refresh_token(idx)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _acquire_account_and_throttle(self) -> int:
        """Find the most free account, block if all are maxed out, and return the chosen account index."""
        with self._global_lock:
            now = time.time()
            for state in self._account_states:
                while state['timestamps'] and now - state['timestamps'][0] > RATE_LIMIT_WINDOW_SECS:
                    state['timestamps'].popleft()

            # Find account with minimum load under the threshold
            best_idx = -1
            min_len = RATE_LIMIT_REQUESTS + 1
            for idx, state in enumerate(self._account_states):
                if not state["is_valid"]: continue
                if len(state['timestamps']) < RATE_LIMIT_REQUESTS:
                    if len(state['timestamps']) < min_len:
                        min_len = len(state['timestamps'])
                        best_idx = idx
            
            if best_idx != -1:
                self._account_states[best_idx]['timestamps'].append(now)
                return best_idx
            
            # Check if we have ANY valid accounts left
            valid_accounts = [s for s in self._account_states if s["is_valid"]]
            if not valid_accounts:
                raise RuntimeError("All OneMap accounts are invalid or disabled due to authentication failures.")

            # All accounts maxed. Find the one that frees up next.
            best_idx = 0
            earliest_drop = float('inf')
            for idx, state in enumerate(self._account_states):
                if not state["is_valid"]: continue
                if state['timestamps']:
                    drop_time = state['timestamps'][0]
                    if drop_time < earliest_drop:
                        earliest_drop = drop_time
                        best_idx = idx
                    
            sleep_for = RATE_LIMIT_WINDOW_SECS - (now - earliest_drop) + 0.1
            self._log("info", f"All {len(self._account_states)} accounts rate limited. Sleeping {sleep_for:.2f}s …")
            time.sleep(sleep_for)
            
            now = time.time()
            for state in self._account_states:
                while state['timestamps'] and now - state['timestamps'][0] > RATE_LIMIT_WINDOW_SECS:
                    state['timestamps'].popleft()
                    
            self._account_states[best_idx]['timestamps'].append(now)
            return best_idx

    # ------------------------------------------------------------------
    # Core API call
    # ------------------------------------------------------------------

    def search_address(
        self, query: str, max_retries: int = 2, *, include_raw: bool = False
    ) -> Optional[dict]:
        """
        Query the OneMap elastic search endpoint for a given address string.

        Returns a dict with ``results`` (list of hit dicts) and ``found`` (count).
        If ``include_raw`` is True, also includes ``raw``: the full parsed JSON body
        from the API (for auditing; may contain keys beyond ``results`` / ``found``).

        Raises RuntimeError after exhausting retries.
        """
        for attempt in range(max_retries + 1):
            try:
                # Dynamically acquire an account slot across all threads
                idx = self._acquire_account_and_throttle()
                self._ensure_valid_token(idx)
                
                # If acquiring/ensuring token failed and disabled the account in multi-threading edge case
                if not self._account_states[idx]["is_valid"]:
                    continue
                
                resp = requests.get(
                    ONEMAP_SEARCH_URL,
                    params={
                        "searchVal": query,
                        "returnGeom": "Y",
                        "getAddrDetails": "Y",
                        # "pageNum": 1,
                    },
                    headers={"Authorization": f"Bearer {self._account_states[idx]['token']}"},
                    timeout=10,
                )

                if resp.status_code == 401:
                    self._log("warning", f"401 Unauthorized for account {idx} – invalidating token and retrying.")
                    with self._global_lock:
                        self._account_states[idx]["token"] = None
                        self._account_states[idx]["token_expiry"] = 0.0
                        TOKEN_CACHE_PATH.unlink(missing_ok=True)
                    continue  # retry

                if resp.status_code == 429:
                    # We hit an external rate limit despite our internal tracking.
                    self._log("critical", f"429 received on account {idx}. Maxing out its internal timestamp tracker.")
                    with self._global_lock:
                        # Artificially pad the timestamps so it skips selection temporarily
                        now = time.time()
                        while len(self._account_states[idx]['timestamps']) < RATE_LIMIT_REQUESTS:
                            self._account_states[idx]['timestamps'].append(now)
                    continue

                resp.raise_for_status()
                data = resp.json()
                out = {
                    "results": data.get("results", []),
                    "found": int(data.get("found", 0)),
                }
                if include_raw:
                    out["raw"] = data
                return out

            except requests.HTTPError as e:
                if attempt >= max_retries:
                    raise
                self._log("warning", f"HTTP Error (attempt {attempt + 1}): {e}. Retrying …")
                time.sleep(2 ** attempt)
            except requests.RequestException as e:
                if attempt >= max_retries:
                    raise
                self._log("warning", f"Network Error (attempt {attempt + 1}): {e}. Retrying …")
                time.sleep(2 ** attempt)

        raise RuntimeError(f"Failed to query OneMap for '{query}' after {max_retries + 1} attempts.")

    def get_route(
        self, start_lat: float, start_lng: float, end_lat: float, end_lng: float,
        route_type: str = "walk", date: str = "", query_time: str = "", mode: str = "TRANSIT",
        max_retries: int = 2
    ) -> Optional[dict]:
        """
        Query the OneMap routing endpoint.
        route_type: "walk", "drive", "pt", "cycle"
        """
        for attempt in range(max_retries + 1):
            try:
                idx = self._acquire_account_and_throttle()
                self._ensure_valid_token(idx)
                
                if not self._account_states[idx]["is_valid"]:
                    continue
                
                params = {
                    "start": f"{start_lat},{start_lng}",
                    "end": f"{end_lat},{end_lng}",
                    "routeType": route_type
                }
                if route_type == "pt":
                    # Always route on the next upcoming Monday at 08:30 AM
                    # OneMap requires date within 1 month. Using a stable Mon morning
                    # ensures normalized morning-commute conditions across all blocks.
                    if not date:
                        today = datetime.now()
                        days_until_monday = (7 - today.weekday()) % 7 or 7
                        next_monday = today + timedelta(days=days_until_monday)
                        _date = next_monday.strftime("%m-%d-%Y")
                    else:
                        _date = date
                    params["date"] = _date
                    params["time"] = query_time or "08:30:00"
                    params["mode"] = mode # TRANSIT
                
                resp = requests.get(
                    ONEMAP_ROUTE_URL,
                    params=params,
                    headers={"Authorization": f"Bearer {self._account_states[idx]['token']}"},
                    timeout=15,
                )

                if resp.status_code == 401:
                    self._log("warning", f"401 Unauthorized for account {idx} on routing – invalidating token.")
                    with self._global_lock:
                        self._account_states[idx]["token"] = None
                        self._account_states[idx]["token_expiry"] = 0.0
                        TOKEN_CACHE_PATH.unlink(missing_ok=True)
                    continue

                if resp.status_code == 429:
                    self._log("critical", f"429 received on account {idx} routing. Maxing out timestamp tracker.")
                    with self._global_lock:
                        now = time.time()
                        while len(self._account_states[idx]['timestamps']) < RATE_LIMIT_REQUESTS:
                            self._account_states[idx]['timestamps'].append(now)
                    continue

                resp.raise_for_status()
                return resp.json()

            except requests.HTTPError as e:
                # Do not retry Client Errors (4xx) except 408/429
                if getattr(e, 'response', None) is not None and e.response.status_code < 500 and e.response.status_code not in (408, 429):
                    self._log("info", f"OneMap Route '{route_type}' gracefully skipped (4xx Error): {e}")
                    return None
                    
                if attempt >= max_retries:
                    raise
                self._log("warning", f"Routing HTTP Error (attempt {attempt + 1}): {e}. Retrying …")
                time.sleep(2 ** attempt)
            except requests.RequestException as e:
                if attempt >= max_retries:
                    raise
                self._log("warning", f"Routing Network Error (attempt {attempt + 1}): {e}. Retrying …")
                time.sleep(2 ** attempt)

        raise RuntimeError(f"Failed to route {route_type} from {start_lat},{start_lng} after {max_retries + 1} attempts.")


# ---------------------------------------------------------------------------
# Module-level singleton (optional convenience)
# ---------------------------------------------------------------------------
_service_instance: Optional[OneMapService] = None


def get_service(logger=None) -> OneMapService:
    """Return a module-level singleton OneMapService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = OneMapService(logger=logger)
    elif logger is not None:
        _service_instance._logger = logger
    return _service_instance

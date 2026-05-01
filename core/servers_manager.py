"""
SyncWatch - Servers Manager.

Fetches the list of public SyncWatch servers from the GitHub repository's
syncwatch_servers.json file. Provides:
- Encrypted data storage on GitHub
- Ping latency measurement for each server
- Room count querying from online servers
- Dead server detection and removal via working servers
"""
import json
import logging
import time
import os
import sys
import socket
import threading
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from core.client import SyncClient
from urllib.request import Request, urlopen
from urllib.error import URLError

log = logging.getLogger(__name__)

GITHUB_SERVERS_URL = (
    "https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/syncwatch_servers.json"
)
GITHUB_API_URL = (
    "https://api.github.com/repos/OBITOLZ0X/SyncWatch/contents/syncwatch_servers.json"
)
_CACHE_DURATION = 120  # seconds

_GH_REPO_URL = (
    "https://api.github.com/repos/OBITOLZ0X/SyncWatch/contents/syncwatch_servers.json"
)

# Country name -> ISO 3166-1 alpha-2 code mapping
_COUNTRY_CODES = {
    "Algeria": "DZ", "Argentina": "AR", "Australia": "AU", "Austria": "AT",
    "Bahrain": "BH", "Bangladesh": "BD", "Belarus": "BY", "Belgium": "BE",
    "Bolivia": "BO", "Botswana": "BW", "Brazil": "BR", "Brunei": "BN",
    "Bulgaria": "BG", "Canada": "CA", "Chile": "CL", "China": "CN",
    "Colombia": "CO", "Costa Rica": "CR", "Croatia": "HR", "Cuba": "CU",
    "Cyprus": "CY", "Czech Republic": "CZ", "Denmark": "DK",
    "Dominican Republic": "DO", "Ecuador": "EC", "Egypt": "EG",
    "El Salvador": "SV", "Estonia": "EE", "Finland": "FI", "France": "FR",
    "Germany": "DE", "Ghana": "GH", "Greece": "GR", "Guatemala": "GT",
    "Honduras": "HN", "Hong Kong": "HK", "Hungary": "HU", "Iceland": "IS",
    "India": "IN", "Indonesia": "ID", "Iran": "IR", "Iraq": "IQ",
    "Ireland": "IE", "Israel": "IL", "Italy": "IT", "Jamaica": "JM",
    "Japan": "JP", "Jordan": "JO", "Kazakhstan": "KZ", "Kenya": "KE",
    "Kuwait": "KW", "Latvia": "LV", "Lebanon": "LB", "Libya": "LY",
    "Lithuania": "LT", "Luxembourg": "LU", "Madagascar": "MG",
    "Malawi": "MW", "Malaysia": "MY", "Maldives": "MV", "Malta": "MT",
    "Mauritania": "MR", "Mauritius": "MU", "Mexico": "MX", "Monaco": "MC",
    "Mongolia": "MN", "Morocco": "MA", "Myanmar": "MM", "Namibia": "NA",
    "Nepal": "NP", "Netherlands": "NL", "New Zealand": "NZ",
    "Nicaragua": "NI", "Nigeria": "NG", "Norway": "NO", "Oman": "OM",
    "Pakistan": "PK", "Palestine": "PS", "Panama": "PA",
    "Papua New Guinea": "PG", "Paraguay": "PY", "Peru": "PE",
    "Philippines": "PH", "Poland": "PL", "Portugal": "PT",
    "Puerto Rico": "PR", "Qatar": "QA", "Romania": "RO", "Russia": "RU",
    "Rwanda": "RW", "Saudi Arabia": "SA", "Senegal": "SN", "Serbia": "RS",
    "Singapore": "SG", "Slovakia": "SK", "Slovenia": "SI",
    "South Africa": "ZA", "South Korea": "KR", "Spain": "ES",
    "Sri Lanka": "LK", "Sudan": "SD", "Sweden": "SE", "Switzerland": "CH",
    "Syria": "SY", "Taiwan": "TW", "Tanzania": "TZ", "Thailand": "TH",
    "Tunisia": "TN", "Turkey": "TR", "Uganda": "UG", "Ukraine": "UA",
    "United Arab Emirates": "AE", "United Kingdom": "GB",
    "United States": "US", "Uruguay": "UY", "Uzbekistan": "UZ",
    "Vatican City": "VA", "Venezuela": "VE", "Vietnam": "VN",
    "Yemen": "YE", "Zambia": "ZM", "Zimbabwe": "ZW",
}


def _country_to_code(country_name: str) -> str:
    """Convert a full country name to ISO 3166-1 alpha-2 code."""
    if len(country_name) == 2 and country_name.isalpha():
        return country_name.upper()
    return _COUNTRY_CODES.get(country_name, country_name[:2].upper() if country_name else "??")


class ServersManager:
    """Fetches and caches the list of public SyncWatch servers."""

    def __init__(self):
        self._cache: List[Dict] = []
        self._cache_time: float = 0.0
        self._last_error: Optional[str] = None

    def fetch_servers(self, force: bool = False) -> List[Dict]:
        """Fetch the list of public servers from GitHub.

        Returns a list of dicts::
            {
                "url": "ws://1.2.3.4:8765",
                "country": "United States",
                "country_code": "US",
                "port": 8765,
                "host": "1.2.3.4",
                "status": "online",
                "last_seen": "2026-04-30T12:00:00Z",
                "ping_ms": 45,
                "rooms": 0,  # number of open rooms on the server
            }
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < _CACHE_DURATION:
            return self._cache

        servers = []
        try:
            req = Request(
                GITHUB_SERVERS_URL,
                headers={"User-Agent": "SyncWatch/2.0"},
            )
            with urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8").strip()
                try:
                    from core.token_utils import server_data_decrypt
                    decrypted = server_data_decrypt(raw)
                    servers = json.loads(decrypted)
                    log.info("Successfully decrypted server data from GitHub")
                except Exception:
                    servers = json.loads(raw)
                    log.info("Parsed server data as plain JSON")

            if not isinstance(servers, list):
                log.warning("Servers file is not a list, got %s", type(servers).__name__)
                servers = []

            for srv in servers:
                country = srv.get("country", "")
                if "country_code" not in srv:
                    srv["country_code"] = _country_to_code(country)
                if "rooms" not in srv:
                    srv["rooms"] = None

            self._last_error = None
            log.info("Fetched %d public servers from GitHub", len(servers))

        except URLError as e:
            self._last_error = f"Network error: {e.reason}"
            log.warning("Failed to fetch servers: %s", self._last_error)
        except json.JSONDecodeError as e:
            self._last_error = f"Invalid JSON: {e}"
            log.warning("Failed to parse servers: %s", self._last_error)
        except Exception as e:
            self._last_error = str(e)
            log.warning("Failed to fetch servers: %s", e)

        return servers

    def scan_servers_sequential(self, servers: List[Dict],
                                progress_callback=None) -> List[Dict]:
        """Scan servers one-by-one measuring ping & querying room counts.

        Calls progress_callback(current, total, server_dict, status_msg)
        after each server is checked.
        """
        total = len(servers)
        for idx, srv in enumerate(servers):
            url = srv.get("url", "")
            host_ip = srv.get("host", "")
            country = srv.get("country", "Unknown")
            country_code = srv.get("country_code", "??")

            # Build a display label from the host IP (masked)
            ip_parts = host_ip.split(".")
            if len(ip_parts) == 4 and all(p.isdigit() for p in ip_parts):
                display_ip = f"{ip_parts[0]}.{ip_parts[1]}.*.*"
            elif host_ip:
                display_ip = host_ip
            else:
                display_ip = url.split("://")[-1].split("/")[0] if url else "?"

            if progress_callback:
                progress_callback(
                    idx + 1, total,
                    {**srv},
                    f"Checking server {idx+1}/{total}: {display_ip} ({country_code})"
                )

            # Measure TCP ping
            ping_ms = self._measure_tcp_ping(srv)
            srv["ping_ms"] = ping_ms if ping_ms is not None else -1
            srv["status"] = "online" if ping_ms is not None else "offline"

            if srv["status"] == "online":
                # Query room count via WebSocket
                self._query_single_server_rooms(srv)

            if srv["status"] != "online":
                srv["ping_ms"] = -1
                srv["rooms"] = None

            srv["last_checked"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Sort: online with rooms first (by rooms asc, then ping asc),
        # then online without rooms (by ping asc), then offline
        servers.sort(key=lambda s: (
            0 if s.get("status") == "online" and isinstance(s.get("rooms"), int) and s["rooms"] > 0 else
            1 if s.get("status") == "online" else 2,
            s.get("rooms", 9999) if isinstance(s.get("rooms"), int) else 9999,
            s.get("ping_ms", 9999) if isinstance(s.get("ping_ms"), (int, float)) and s.get("ping_ms") >= 0 else 9999,
            s.get("country", "Unknown"),
        ))

        self._cache = list(servers)
        self._cache_time = time.time()
        return servers

    def _measure_tcp_ping(self, srv: Dict) -> Optional[int]:
        """Measure ping via TCP connection time. Returns ms or None.
        
        Uses 3 rapid connections and takes the FASTEST time — this
        eliminates cold-start (DNS cache, Windows networking) overhead
        that inflates the first measurement.
        """
        url = srv.get("url", "")
        # Detect scheme
        scheme = ""
        rest = url
        for prefix in ("wss://", "ws://", "https://", "http://"):
            if rest.startswith(prefix):
                scheme = prefix.rstrip("://")
                rest = rest[len(prefix):]
                break

        if ":" in rest and rest.split(":")[1].split("/")[0].isdigit():
            host = rest.split(":")[0]
            port_str = rest.split(":")[1].split("/")[0]
            port = int(port_str)
        else:
            host = rest.split("/")[0]
            if scheme in ("wss", "https"):
                port = 443
            elif scheme in ("ws", "http"):
                port = 80
            else:
                port = srv.get("port", 8765)

        try:
            # Resolve DNS once up front so we work with the IP directly
            try:
                resolved = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                ip = resolved[0][4][0]
            except Exception:
                ip = host  # fallback to hostname

            best_ms = 9999  # sentinel
            for _attempt in range(3):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3.0)
                    start = time.perf_counter()
                    result = sock.connect_ex((ip, port))
                    elapsed = (time.perf_counter() - start) * 1000
                    sock.close()
                    if result == 0 and elapsed < best_ms:
                        best_ms = elapsed
                except Exception:
                    pass

            if best_ms < 9999:
                return int(best_ms)
        except Exception:
            pass
        return None

    def _query_single_server_rooms(self, srv: Dict) -> None:
        """Query room count from one online server via WebSocket.
        
        Does NOT overwrite ping_ms — the TCP connect time from
        _measure_tcp_ping is the canonical ping value.
        """
        url = srv.get("url", "")
        if not url:
            srv["status"] = "offline"
            srv["rooms"] = None
            srv["ping_ms"] = -1
            return
        try:
            import asyncio
            import json as _json
            import websockets as _ws
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _do_query():
                try:
                    async with _ws.connect(
                        url,
                        ping_interval=None,
                        open_timeout=5,
                        close_timeout=2,
                    ) as ws:
                        await ws.send(_json.dumps({"type": "room_count_request"}))
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        data = _json.loads(raw)
                        if data.get("type") == "room_count_response":
                            room_count = data.get("room_count")
                            if room_count is None or room_count == "-":
                                srv["status"] = "offline"
                                srv["rooms"] = None
                                srv["ping_ms"] = -1
                            else:
                                srv["rooms"] = room_count
                                # ping_ms already set by _measure_tcp_ping — keep it
                        else:
                            srv["status"] = "offline"
                            srv["rooms"] = None
                            srv["ping_ms"] = -1
                except Exception:
                    srv["status"] = "offline"
                    srv["rooms"] = None
                    srv["ping_ms"] = -1

            loop.run_until_complete(_do_query())
            loop.close()
        except Exception:
            srv["status"] = "offline"
            srv["rooms"] = None
            srv["ping_ms"] = -1

    def _query_room_counts(self, servers: List[Dict]) -> None:
        """Query room count from each online server via WebSocket in background threads.
        
        Also measures ping response time and marks servers as offline if they:
        - Don't respond within the timeout
        - Return "-" (None) for room count
        - Return unexpected response format
        """

        def _query(srv: Dict):
            if srv.get("status") != "online":
                return
            url = srv.get("url", "")
            if not url:
                return
            try:
                import asyncio
                import json as _json
                import websockets as _ws
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def _do_query():
                    try:
                        start_time = time.time()
                        async with _ws.connect(
                            url,
                            ping_interval=None,
                            open_timeout=5,
                            close_timeout=2,
                        ) as ws:
                            await ws.send(_json.dumps({"type": "room_count_request"}))
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                            response_time = (time.time() - start_time) * 1000  # ms
                            
                            data = _json.loads(raw)
                            if data.get("type") == "room_count_response":
                                room_count = data.get("room_count")
                                # Check if room count is "-" (None) or invalid
                                if room_count is None or room_count == "-":
                                    # Server returned "-" or None — mark as offline
                                    srv["status"] = "offline"
                                    srv["rooms"] = None
                                    srv["ping_ms"] = -1
                                    log.warning("Server %s returned invalid room count (%s) — marking as offline",
                                               url, room_count)
                                else:
                                    srv["rooms"] = room_count
                                    # Update ping based on response time (from WebSocket connection + request/response)
                                    if "ping_ms" not in srv or srv["ping_ms"] < 0:
                                        srv["ping_ms"] = int(response_time)
                            else:
                                # Unexpected response format
                                srv["status"] = "offline"
                                srv["rooms"] = None
                                srv["ping_ms"] = -1
                                log.warning("Server %s returned unexpected response format — marking as offline", url)
                    except asyncio.TimeoutError:
                        # Timeout — mark as offline
                        srv["status"] = "offline"
                        srv["rooms"] = None
                        srv["ping_ms"] = -1
                        log.warning("Server %s did not respond to room_count_request (timeout) — marking as offline", url)
                    except Exception as e:
                        srv["status"] = "offline"
                        srv["rooms"] = None
                        srv["ping_ms"] = -1
                        log.warning("Server %s failed room_count query: %s — marking as offline", url, e)

                loop.run_until_complete(_do_query())
                loop.close()
            except Exception as e:
                srv["status"] = "offline"
                srv["rooms"] = None
                srv["ping_ms"] = -1
                log.warning("Server %s room_count query error: %s — marking as offline", url, e)

        threads = []
        for srv in servers:
            if srv.get("status") == "online":
                t = threading.Thread(target=_query, args=(srv,), daemon=True)
                threads.append(t)
                t.start()

        for t in threads:
            t.join(timeout=6.0)

    def _check_servers(self, servers: List[Dict]) -> List[Dict]:
        """Check connectivity and measure ping for each server.
        
        Pings use the *connection URL* (ngrok/domain) not the raw IP,
        because the raw IP may be firewalled while the tunnel works.
        """
        import re as _re
        results = [None] * len(servers)

        def _check(idx: int, srv: Dict):
            url = srv.get("url", "")

            # Detect URL scheme for default ports
            scheme = ""
            rest = url
            for prefix in ("wss://", "ws://", "https://", "http://"):
                if rest.startswith(prefix):
                    scheme = prefix.rstrip("://")
                    rest = rest[len(prefix):]
                    break

            # Extract hostname:port from the public connection URL (ngrok/domain)
            if ":" in rest and rest.split(":")[1].split("/")[0].isdigit():
                # Explicit port in URL
                host = rest.split(":")[0]
                port_str = rest.split(":")[1].split("/")[0]
                port = int(port_str)
            else:
                # No explicit port — use default based on scheme
                host = rest.split("/")[0]
                if scheme == "wss" or scheme == "https":
                    port = 443
                elif scheme == "ws" or scheme == "http":
                    port = 80
                else:
                    port = srv.get("port", 8765)

            # Measure ping via TCP connection time
            ping_ms = None
            is_online = False
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                start = time.time()
                result = sock.connect_ex((host, port))
                elapsed = (time.time() - start) * 1000  # ms
                sock.close()
                if result == 0:
                    is_online = True
                    ping_ms = int(elapsed)
                else:
                    is_online = False
            except Exception:
                is_online = False

            srv["status"] = "online" if is_online else "offline"
            if ping_ms is not None:
                srv["ping_ms"] = ping_ms
            srv["last_checked"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            results[idx] = srv

        threads = []
        for i, srv in enumerate(servers):
            t = threading.Thread(target=_check, args=(i, srv), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=4.0)

        return [r for r in results if r is not None]

    def get_offline_servers(self, servers: List[Dict]) -> List[Dict]:
        """Get list of servers that are marked as offline.
        
        Returns a list of offline server dicts that should be removed.
        """
        return [srv for srv in servers if srv.get("status") == "offline"]

    def cleanup_offline_servers(self, client: 'SyncClient', servers: List[Dict]) -> None:
        """Automatically cleanup offline servers via connected client.
        
        Detects offline servers from the fetch_servers result and automatically
        sends a cleanup request to a connected server to remove them from GitHub.
        
        Args:
            client: A connected SyncClient instance
            servers: The list of servers (from fetch_servers)
        """
        offline_servers = self.get_offline_servers(servers)
        if not offline_servers:
            log.info("No offline servers detected")
            return
        
        log.warning("Detected %d offline servers, sending cleanup request", len(offline_servers))
        for srv in offline_servers:
            log.warning("  - Offline: %s (URL: %s)", 
                       srv.get("country", "Unknown"), 
                       srv.get("url", "Unknown"))
        
        # Request connected server to remove offline servers
        self.request_cleanup_via_client(client, servers)

    def remove_dead_servers(self) -> bool:
        """Remove offline servers from the GitHub JSON file.
        
        ⚠ The client no longer has the GitHub token. Cleanup is delegated
        to running servers via the protocol (CLEANUP_REQUEST / CLEANUP_RESPONSE).
        
        This method is kept for backward compatibility — it always returns False
        to signal that cleanup must be done through a connected server.
        
        To trigger cleanup from the UI, use the 'request_cleanup' method
        with a SyncClient connection to a running server.
        """
        log.info("Client-side cleanup disabled — delegated to servers via protocol")
        return False

    def request_cleanup_via_client(self, client: 'SyncClient', servers: List[Dict]) -> None:
        """Request a connected server to verify and remove dead servers.
        
        The client must already be connected to a running SyncWatch server.
        The server will check all servers, remove offline ones from GitHub,
        and respond with CLEANUP_RESPONSE.
        
        Args:
            client: A connected SyncClient instance
            servers: The list of servers to check (from fetch_servers)
        """
        if not client or not client.is_connected:
            log.warning("Cannot request cleanup: no connected client")
            return
        client.send_cleanup_request(servers)
        log.info("Cleanup request sent to connected server")

    def get_last_error(self) -> Optional[str]:
        """Return the last error message, if any."""
        return self._last_error

    def clear_cache(self):
        """Force re-fetch on next call."""
        self._cache = []
        self._cache_time = 0.0
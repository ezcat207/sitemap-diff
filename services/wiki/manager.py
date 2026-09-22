import json
import logging
from pathlib import Path
from urllib.parse import urlparse, quote
import requests


class WikiManager:
    """监控 MediaWiki/Fandom 类站点的新增词条 (走 api.php, 不受 sitemap.xml 的 Cloudflare 拦截影响)"""

    def __init__(self):
        self.config_dir = Path("storage/wiki/config")
        self.state_dir = Path("storage/wiki/state")  # 记录每个站点最后检查到的时间戳
        self.feeds_file = self.config_dir / "feeds.json"
        self._init_directories()

    def _init_directories(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.feeds_file.exists():
            self.feeds_file.write_text("[]")

    def _state_file(self, base_url: str) -> Path:
        domain = urlparse(base_url).netloc
        return self.state_dir / f"{domain}.json"

    def get_feeds(self) -> list:
        try:
            return json.loads(self.feeds_file.read_text())
        except Exception:
            logging.error("读取wiki feeds文件失败", exc_info=True)
            return []

    def add_feed(self, base_url: str) -> tuple[bool, str, list[dict]]:
        base_url = base_url.rstrip("/")
        feeds = self.get_feeds()
        if base_url not in feeds:
            success, error_msg, new_pages = self.check_new_pages(base_url)
            if not success:
                return False, error_msg, []
            feeds.append(base_url)
            self.feeds_file.write_text(json.dumps(feeds, indent=2))
            logging.info(f"成功添加wiki监控: {base_url}")
            return True, "", new_pages
        else:
            success, error_msg, new_pages = self.check_new_pages(base_url)
            if not success:
                return False, error_msg, []
            return True, "已存在的wiki更新成功", new_pages

    def remove_feed(self, base_url: str) -> tuple[bool, str]:
        base_url = base_url.rstrip("/")
        feeds = self.get_feeds()
        if base_url not in feeds:
            return False, "该wiki订阅不存在"
        feeds.remove(base_url)
        self.feeds_file.write_text(json.dumps(feeds, indent=2))
        state_file = self._state_file(base_url)
        if state_file.exists():
            state_file.unlink()
        return True, ""

    def check_new_pages(self, base_url: str, limit: int = 50) -> tuple[bool, str, list[dict]]:
        """通过 MediaWiki api.php 的 recentchanges 检查新增词条 (ns=0, type=new)

        Returns:
            tuple[bool, str, list[dict]]: (是否成功, 错误信息, 新增词条列表 [{title, url, timestamp}])
        """
        api_url = f"{base_url}/api.php"
        state_file = self._state_file(base_url)
        last_timestamp = None
        if state_file.exists():
            try:
                last_timestamp = json.loads(state_file.read_text()).get("last_timestamp")
            except Exception:
                last_timestamp = None

        params = {
            "action": "query",
            "list": "recentchanges",
            "rcnamespace": 0,
            "rctype": "new",
            "rcprop": "title|timestamp|ids",
            "rclimit": limit,
            "format": "json",
        }
        if last_timestamp:
            params["rcdir"] = "newer"
            params["rcstart"] = last_timestamp

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

        try:
            response = requests.get(api_url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            changes = data.get("query", {}).get("recentchanges", [])
        except requests.exceptions.RequestException as e:
            return False, f"请求失败: {str(e)}", []
        except (ValueError, KeyError) as e:
            return False, f"解析失败: {str(e)}", []

        # 首次添加时不回放历史，只建立基线，避免一次性刷屏
        if last_timestamp is None:
            new_pages = []
        else:
            new_pages = [
                {
                    "title": c["title"],
                    "url": f"{base_url}/wiki/{quote(c['title'].replace(' ', '_'))}",
                    "timestamp": c["timestamp"],
                }
                for c in changes
                if c.get("title") and c.get("timestamp")
            ]

        if changes:
            latest_timestamp = max(c["timestamp"] for c in changes)
            state_file.write_text(json.dumps({"last_timestamp": latest_timestamp}, indent=2))
        elif last_timestamp is None:
            # 没有任何历史变更也要建立基线（用当前时间），否则每次都会被当成"首次"
            from datetime import datetime, timezone

            state_file.write_text(
                json.dumps(
                    {"last_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                    indent=2,
                )
            )

        return True, "", new_pages

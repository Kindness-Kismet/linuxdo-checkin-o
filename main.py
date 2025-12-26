"""
cron: 0 */6 * * *
new Env("Linux.Do 签到")
"""

import os
import random
import time
import functools
import sys
import re
from loguru import logger
from DrissionPage import ChromiumOptions, Chromium
from tabulate import tabulate
from curl_cffi import requests
from bs4 import BeautifulSoup


def retry_decorator(retries=3):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        logger.error(f"函数 {func.__name__} 最终执行失败: {str(e)}")
                    logger.warning(
                        f"函数 {func.__name__} 第 {attempt + 1}/{retries} 次尝试失败: {str(e)}"
                    )
                    time.sleep(1)
            return None

        return wrapper

    return decorator


os.environ.pop("DISPLAY", None)
os.environ.pop("DYLD_LIBRARY_PATH", None)

USERNAME = os.environ.get("LINUXDO_USERNAME")
PASSWORD = os.environ.get("LINUXDO_PASSWORD")
BROWSE_ENABLED = os.environ.get("BROWSE_ENABLED", "true").strip().lower() not in [
    "false",
    "0",
    "off",
]
if not USERNAME:
    USERNAME = os.environ.get("USERNAME")
if not PASSWORD:
    PASSWORD = os.environ.get("PASSWORD")
GOTIFY_URL = os.environ.get("GOTIFY_URL")
GOTIFY_TOKEN = os.environ.get("GOTIFY_TOKEN")
SC3_PUSH_KEY = os.environ.get("SC3_PUSH_KEY")

HOME_URL = "https://linux.do/"
LOGIN_URL = "https://linux.do/login"
SESSION_URL = "https://linux.do/session"
CSRF_URL = "https://linux.do/session/csrf"


class LinuxDoBrowser:
    def __init__(self) -> None:
        from sys import platform

        if platform.startswith("linux"):
            platformIdentifier = "X11; Linux x86_64"
        elif platform == "darwin":
            platformIdentifier = "Macintosh; Intel Mac OS X 10_15_7"
        else:
            platformIdentifier = "Windows NT 10.0; Win64; x64"

        co = (
            ChromiumOptions()
            .headless(True)
            .incognito(True)
            .set_argument("--no-sandbox")
        )
        co.set_user_agent(
            f"Mozilla/5.0 ({platformIdentifier}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        self.browser = Chromium(co)
        self.page = self.browser.new_tab()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )

    def login(self):
        logger.info("开始登录")
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LOGIN_URL,
        }
        resp_csrf = self.session.get(CSRF_URL, headers=headers, impersonate="chrome136")
        csrf_token = resp_csrf.json().get("csrf")

        headers.update(
            {
                "X-CSRF-Token": csrf_token,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://linux.do",
            }
        )

        data = {
            "login": USERNAME,
            "password": PASSWORD,
            "second_factor_method": "1",
            "timezone": "Asia/Shanghai",
        }

        resp_login = self.session.post(
            SESSION_URL, data=data, headers=headers, impersonate="chrome136"
        )

        if resp_login.status_code != 200 or resp_login.json().get("error"):
            logger.error("登录失败")
            return False

        logger.success("登录成功")
        self.print_connect_info()

        cookies = [
            {"name": k, "value": v, "domain": ".linux.do", "path": "/"}
            for k, v in self.session.cookies.get_dict().items()
        ]
        self.page.set.cookies(cookies)
        self.page.get(HOME_URL)
        time.sleep(5)
        return True

    def click_topic(self):
        topic_list = self.page.ele("@id=list-area").eles(".:title")
        if not topic_list:
            logger.error("未找到主题帖")
            return False

        count = min(25, len(topic_list))
        logger.info(f"发现 {len(topic_list)} 个主题帖，随机选择 {count} 个")

        for topic in random.sample(topic_list, count):
            self.click_one_topic(topic.attr("href"))
        return True

    @retry_decorator()
    def click_one_topic(self, topic_url):
        page = self.browser.new_tab()
        page.get(topic_url)
        if random.random() < 0.3:
            self.click_like(page)
        self.browse_post(page)
        page.close()

    def browse_post(self, page):
        prev_url = None
        for _ in range(10):
            scroll_distance = random.randint(550, 650)
            page.run_js(f"window.scrollBy(0, {scroll_distance})")

            if random.random() < 0.03:
                break

            at_bottom = page.run_js(
                "window.scrollY + window.innerHeight >= document.body.scrollHeight"
            )
            if at_bottom and page.url == prev_url:
                break
            prev_url = page.url

            wait_time = random.uniform(4.5, 5.5)
            logger.info(f"等待 {wait_time:.2f} 秒...")
            time.sleep(wait_time)

    def click_like(self, page):
        try:
            btn = page.ele(".discourse-reactions-reaction-button")
            if btn:
                btn.click()
                time.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.error(f"点赞失败: {e}")

    def print_connect_info(self):
        resp = self.session.get("https://connect.linux.do/", impersonate="chrome136")
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table tr")
        data = []
        for r in rows:
            tds = r.select("td")
            if len(tds) >= 3:
                data.append([tds[0].text, tds[1].text or "0", tds[2].text or "0"])
        print(tabulate(data, headers=["项目", "当前", "要求"], tablefmt="pretty"))

    def send_notifications(self, browse_enabled):
        msg = "✅每日登录成功"
        if browse_enabled:
            msg += " + 浏览任务完成"

        if GOTIFY_URL and GOTIFY_TOKEN:
            requests.post(
                f"{GOTIFY_URL}/message",
                params={"token": GOTIFY_TOKEN},
                json={"title": "LINUX DO", "message": msg, "priority": 1},
            )

    def run(self):
        self.login()
        if BROWSE_ENABLED:
            self.click_topic()
        self.send_notifications(BROWSE_ENABLED)
        self.page.close()
        self.browser.quit()


if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        print("Please set USERNAME and PASSWORD")
        sys.exit(1)
    LinuxDoBrowser().run()

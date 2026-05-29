#!/usr/local/python3/bin/python3
import requests
import json
import logging
from pathlib import Path

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置管理
CONFIG = {
    "THINGSBOARD_HOST": "https://tb-web-test.moogo.com",
    "USERNAME": "tenant@thingsboard.org",
    "PASSWORD": "Moogo2023!@#",
    "PROMETHEUS_FILE": "/opt/proms/node_exporter/key/moogo_thingsboard.prom"
}

class ThingsBoardClient:
    def __init__(self):
        self.token = None

    def get_token(self):
        if self.token:
            return self.token

        try:
            # 构建登录请求
            login_payload = {
                "username": CONFIG["USERNAME"],
                "password": CONFIG["PASSWORD"]
            }
            login_url = f"{CONFIG['THINGSBOARD_HOST']}/api/auth/login"

            # 发送登录请求
            response = requests.post(login_url, json=login_payload)
            response.raise_for_status()

            # 从响应中获取 token
            self.token = response.json()["token"]
            return self.token
        except requests.exceptions.RequestException as e:
            logging.error(f"获取 token 失败: {e}")
            return None

    def write_token_status(self, value):
        try:
            file_path = Path(CONFIG["PROMETHEUS_FILE"])
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("w") as f:
                data = f"get_token_status_thingsboard{{app_vego=\"thingsboard-moogo-test\",env=\"test\"}} {value}\n"
                print(data)
                f.write(data)
        except Exception as e:
            logging.error(f"写入 Prometheus 文件失败: {e}")

# 使用示例
client = ThingsBoardClient()
token = client.get_token()
if token:
    print(token)
    client.write_token_status(1)
else:
    client.write_token_status(0)

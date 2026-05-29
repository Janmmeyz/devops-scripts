#!/usr/local/python3/bin/python3

import requests
from pathlib import Path
import sys
parent_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(parent_dir))
from common.Unit_Log import Logger

# 配置日志记录
log = Logger()

# 配置管理
CONFIG = {
    "THINGSBOARD_HOST": "https://tb-web.vego.com",
    "USERNAME": "tenant@thingsboard.org",
    "PASSWORD": "Vgctenant2024!@#prd",
    # "PROMETHEUS_FILE": "/opt/proms/node_exporter/key/composter_thingsboard.prom"
    "PROMETHEUS_FILE": "composter_thingsboard.prom"
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
            log.error(f"获取 token 失败: {e}")
            return None

def write_token_status(value):
    try:
        file_path = Path(CONFIG["PROMETHEUS_FILE"])
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("w") as f:
            data = f"get_token_status_thingsboard{{app_vego=\"thingsboard-composter-prd\",env=\"prd\"}} {value}\n"
            log.info(f"data: {data}")
            f.write(data)
    except Exception as e:
        log.error(f"写入 Prometheus 文件失败: {e}")


# 使用示例
if __name__ == "__main__":
    client = ThingsBoardClient()
    token = client.get_token()
    if token:
        log.info(f"token: {token}")
        write_token_status(1)
    else:
        write_token_status(0)

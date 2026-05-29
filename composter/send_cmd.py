#!/usr/local/python3/bin/python3
import requests
import json
import sys
from pathlib import Path
parent_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(parent_dir))
from common.Unit_Log import Logger

# 配置日志记录
log = Logger()


# Composter prd ThingsBoard API 端点
rpc_url = "https://tb-web.vego.com/api/plugins/rpc/twoway/{device_id}"
auth_url = "https://tb-web.vego.com/api/auth/login"

# ThingsBoard 用户名和密码
username = "tenant@thingsboard.org"
password = "Vgctenant2024!@#prd"

# 设备 ID
# device_id = "b48cfa30-53c7-11ef-bdc8-ed27152126cf"  # old
device_id = "f892a8e0-6607-11ef-bdc8-ed27152126cf"

# RPC 请求负载
rpc_request = {"method": "queryInfo", "params": {}}

# Prometheus 指标文件路径
#file_proms = "../key/moogo_thingsboard_send.prom"
# file_proms = "/opt/proms/node_exporter/key/composter_prd_thingsboard_send.prom"
file_proms = "composter_prd_thingsboard_send.prom"


try:
    # 获取访问令牌
    auth_payload = {
        "username": username,
        "password": password
    }
    auth_response = requests.post(auth_url, json=auth_payload)

    log.info(f"auth_response http code for get token is {auth_response.status_code}")
    if auth_response.status_code == 200:
        access_token = auth_response.json()["token"]
        headers = {
            "Content-Type": "application/json",
            "X-Authorization": f"Bearer {access_token}"
        }

        # 发送 RPC 请求
        try:
            response = requests.post(rpc_url.format(device_id=device_id), data=json.dumps(rpc_request), headers=headers)
            log.info(f"rpc response status_code is {response.status_code}")
            # log.info(f"response.text: {response.text}")
            if response.status_code == 200 or response.status_code == 409:
                log.info(f"response.text: {response.text}")
                with open(file_proms, "w") as f:
                    data = "send_cmd_status_thingsboard{app_vego=\"thingsboard-composter-prd\",env=\"prd\"} 1\n"
                    log.info(f"data: {data}")
                    f.write(data)
            else:
                log.error(f"http code status not ok, status_code: {response.status_code}, response.text: {response.text}")
                with open(file_proms, "w") as f:
                    data = "send_cmd_status_thingsboard{app_vego=\"thingsboard-composter-prd\",env=\"prd\"} 0\n"
                    log.info(f"data: {data}")
                    f.write(data)
        except requests.exceptions.RequestException as e:
            log.error(f"Error sending RPC request: {e}")
    else:
        log.error(f"Error getting access token: {auth_response.text}")
except Exception as e:
    log.error(f"An error occurred: {e}")

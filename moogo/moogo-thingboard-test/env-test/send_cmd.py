#!/usr/local/python3/bin/python3
import requests
import json
import logging

# ThingsBoard API 端点
rpc_url = "https://tb-web-test.moogo.com/api/plugins/rpc/twoway/{device_id}"
auth_url = "https://tb-web-test.moogo.com/api/auth/login"

# ThingsBoard 用户名和密码
username = "tenant@thingsboard.org"
password = "Moogo2023!@#"

# 设备 ID
device_id = "a2fc4840-006a-11ee-8459-f57974554a53"   # 正确的设备id
# device_id = "a2fc4840-006a-11ee-8459-f57974554a54"   # 模拟告警使用错误的id

# RPC 请求负载
rpc_request = {"method": "queryInfo", "params": {}}

# Prometheus 指标文件路径
#file_proms = "../key/moogo_thingsboard_send.prom"
file_proms = "/opt/proms/node_exporter/key/moogo_thingsboard_send.prom"

# 配置日志
#logging.basicConfig(filename='../logs/moogo_thingsboard_test.log', level=logging.ERROR, format='%(asctime)s %(levelname)s: %(message)s')
logging.basicConfig(filename='/opt/logs/moogo_thingsboard_test.log', level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

try:
    # 获取访问令牌
    auth_payload = {
        "username": username,
        "password": password
    }
    auth_response = requests.post(auth_url, json=auth_payload)

    if auth_response.status_code == 200:
        logging.info(f"http code for get token is 200")
        access_token = auth_response.json()["token"]
        headers = {
            "Content-Type": "application/json",
            "X-Authorization": f"Bearer {access_token}"
        }

        # 发送 RPC 请求
        try:
            response = requests.post(rpc_url.format(device_id=device_id), data=json.dumps(rpc_request), headers=headers)
            logging.info(response.status_code)
            if response.status_code == 200:
                logging.info(response.text)
                with open(file_proms, "w") as f:
                    data = "send_cmd_status_thingsboard{app_vego=\"thingsboard-moogo-test\",env=\"test\"} 1\n"
                    logging.info(data)
                    f.write(data)
            else:
                logging.info("http code status not ok")
                logging.info(response.status_code)
                logging.info(response.text)
                with open(file_proms, "w") as f:
                    data = "send_cmd_status_thingsboard{app_vego=\"thingsboard-moogo-test\",env=\"test\"} 0\n"
                    print(data)
                    f.write(data)
        except requests.exceptions.RequestException as e:
            logging.error(f"Error sending RPC request: {e}")
    else:
        logging.error(f"Error getting access token: {auth_response.text}")
except Exception as e:
    logging.error(f"An error occurred: {e}")

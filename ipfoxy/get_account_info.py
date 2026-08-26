import sys
import requests
import json
import boto3
import base64
from botocore.exceptions import ClientError
from datetime import datetime
from common.Unit_Log import Logger

log = Logger()


def get_secret(secret_name, region_name="us-east-1"):
    """
    从 AWS Secrets Manager 获取密钥

    参数:
        secret_name: 密钥名称 (ARN 或名称)
        region_name: AWS 区域

    返回:
        dict: 密钥键值对
    """
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            log.error("密钥未找到")
        elif e.response["Error"]["Code"] == "InvalidRequestException":
            log.error("请求参数无效")
        elif e.response["Error"]["Code"] == "InvalidParameterException":
            log.error("参数无效")
        raise e
    else:
        # 根据密钥类型解析
        if "SecretString" in get_secret_value_response:
            secret = get_secret_value_response["SecretString"]
            return json.loads(secret)
        else:
            decoded_binary_secret = base64.b64decode(
                get_secret_value_response["SecretBinary"]
            )
            return json.loads(decoded_binary_secret)


def send_feishu_notify(feishu_webhook, content: str):
    """发送飞书文本告警消息"""
    payload = {
        "msg_type": "text",
        "content": {"text": f"【IPFoxy代理告警】\n{content}"},
    }
    try:
        resp = requests.post(feishu_webhook, json=payload, timeout=10)
        res_json = resp.json()
        if res_json.get("code") != 0:
            log.error(f"飞书推送失败:{res_json}")
        else:
            log.info("飞书告警消息已发送")
    except Exception as e:
        log.error(f"飞书接口异常：{e}")


def get_ipfoxy_main_plan():
    TRAFFIC_ALERT_THRESHOLD_GB = 0.5
    EXPIRE_ALERT_DAY = 1
    
    secret = get_secret(
        "vego-garden/devops-alert/ipfoxy/production", region_name="us-east-1"
    )
    feishu_token = secret["feishu"]
    feishu_webhook_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{feishu_token}"
    # slack_token = secret["slack"]
    # slack_webhook_url = f"https://hooks.slack.com/services/{slack_token}"
    api_id = secret.get("ipfoxy_api_id")
    api_token = secret.get("ipfoxy_api_token")
    base_url = secret.get("ipfoxy_base_url")
    # log.info(feishu_webhsecret["slack"]ook_url)
    headers = {"api-id": api_id, "api-token": api_token}
    url = f"{base_url}/ip/open-api/residential-data"

    """获取IPFoxy主套餐信息residential-data"""
    resp = requests.get(url, headers=headers, timeout=15)
    j = resp.json()
    if j.get("code") != 0:
        raise Exception(f"IPFoxy接口调用失败 code={j.get('code')}, msg={j.get('msg')}")
    d = j["data"]
    total_gb = float(d["total_mb"]) / 1024
    remain_gb = float(d["remain_mb"]) / 1024
    expire_ts = int(d["expire_time"])
    expire_datetime = datetime.fromtimestamp(expire_ts)
    now = datetime.now()
    delta_seconds = expire_ts - now.timestamp()
    delta_days = delta_seconds / 86400  # 剩余天数

    try:
            
        log.info(f"套餐总流量:{round(total_gb,2)} GB")
        log.info(f"套餐剩余流量:{round(remain_gb,2)} GB")
        log.info(f"套餐到期时间:{expire_datetime}")
        log.info(f"距离到期剩余天数:{round(delta_days,2)} 天")

        alert_messages = []
        # 判断流量告警
        if round(remain_gb, 2) < TRAFFIC_ALERT_THRESHOLD_GB:
            alert_messages.append(
                f"剩余流量不足 {TRAFFIC_ALERT_THRESHOLD_GB}GB，当前剩余 {round(remain_gb, 2)} GB"
            )
        # 判断到期告警
        if round(delta_days, 2) < EXPIRE_ALERT_DAY:
            alert_messages.append(
                f"套餐即将到期！剩余 {round(delta_days, 2)} 天，到期时间 {expire_datetime}"
            )

        if len(alert_messages) > 0:
            msg = "\n".join(alert_messages)
            log.info(f"msg: {msg}")
            send_feishu_notify(feishu_webhook=feishu_webhook_url,content=msg)
        else:
            log.info(f"一切正常，无需告警\n告警阈值:\n剩余流量: {TRAFFIC_ALERT_THRESHOLD_GB}GB\n剩余天数: {EXPIRE_ALERT_DAY}天")

    except Exception as err:
        err_msg = f"脚本执行异常:{str(err)}"
        log.error(f"err_msg: {err_msg}")
        send_feishu_notify(feishu_webhook=feishu_webhook_url,content=err_msg)
    # return {
    #     "total_gb": round(total_gb, 2),
    #     "remain_gb": round(remain_gb, 2),
    #     "expire_dt": expire_datetime,
    #     "remain_days": round(delta_days, 2),
    # }


if __name__ == "__main__":
    get_ipfoxy_main_plan()
    

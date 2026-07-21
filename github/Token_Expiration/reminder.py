import requests
from datetime import datetime, UTC
import json
from common.Unit_Log import Logger
import boto3
import base64
from botocore.exceptions import ClientError
import ast
from send_feishu_slack import send_feishu_alert_via_webhook,send_slack_alert_via_webhook
log = Logger()

# ---------------------- 配置区 ----------------------
# 提前几天告警：7天
WARN_DAYS =  7
# -----------------------------------------------------
def get_secret(secret_name, region_name="us-east-1"):
    """
    Retrieve a secret from AWS Secrets Manager

    Parameters:
        secret_name: Secret name (ARN or name)
        region_name: AWS region

    Returns:
        dict: Secret key-value pairs
    """
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            log.error("Secret not found")
        elif e.response["Error"]["Code"] == "InvalidRequestException":
            log.error("Invalid request parameters")
        elif e.response["Error"]["Code"] == "InvalidParameterException":
            log.error("Invalid parameters")
        raise e
    else:
        # Parse based on secret type
        if "SecretString" in get_secret_value_response:
            secret = get_secret_value_response["SecretString"]
            return json.loads(secret)
        else:
            decoded_binary_secret = base64.b64decode(
                get_secret_value_response["SecretBinary"]
            )
            return json.loads(decoded_binary_secret)

def parse_expire_timestamp(exp_str):
    """解析时间并返回 UTC 时间戳（统一计算基准）"""
    fmt1 = "%Y-%m-%dT%H:%M:%SZ"
    fmt2 = "%Y-%m-%d %H:%M:%S %Z"
    try:
        dt = datetime.strptime(exp_str, fmt1)
    except ValueError:
        try:
            dt = datetime.strptime(exp_str, fmt2)
        except ValueError:
            return None
    # 转为时间戳，无视时区对象差异
    return dt.timestamp()

def check_github_token_expiry(token):
    url = "https://api.github.com/user"
    headers = {
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"

        exp_str = resp.headers.get("GitHub-Authentication-Token-Expiration")
        if not exp_str:
            return None, "never expires (classic token)"

        ts = parse_expire_timestamp(exp_str)
        if ts is None:
            return None, f"时间格式解析失败: {exp_str}"
        return ts, exp_str
    except Exception as e:
        return None, str(e)



def main():
    secret = get_secret("vego-garden/devops-alert/github/production", region_name="us-east-1")
    github_token_str= secret["GitHub_Token_List"]
    feishu_token = secret["feishu"]
    feishu_webhook_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{feishu_token}"
    slack_token = secret["slack"]
    slack_webhook_url = f"https://hooks.slack.com/services/{slack_token}"
    # log.info(f"github_token_str:{github_token_str}")
    # log.info(f"type:{type(github_token_str)}")
    github_token_list= ast.literal_eval(github_token_str)
    now_ts = datetime.now(UTC).timestamp()
    warn_list = []

    for item in github_token_list:
        name = item["name"]
        token = item["token"]
        exp_ts, exp_str = check_github_token_expiry(token)

        if exp_ts is None:
            log.info(f"[{name}] {exp_str}")
            continue

        # 时间戳差值计算剩余秒数
        diff_sec = exp_ts - now_ts
        days_left = int(diff_sec / (24 * 3600))
        log.info(f"[{name}] 剩余 {days_left} 天，过期时间: {exp_str}")

        if days_left <= WARN_DAYS:
            warn_list.append({
                "name": name,
                "exp_time": exp_str,
                "days_left": days_left
            })

    if warn_list:
        msg_lines = [f"GitHub Token 即将过期（不足{WARN_DAYS}天）："]
        for w in warn_list:
            msg_lines.append(f"- {w['name']}：剩余 {w['days_left']} 天，过期时间 {w['exp_time']}")
        msg = "\n".join(msg_lines)
        log.info("\n" + msg)
        send_feishu_alert_via_webhook(feishu_webhook_url, msg)
        # send_slack_alert_via_webhook(message=msg,webhook_url=slack_webhook_url,channel_id="jenkins_alert")
    else:
        log.info("所有 Token 有效期正常，无需告警。")

if __name__ == "__main__":
    main()
    
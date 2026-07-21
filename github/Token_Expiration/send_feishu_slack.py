import sys
import requests
import json
import boto3
import base64
from botocore.exceptions import ClientError


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
            print("密钥未找到")
        elif e.response["Error"]["Code"] == "InvalidRequestException":
            print("请求参数无效")
        elif e.response["Error"]["Code"] == "InvalidParameterException":
            print("参数无效")
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


def send_feishu_alert_via_webhook(webhook_url, content):
    """
    发送飞书Markdown格式告警
    
    :param webhook_url: 飞书机器人Webhook地址
    :param title: 告警标题
    :param content: Markdown格式内容
    """
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True
            },
            # "header": {
            #     "title": {
            #         "tag": "plain_text",
            #         "content": title
            #     },
            #     "template": "red"  # 红色标题，可选 red/blue/green/yellow
            # },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",  # 飞书Markdown格式
                        "content": content
                    }
                },
                # {
                #     "tag": "action",
                #     "actions": [
                #         {
                #             "tag": "button",
                #             "text": {
                #                 "tag": "plain_text",
                #                 "content": "detail"
                #             },
                #             "type": "primary",
                #             "url": detail_url  # 实际URL
                #         }
                #     ]
                # }
            ]
        }
    }
    # print(payload)
    try:
        response = requests.post(
            webhook_url,
            headers=headers,
            data=json.dumps(payload))
        response.raise_for_status()
        print("飞书告警发送成功")
    except Exception as e:
        print(f"飞书告警发送失败: {str(e)}")

def send_slack_alert_via_webhook(message, webhook_url,channel_id):
    """
    使用 Incoming Webhook 发送告警消息
    
    参数:
        message: 要发送的告警内容
        webhook_url: Slack Webhook URL
    """
    payload = {
        "text": message,
        "username": "Jenkins Alert",
        # "username": "Alert Bot",  # 自定义发送者名称
        # "icon_emoji": ":warning:",  # 自定义图标
        # "channel": "#alerts"  # 可覆盖创建时的默认频道
        "channel": channel_id
    }
    
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers=headers
        )
        response.raise_for_status()
        print("Slack告警发送成功")
    except requests.exceptions.RequestException as e:
        print(f"Slack发送告警失败: {e}")

# 示例调用
if __name__ == "__main__":
    secret = get_secret("vego-garden/devops-alert/jenkins/production", region_name="us-east-1")
    feishu_token = secret["feishu"]
    feishu_webhook_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{feishu_token}"
    slack_token = secret["slack"]
    slack_webhook_url = f"https://hooks.slack.com/services/{slack_token}"
    # print(feishu_webhook_url)

    args = sys.argv
    message_text=args[1]
    lines = message_text.splitlines()
    title=lines[1].lstrip()
    content_text='\n'.join(item.lstrip() for item in lines[:-2]) + '\n'
    log_url_str=lines[len(lines)-2]
    logs_list=log_url_str.split(': ')
    # content_text=f"{content_text}{logs_list[0].lstrip()}:"
    detail_url=logs_list[1].lstrip()
    # print(f"detail_url: {detail_url}")
    # print(f"title: {title}\n\n content_text:{content_text}")
    alert_title='JenkinsAlert'
    alert_content=content_text
    send_feishu_alert_via_webhook(feishu_webhook_url, alert_title, alert_content,detail_url)
    send_slack_alert_via_webhook(message=alert_content,webhook_url=slack_webhook_url,channel_id="jenkins_alert")

#!/usr/local/python3/bin/python3
import requests
import json
from datetime import datetime
class FeishuAlert():
    def __init__(self):
        self.headers = {'Content-Type': 'application/json'}

    def post_to_robot(self,title,content,webhook_url):
        # webhook：飞书群地址url
        webhook = webhook_url
        # headers: 请求头
        headers = self.headers

        # alert_headers: 告警消息标题
        alert_headers = title
        ## 检测时间
        formatted_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # alert_content: 告警消息内容，用户可根据自身业务内容，定义告警内容
        alert_content = "服务器检测时间:{0}\n".format(formatted_time)+content
        # message_body: 请求信息主体
        message_body = {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "content": alert_content,
                            "tag": "lark_md"
                        }
                    }
                ],
                "header": {
                    "template": "red",
                    "title": {
                        "content": alert_headers,
                        "tag": "plain_text"
                    }
                }
            }}
        response = requests.request("POST", webhook, headers=headers, data=json.dumps(message_body))
        print(response)


# if __name__ == '__main__':
#     content="最近5分钟，当level:E ,device的列表如下："
#
#     alert_feishu = FeishuAlert()
#     alert_feishu.post_to_robot("Moogo设备告警",content,"webhook")

#!/usr/local/python3/bin/python3
from datetime import datetime, timedelta
from elasticsearch import Elasticsearch
from tools import feishu

"""
### es告警
# devops_monitor/Vego2024--asdfg
"""

# es = Elasticsearch("http://44.216.126.2:9200",basic_auth=("elastic","Vego@#2022"))
#es = Elasticsearch("http://44.216.126.2:9200",basic_auth=("devops-monitor","Vego2024--asdfg"))
es = Elasticsearch("http://172.31.13.122:9200",basic_auth=("devops-monitor","Vego2024--asdfg"))

# 设置查询时间范围
end_time = datetime.now()
# start_time = end_time - timedelta(hours=1)
start_time = end_time - timedelta(minutes=30)
#start_time = end_time - timedelta(days=30)   # 30 小时

## 输出当前月份数字和年份数字
current_month = datetime.now().month
formatted_month = f"{current_month:02}"
current_year = datetime.now().year
########################
# 数据处理函数
def chuli_data(data_list):
    content = "最近30分钟，当message字段中有reset_reason内容，设备和消息的列表如下:"
    device_message_list = "\n".join([f"- 设备: {d['device']}, 消息: {d['message']}" for d in data_list])
    full_content = f"{content}\n{device_message_list}"
    print(full_content)
    return full_content

##### 构建查询
query = {
    "query": {
        "bool": {
            "must": [
                {
                    "range": {
                        "@timestamp": {
                            "gte": start_time.isoformat(),
                            "lte": end_time.isoformat()
                        }
                    }
                }

            ]
        }
    },
    "size":10000
}


# # 使用通配符查询索引
# index_pattern = 'moogo_diagnostic_log*'  # 替换为你的索引匹配模式

###
#index="moogo_diagnostic_log_{0}.{1}".format(current_year,formatted_month)
index_pattern='moogo_diagnostic_log*'

# print(index)
response = es.search(index=index_pattern,body=query)
# print(response)

# message字段中有reset_reason的时候告警
devices = []
for hit in response['hits']['hits']:
    if "reset_reason".lower() in hit['_source']['message'].lower():
        device_value = hit['_source'].get('device')
        message_value = hit['_source'].get('message')  # 获取 message 字段
        if device_value and message_value:
            devices.append({'device': device_value, 'message': message_value})  # 将设备和消息一起存储


last_content=chuli_data(devices)

## 判断列表是否为空，在决定是否发送告警
if  bool(devices):
    print("列表不为空")
    alert_feishu = feishu.FeishuAlert()
    webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/292f9a03-8d2f-4fa2-ba70-e19b886df17e"
    alert_feishu.post_to_robot("Moogo设备告警", last_content,webhook)


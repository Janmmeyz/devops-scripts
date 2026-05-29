#!/usr/local/python3/bin/python3
import paho.mqtt.client as mqtt
import json
import time
import sys
from pathlib import Path
parent_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(parent_dir))
from common.Unit_Log import Logger

# 配置日志记录
log = Logger()

#file_proms = "../key/composter_thingsboard_mqtt.prom"
# file_proms = "/opt/proms/node_exporter/key/composter_thingsboard_mqtt.prom"
file_proms = "composter_thingsboard_mqtt.prom"

# composter 配置 ThingsBoard 访问信息
TB_HOST = "tb-mqtt.vego.com"
TB_PORT = 1883
TB_ACCESS_TOKEN = "xkX8lfDrxslBrARupA7X"  # composter正确的token
#TB_ACCESS_TOKEN = "8VP85Uoed7p24MTkhlV9"  # 模拟告警
TB_SUBSCRIBE_TOPIC = "v1/devices/me/rpc/response/0"    # 订阅主题
TB_PUBLISH_TOPIC = "v1/devices/me/rpc/request/0"     # 状态上报的主题

## 写文件函数
def write_to_file(file_path, data):
    with open(file_path, "w") as f:
        log.info(data)
        f.write(data)

# 定义 MQTT 回调函数
def on_connect(client, userdata, flags, rc):
    log.info(f"Connected to ThingsBoard with result code {str(rc)}")
    client.subscribe(TB_SUBSCRIBE_TOPIC)

def on_message(client, userdata, msg):
    log.info(f"Received message on topic {msg.topic}: {msg.payload.decode()}")
    # 在这里处理接收到的消息
    data = json.loads(msg.payload.decode())
    log.info(data)

# 创建 MQTT 客户端
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

# 连接 ThingsBoard 服务器
client.username_pw_set(TB_ACCESS_TOKEN)
client.connect(TB_HOST, TB_PORT, 60)

# 发送 RPC 请求
def send_rpc_request(playload):
    client.publish(TB_PUBLISH_TOPIC, json.dumps(playload))

# 接收 RPC 响应
def on_rpc_response(client, userdata, msg):
    if msg.topic.startswith("v1/devices/me/rpc/response/"):
        log.info(f"Received RPC response: {msg.payload.decode()}")
        response = json.loads(msg.payload.decode())
        # 在这里处理 RPC 响应
        # print(response)
        log.info(f"response:{response}")
        file_data = "mqtt_send_res_thingsboard{app_vego=\"thingsboard-composter-test\",env=\"prd\"} 1\n"
        write_to_file(file_proms,file_data)
    else:
        file_data = "mqtt_send_res_thingsboard{app_vego=\"thingsboard-composter-prd\",env=\"prd\"} 0\n"
        write_to_file(file_proms,file_data)

## 回调
client.message_callback_add(f"v1/devices/me/rpc/response/#", on_rpc_response)

def main():
    # 保持连接并订阅主题
    client.loop_start()

    # 发送 RPC 请求
    playload = {"method": "status", "params": {"data": "1", "messageId": "1"}}

    # send_rpc_request("状态上报开始", playload)
    send_rpc_request(playload)

    # 等待 RPC 响应
    time.sleep(5)

    client.loop_stop()

if __name__ == "__main__":
    main()

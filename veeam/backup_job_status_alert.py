import requests
import urllib3
from common.Unit_Log import Logger
import json
import boto3
import base64
from botocore.exceptions import ClientError

log = Logger()
# 禁用自签名证书引发的无视警告（生产环境中建议使用有效证书）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        "content": {"text": f"【Veeam Backup失败告警】\n{content}"},
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

def get_appliance_access_token(base_url, username, password, api_version="1.9-rev0"):
    """请求 API Token"""
    token_url = f"{base_url}/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "x-api-version": api_version,
    }
    payload = {"grant_type": "password", "username": username, "password": password}

    response = requests.post(token_url, data=payload, headers=headers, verify=False)
    response.raise_for_status()
    return response.json().get("access_token")


def get_appliance_job_policies(api_url, description, token, api_version="1.9-rev0"):
    """获取 AWS Job 备份策略"""
    appliance_job_polices_info = []
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-api-version": api_version,
        }
        res = requests.get(api_url, headers=headers, verify=False)
        res.raise_for_status()
        res_json = res.json()
        jobs = (
            res_json.get("results", res_json)
            if isinstance(res_json, dict)
            else res_json
        )
        log.info(f"共成功获取到 {len(jobs)} 个 {description} 备份 Job")
        log.info("=" * 60)
        for job in jobs:
            job_info = {
                "id": job.get("id"),
                "job_name": job.get("name"),
                "description": job.get("description", "N/A"),
                "status": job.get("isEnabled"),
                "lastPolicySessionStatus": job.get("lastPolicySessionStatus", "N/A"),
            }
            appliance_job_polices_info.append(job_info)
            log.info(f"appliance_job_data:{job_info}")
    except requests.exceptions.HTTPError as e:
        log.error(f" HTTP 请求失败: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        log.error(f" 发生错误: {e}")

    return appliance_job_polices_info


def get_appliance_jobs_status(aws_secret="vego-garden/devops-alert/veeam/production"):
    secret = get_secret(aws_secret, region_name="us-east-1")
    appliance_base_url = secret.get("veeam_appliance_base_url")
    appliance_username = secret.get("veeam_appliance_username")
    appliance_password = secret.get("veeam_appliance_password")
    appliance_api_version = secret.get("veeam_appliance_api_version")
    appliance_apis = [
        {
            "api_url": f"{appliance_base_url}/virtualMachines/policies",
            "description": "EC2",
        },
        {"api_url": f"{appliance_base_url}/rds/policies", "description": "RDS"},
    ]
    appliance_data = []
    try:
        log.info("正在获取 Appliance Access Token...")
        token = get_appliance_access_token(
            appliance_base_url,
            appliance_username,
            appliance_password,
            api_version=appliance_api_version,
        )
        log.info(f"Token 获取成功！")
        # 获取各策略的状态
        log.info("正在拉取 AWS 备份 Policy 列表...")
        for appliance_api in appliance_apis:
            api_url = appliance_api.get("api_url")
            description = appliance_api.get("description")
            appliance_job_data = get_appliance_job_policies(
                api_url=api_url,
                description=description,
                token=token,
                api_version=appliance_api_version,
            )
            appliance_data.extend(appliance_job_data)

    except requests.exceptions.HTTPError as e:
        log.error(f" HTTP 请求失败: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        log.error(f" 发生错误: {e}")
    return appliance_data


def get_vbr_access_token(base_url, username, password, api_version="1.3-rev2"):
    token_url = f"{base_url}/oauth2/token"
    payload = {
        "grant_type": "password",
        "username": username,
        "password": password,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "x-api-version": api_version,
    }
    resp = requests.post(
        token_url, data=payload, headers=headers, verify=False, timeout=20
    )
    resp.raise_for_status()
    token_data = resp.json()

    return token_data["access_token"]


def get_vbr_jobs_states(api_url, description, token, api_version="1.3-rev2"):
    log.info(f"api_url:{api_url}")
    vbr_job_states_info = []
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            # "Accept": "application/json",
            "x-api-version": api_version,
        }
        # query = {
        #     "skip": "0",
        #     "limit": "200",
        #     "typeFilter": "CloudBackupAWS",
        # }
        resp = requests.get(api_url, headers=headers, verify=False, timeout=20)
        resp.raise_for_status()
        res_json = resp.json()
        jobs = (
            res_json.get("data", res_json) if isinstance(res_json, dict) else res_json
        )
        log.info(f"共成功获取到 {len(jobs)} 个 {description} 备份 Job")
        log.info("=" * 60)
        for job in jobs:
            status = False if job.get("status") == "Disabled" else True
            lastPolicySessionStatus="Succeeded" if job.get("lastResult") == "Success" else "Failed"
            job_info = {
                "id": job.get("id"),
                "job_name": job.get("name"),
                "description": job.get("description", "N/A"),
                "status": status,
                "lastPolicySessionStatus": lastPolicySessionStatus,
            }
            vbr_job_states_info.append(job_info)
            log.info(f"vbr_job_data:{job_info}")
    except requests.exceptions.HTTPError as e:
        log.error(f" HTTP 请求失败: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        log.error(f" 发生错误: {e}")

    return vbr_job_states_info


def get_vbr_jobs_status(aws_secret):
    secret = get_secret(aws_secret, region_name="us-east-1")
    vbr_base_url = secret.get("veeam_vbr_base_url")
    vbr_username = secret.get("veeam_vbr_username")
    vbr_password = secret.get("veeam_vbr_password")
    vbr_api_version = secret.get("veeam_vbr_api_version")
    vbr_jobs_api = f"{vbr_base_url}/v1/jobs/states"
    vbr_data = []
    try:
        log.info("正在获取 VBR Access Token...")
        token = get_vbr_access_token(
            vbr_base_url, vbr_username, vbr_password, api_version=vbr_api_version
        )
        log.info(f"VBR Token 获取成功！")
        # 获取各策略的状态
        log.info("正在拉取 VBR 备份 Job 列表...")
        description = "VBR"
        appliance_job_data = get_vbr_jobs_states(
            api_url=vbr_jobs_api,
            description=description,
            token=token,
            api_version=vbr_api_version,
        )
        vbr_data.extend(appliance_job_data)
    except requests.exceptions.HTTPError as e:
        log.error(f" HTTP 请求失败: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        log.error(f" 发生错误: {e}")
    return vbr_data

def main():
    AWS_SECRET = "vego-garden/devops-alert/veeam/production"
    veeam_job_status=[]
    veeam_job_status = get_appliance_jobs_status(AWS_SECRET)
    vbr_data = get_vbr_jobs_status(AWS_SECRET)
    veeam_job_status.extend(vbr_data)
    err_msg=''
    for job in veeam_job_status:
        if job.get("status"):
            if not job.get("lastPolicySessionStatus")=="Succeeded":
                err_msg =f"{err_msg}\njob_name: {job.get('job_name')}\nlastPolicySessionStatus: {job.get('lastPolicySessionStatus')} "
    if err_msg:
        log.info(f"message: {err_msg}")
        secret = get_secret(AWS_SECRET, region_name="us-east-1")
        feishu_token = secret["feishu"]
        feishu_webhook_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{feishu_token}"
        send_feishu_notify(feishu_webhook=feishu_webhook_url,content=err_msg)
if __name__ == "__main__":
    main()
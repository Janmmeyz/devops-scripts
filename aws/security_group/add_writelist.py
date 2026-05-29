from common.Unit_Log import Logger
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
import boto3
import base64
from botocore.exceptions import ClientError
import json
import pandas as pd
import io
import sys


log = Logger()


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


def read_google_drive_excel(service_account_info, file_id):
    """
    Read Excel file from Google Drive using service account

    Args:
        service_account_file (str): Path to service account JSON credentials file
        file_id (str): Google Drive file ID

    Returns:
        pd.DataFrame: DataFrame containing Excel data
    """
    try:
        # 1. Validate and load service account credentials
        try:
            if isinstance(service_account_info, str):
                info_dict = json.loads(service_account_info)
            else:
                info_dict = service_account_info

            credentials = service_account.Credentials.from_service_account_info(
                info_dict, scopes=["https://www.googleapis.com/auth/drive"]
            )
        except Exception as e:
            error_msg = (
                f"Failed to load service account credentials from variable: {str(e)}"
            )
            log.error(error_msg)
            raise RuntimeError(error_msg) from e

        # 2. Initialize Drive API service
        try:
            service = build("drive", "v3", credentials=credentials)
        except Exception as e:
            error_msg = f"Failed to initialize Drive API service: {str(e)}"
            log.error(error_msg)
            raise RuntimeError(error_msg) from e

        # 3. Download file content
        fh = io.BytesIO()
        try:
            request = service.files().export_media(
                fileId=file_id,
                mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            downloader = MediaIoBaseDownload(fh, request)

            done = False
            while not done:
                try:
                    status, done = downloader.next_chunk()
                    log.info(f"Download progress: {int(status.progress() * 100)}%")
                except HttpError as e:
                    if e.resp.status == 404:
                        error_msg = f"File not found, please check file ID: {file_id}"
                    elif e.resp.status == 403:
                        error_msg = (
                            "Permission denied, ensure service account has access"
                        )
                    else:
                        error_msg = f"File download HTTP error: {str(e)}"
                    log.error(error_msg)
                    raise RuntimeError(error_msg) from e
                except Exception as e:
                    error_msg = f"File download failed: {str(e)}"
                    log.error(error_msg)
                    raise RuntimeError(error_msg) from e

        except Exception as e:
            error_msg = f"File download initialization failed: {str(e)}"
            log.error(error_msg)
            raise RuntimeError(error_msg) from e

        # 4. Read Excel file
        try:
            fh.seek(0)  # Reset file pointer to beginning
            df = pd.read_excel(fh)
            log.info("Excel file read successfully")
            return df
        except Exception as e:
            error_msg = f"Excel file parsing failed: {str(e)}"
            log.error(error_msg)
            raise RuntimeError(error_msg) from e

    except Exception as e:
        # Catch all unhandled exceptions
        error_msg = f"Unhandled exception: {str(e)}"
        log.error(error_msg)
        raise  # Re-raise exception for upper level handling


def sync_security_group_with_status(aws_secret_name):
    ec2 = boto3.client("ec2")
    aws_secret_json = get_secret(aws_secret_name, region_name="us-east-1")
    google_service_account_info = aws_secret_json.get("google_service_account_info")
    google_drive_file_id = aws_secret_json.get("google_drive_file_id")
    desc_prefix = aws_secret_json.get("desc_prefix")
    sg_id = aws_secret_json.get("security_group_id")
    df = read_google_drive_excel(google_service_account_info, google_drive_file_id)

    # sg_ids = df["sg_id"].unique()
    # sg_df = df[df["sg_id"] == sg_id]
    sg_df = df

    # 获取当前 AWS 云端配置
    try:
        response = ec2.describe_security_groups(GroupIds=[sg_id])
        current_sg = response["SecurityGroups"][0]
    except Exception as e:
        log.error(f"获取 AWS 安全组 {sg_id} 失败，跳过。错误: {e}")

    # 提取云端带前缀的规则现况
    cloud_rules = {}
    for permission in current_sg.get("IpPermissions", []):
        protocol = permission.get("IpProtocol")
        from_port = permission.get("FromPort", 0)
        to_port = permission.get("ToPort", 0)

        for ip_range in permission.get("IpRanges", []):
            desc = ip_range.get("Description", "")
            if desc.startswith(desc_prefix):
                cloud_rules[desc] = {
                    "cidr": ip_range["CidrIp"],
                    "from_port": from_port,
                    "to_port": to_port,
                    "protocol": protocol,
                }

    for _, row in sg_df.iterrows():
        # excel_desc = str(row["description"])
        excel_cidr = f"{str(row["cidr"]).strip()}/32" if "/" not in str(row["cidr"]).strip() else str(row["cidr"]).strip()
        excel_from_port = int(row["from_port"])
        excel_to_port = int(row["to_port"])
        excel_protocol = str(row["protocol"]).strip().lower()
        excel_status = str(row["status"]).strip().lower()
        if excel_from_port == excel_to_port:
            excel_desc = f"{str(row["description"])}_{str(row["from_port"])}"
        else:
            excel_desc = f"{str(row["description"])}_{str(row["from_port"])} To {str(row["to_port"])}"
        if not excel_desc.startswith(desc_prefix):
            excel_desc = f"{desc_prefix}{excel_desc}"

        # --------------------------------------------------
        # 分流逻辑 1：Excel 中标记为 STATUS = DELETE
        # --------------------------------------------------
        if excel_status == "delete":
            if excel_desc in cloud_rules:
                cloud_item = cloud_rules[excel_desc]
                log.info(f"检测到删除指令：[{excel_desc}] 正在从 AWS 移除...")
                try:
                    ec2.revoke_security_group_ingress(
                        GroupId=sg_id,
                        IpPermissions=[
                            {
                                "IpProtocol": cloud_item["protocol"],
                                "FromPort": cloud_item["from_port"],
                                "ToPort": cloud_item["to_port"],
                                "IpRanges": [
                                    {
                                        "CidrIp": cloud_item["cidr"],
                                        "Description": excel_desc,
                                    }
                                ],
                            }
                        ],
                    )
                    log.info(f"成功删除 IP: {cloud_item['cidr']}, Description: {excel_desc}")
                except Exception as e:
                    log.error(f"删除失败: {e}")
            else:
                log.warning(
                    f"提示：Excel 标记了删除 [{excel_desc}]，但云端本就不存在，跳过。"
                )

            continue  # 处理下一条

        # --------------------------------------------------
        # 分流逻辑 2：Excel 中为 ACTIVE (新增或更新)
        # --------------------------------------------------
        if excel_desc in cloud_rules:
            cloud_item = cloud_rules[excel_desc]

            cloud_cidr = str(cloud_item["cidr"]).strip()
            cloud_proto = str(cloud_item["protocol"]).strip().lower()
            cloud_from = int(cloud_item["from_port"])
            cloud_to = int(cloud_item["to_port"])

            # 配置完全没变
            if (
                cloud_cidr == excel_cidr
                and cloud_from == excel_from_port
                and cloud_to == excel_to_port
                and cloud_proto == excel_protocol
            ):
                log.info(f"规则 [{excel_desc}] 未发生变化。")
            else:
                # 配置变了：先删旧，再加新
                log.info(f"规则 [{excel_desc}] 检测到配置变更，正在更新...")
                ec2.revoke_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=[
                        {
                            "IpProtocol": cloud_item["protocol"],
                            "FromPort": cloud_item["from_port"],
                            "ToPort": cloud_item["to_port"],
                            "IpRanges": [
                                {
                                    "CidrIp": cloud_item["cidr"],
                                    "Description": excel_desc,
                                }
                            ],
                        }
                    ],
                )
                ec2.authorize_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=[
                        {
                            "IpProtocol": excel_protocol,
                            "FromPort": excel_from_port,
                            "ToPort": excel_to_port,
                            "IpRanges": [
                                {"CidrIp": excel_cidr, "Description": excel_desc}
                            ],
                        }
                    ],
                )
                log.info(f"成功将 IP 从 [{cloud_item['cidr']}] 更新为 [{excel_cidr}]")
        else:
            # 云端没有，直接新增
            log.info(f"发现新规则 [{excel_desc}]，正在添加...")
            try:
                ec2.authorize_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=[
                        {
                            "IpProtocol": excel_protocol,
                            "FromPort": excel_from_port,
                            "ToPort": excel_to_port,
                            "IpRanges": [
                                {"CidrIp": excel_cidr, "Description": excel_desc}
                            ],
                        }
                    ],
                )
                log.info(f"成功添加 IP: {excel_cidr}")
            except Exception as e:
                log.error(f"添加失败Description: {excel_desc}, IP: {excel_cidr}, {e}")
                continue
    log.info(f"{sg_id}安全组同步流程执行完毕！")


if __name__ == "__main__":
    args= sys.argv
    if len(sys.argv) >1:
        aws_secret_name=sys.argv[1]
    else:
        aws_secret_name = "vego-garden/devops/secuirty_group/skucast/production"
    sync_security_group_with_status(aws_secret_name)

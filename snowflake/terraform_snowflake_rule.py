import os
import shutil
import subprocess
# from dotenv import load_dotenv
import gspread
from gspread.exceptions import WorksheetNotFound, APIError
from common.Unit_Log import Logger
import boto3
import base64
from botocore.exceptions import ClientError
import json
import pandas as pd
import re
import ipaddress


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
            print.error("Secret not found")
        elif e.response["Error"]["Code"] == "InvalidRequestException":
            print.error("Invalid request parameters")
        elif e.response["Error"]["Code"] == "InvalidParameterException":
            print.error("Invalid parameters")
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


def fix_pem_whitespace(raw_env_pem: str) -> str:
    """
    修复从环境变量/Secrets Manager 拿到的单行 PEM, 转为标准多行 PEM
    """
    # pattern = r"(-----BEGIN PRIVATE KEY-----)(.*)(-----END PRIVATE KEY-----)"
    pattern = r"(-----BEGIN [A-Z ]+-----)(.*)(-----END [A-Z ]+-----)"
    match = re.match(pattern, raw_env_pem.strip(), re.DOTALL)
    if not match:
        raise ValueError("PEM format invalid, cannot match BEGIN/END marker")

    header = match.group(1)
    body_raw = match.group(2).strip()
    footer = match.group(3)

    # 把 body 里面的空格替换为真实换行
    body_lines = body_raw.replace(" ", "\n")
    # 组装标准 PEM
    pem = f"{header}\n{body_lines}\n{footer}"
    return pem


def normalize_ip_cidr(ip_str: str) -> str:
    stripped = ip_str.strip()
    try:
        if "/" in stripped:
            net = ipaddress.ip_network(stripped, strict=False)
        else:
            ip = ipaddress.ip_address(stripped)
            prefix = "/128" if ip.version == 6 else "/32"
            net = ipaddress.ip_network(f"{ip}{prefix}", strict=False)
        return str(net)
    except ValueError as e:
        raise ValueError(f"Invalid IP/CIDR: {ip_str}, {e}") from e


class RuleTerraformGenerator:
    def __init__(self, aws_secret_name: str):
        self.log = Logger()
        self.tf_workdir = "./tf_snowflake_rules"
        aws_secret_json = get_secret(aws_secret_name, region_name="us-east-1")
        self.gsheet_spreadsheet_id = aws_secret_json.get("GSHEET_SPREADSHEET_ID")
        self.gsheet_service_account_json_raw = aws_secret_json.get(
            "GSHEET_SERVICE_ACCOUNT_JSON"
        )
        self.gsheet_tab = aws_secret_json.get("GSHEET_SHEET_NAME", "network_rules")
        self.snowflake_account_locator = aws_secret_json.get(
            "SNOWFLAKE_ACCOUNT_LOCATOR"
        )
        self.snowflake_user = aws_secret_json.get("SNOWFLAKE_USER")
        self.snowflake_role = aws_secret_json.get("SNOWFLAKE_ROLE")

        raw_key = aws_secret_json.get("SNOWFLAKE_PRIVATE_KEY_PEM")
        self.snowflake_private_key_pem = fix_pem_whitespace(raw_key)
        self.snowflake_private_key_passphrase = aws_secret_json.get(
            "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"
        )

    def read_google_sheet(self) -> list[dict]:
        """
        在线读取 Google Sheet
        相同 (database, schema, rule_name) 的行会合并 value_list, IP 自动去重
        """
        sa_info = json.loads(self.gsheet_service_account_json_raw)
        gc = gspread.service_account_from_dict(sa_info)
        try:
            sh = gc.open_by_key(self.gsheet_spreadsheet_id)
        except APIError as e:
            raise Exception(
                f"Open spreadsheet failed, check spreadsheet_id & SA share permission: {e}"
            )

        try:
            ws = sh.worksheet(self.gsheet_tab)
        except WorksheetNotFound:
            raise Exception(f"Worksheet {self.gsheet_tab} not found in google sheet")

        all_values = ws.get_all_values()
        # self.log.info(
        #     f"Sheet debug info: worksheet name='{ws.title}', total raw rows={len(all_values)}"
        # )
        if len(all_values) == 0:
            raise Exception("Google sheet is completely empty")

        header_row = all_values[0]
        clean_header = [h.strip() for h in header_row]
        # self.log.info(f"Sheet header stripped: {clean_header}")

        records = ws.get_all_records()
        # self.log.info(f"Read records count: {len(records)}")

        if len(records) == 0:
            raise Exception(
                "Got zero rows from Google Sheet. Check: 1) sheet has data below header; 2) header names match."
            )

        rule_map = {}

        for idx, rec in enumerate(records):
            rec_clean = {k.strip(): v for k, v in rec.items()}

            rule_name = rec_clean.get("rule_name", "").strip()
            db = rec_clean.get("database", "UTIL").strip()
            schema = rec_clean.get("schema", "PUBLIC").strip()
            if not rule_name or not db or not schema:
                self.log.warning(
                    f"Skip row {idx+2}: missing rule_name/database/schema, raw={rec_clean}"
                )
                continue

            key = (db, schema, rule_name)
            raw_values = rec_clean.get("value_list", "") or ""
            # ip_list = [v.strip() for v in raw_values.split(",") if v.strip()]
            ip_list = []
            for v in raw_values.split(","):
                raw = v.strip()
                if not raw:
                    continue
                try:
                    cidr = normalize_ip_cidr(raw)
                    ip_list.append(cidr)
                except ValueError as err:
                    self.log.error(f"Skip invalid entry [{raw}]: {err}")
            if not ip_list:
                continue
            if key not in rule_map:
                rule_map[key] = {
                    "rule_name": rule_name,
                    "database": db,
                    "schema": schema,
                    "value_set": set(ip_list),
                    "comment": rec_clean.get(
                        "comment",
                        "Managed by Python Terraform wrapper from Google Sheet",
                    ),
                    "policy_name": rec_clean.get(
                        "policy_name", "account_access_policy"
                    ),
                    "attach_to_policy": str(
                        rec_clean.get("attach_to_policy", "false")
                    ).lower()
                    == "true",
                }
            else:
                rule_map[key]["value_set"].update(ip_list)
                self.log.info(f"Merge into existing rule {key}, added {ip_list}")

        result = []
        for item in rule_map.values():
            result.append(
                {
                    "rule_name": item["rule_name"],
                    "database": item["database"],
                    "schema": item["schema"],
                    "value_list": sorted(list(item["value_set"])),
                    "comment": item["comment"],
                    "policy_name": item["policy_name"],
                    "attach_to_policy": item["attach_to_policy"],
                }
            )
        self.log.info(f"After merge, total network rules: {len(result)}")
        return result

    def render_tf(self, rule_list: list[dict]) -> str:
        rule_blocks = []
        policy_allowed_rules = {}

        for r in rule_list:
            tf_name = r["rule_name"].replace("-", "_").lower()
            values = "\n".join([f'    "{v}",' for v in r["value_list"]])
            rule_blocks.append(f"""
resource "snowflake_network_rule" "{tf_name}" {{
  name       = "{r["rule_name"]}"
  database   = "{r["database"]}"
  schema     = "{r["schema"]}"
  type       = "IPV4"
  mode       = "INGRESS"
  value_list = [
{values}
  ]
  comment    = "{r["comment"]}"
}}

output "{tf_name}_fq_name" {{
  value = snowflake_network_rule.{tf_name}.fully_qualified_name
}}
""")
            if r["attach_to_policy"]:
                p_name = r["policy_name"]
                fq = f"${{snowflake_network_rule.{tf_name}.fully_qualified_name}}"
                if p_name not in policy_allowed_rules:
                    policy_allowed_rules[p_name] = []
                policy_allowed_rules[p_name].append(fq)

        policy_blocks = []
        for policy_name, rule_fq_list in policy_allowed_rules.items():
            rule_str = "\n".join([f"    {fq}," for fq in rule_fq_list])
            policy_blocks.append(f"""
resource "snowflake_network_policy" "{policy_name.lower()}" {{
  name = "{policy_name}"
  allowed_network_rule_list = [
{rule_str}
  ]
  comment = "Network policy referencing network rules, managed by Google Sheet"
}}
""")

        tf = f"""terraform {{
  required_providers {{
    snowflake = {{
      source  = "snowflakedb/snowflake"
      version = "~> 2.18"
    }}
  }}
}}

provider "snowflake" {{
  account                       = var.snowflake_account_locator
  user                          = var.snowflake_user
  role                          = var.snowflake_role
  authenticator                 = "SNOWFLAKE_JWT"            # 1. 显式声明使用 Key Pair (JWT) 认证
  private_key                   = file(var.snowflake_private_key_path) # 2. 读取私钥文本
  private_key_passphrase        = var.snowflake_private_key_passphrase
  experimental_features_enabled = ["PROVIDER_CONFIGURATION_ACCOUNT_FALLBACK"]
}}

variable "snowflake_account_locator" {{ type = string }}
variable "snowflake_user" {{ type = string }}
variable "snowflake_role" {{ type = string }}
variable "snowflake_private_key_path" {{type = string}}
variable "snowflake_private_key_passphrase" {{
  type      = string
  sensitive = true
}}

{"".join(rule_blocks)}
{"".join(policy_blocks)}
"""
        return tf

    def render_tfvars(self, key_file_name: str) -> str:
        tfvars = f"""
snowflake_account_locator  = "{self.snowflake_account_locator}"
snowflake_user             = "{self.snowflake_user}"
snowflake_role             = "{self.snowflake_role}"
snowflake_private_key_path = "{key_file_name}"
snowflake_private_key_passphrase= "{self.snowflake_private_key_passphrase}"
"""
        return tfvars

    def prepare_tf_dir(self, rules: list[dict]):
        # if os.path.exists(self.tf_workdir):
        #     shutil.rmtree(self.tf_workdir)
        os.makedirs(self.tf_workdir, exist_ok=True)

        # 1. 将 PEM 私钥写入独立的文件中
        pem_file_name = "rsa_key.pem"
        pem_file_path = os.path.join(self.tf_workdir, pem_file_name)
        with open(pem_file_path, "w", encoding="utf-8") as f:
            f.write(self.snowflake_private_key_pem)

        # 设置严格权限 (0600: 仅当前用户读写)
        os.chmod(pem_file_path, 0o600)

        # 2. 渲染 main.tf 和 terraform.tfvars
        main_tf = self.render_tf(rules)
        tfvars = self.render_tfvars(pem_file_name)

        with open(os.path.join(self.tf_workdir, "main.tf"), "w", encoding="utf-8") as f:
            f.write(main_tf)
        with open(
            os.path.join(self.tf_workdir, "terraform.tfvars"), "w", encoding="utf-8"
        ) as f:
            f.write(tfvars)

        self.log.info(f"Terraform files and RSA key generated at {self.tf_workdir}")

    def run_tf_cmd(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.log.info(f"===== RUN: {' '.join(cmd)} =====")
        res = subprocess.run(
            cmd,
            cwd=self.tf_workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.log.info(f"STDOUT: {res.stdout}")
        if res.stderr:
            print(f"STDERR: {res.stderr}")
        return res

    def terraform_import(
        self, rules: list[dict], import_existing_resource: bool = True
    ):
        if not import_existing_resource:
            self.log.info("import_existing_resource=false, skip import step")
            return
        self.log.info("===== IMPORT EXISTING NETWORK RULES =====")

        # Step1: 一次性读取terraform state里已经存在的资源
        state_cmd = ["terraform", "state", "list"]
        ret_state = self.run_tf_cmd(state_cmd)
        state_resources = set()
        if ret_state.returncode == 0:
            # 按行解析资源地址，存入集合方便快速查找
            state_resources = {
                line.strip() for line in ret_state.stdout.splitlines() if line.strip()
            }
            self.log.info(
                f"Loaded {len(state_resources)} resources from terraform state"
            )
        else:
            self.log.warning(
                "terraform state list failed, state empty or no state file, will try import all"
            )

        for r in rules:
            tf_name = r["rule_name"].replace("-", "_").lower()
            tf_addr = f"snowflake_network_rule.{tf_name}"
            import_id = f"{r['database']}.{r['schema']}.{r['rule_name']}"

            # 判断：本地state已经存在该资源 → skip import
            if tf_addr in state_resources:
                self.log.info(
                    f"{tf_addr} already exists in terraform state, skip import"
                )
                continue

            self.log.info(f"===== RUN: terraform import {tf_addr} {import_id} =====")
            cmd = ["terraform", "import", tf_addr, import_id]
            ret = self.run_tf_cmd(cmd)
            if ret.returncode != 0:
                self.log.info(
                    f"Import {import_id} failed. Rule may not exist in Snowflake."
                )
            else:
                # import成功，追加到本地内存state集合，防止同批次重复导入
                state_resources.add(tf_addr)

    def terraform_plan(self):
        rules = self.read_google_sheet()
        self.log.info(f"Total merged network rules count: {len(rules)}")
        self.prepare_tf_dir(rules)
        self.run_tf_cmd(["terraform", "init"])
        self.terraform_import(rules)
        self.run_tf_cmd(["terraform", "plan"])

    def terraform_apply(self):
        rules = self.read_google_sheet()
        self.log.info(f"Total merged network rules count: {len(rules)}")
        self.prepare_tf_dir(rules)
        self.run_tf_cmd(["terraform", "init"])
        self.terraform_import(rules)
        self.run_tf_cmd(["terraform", "apply", "-auto-approve"])

    def terraform_destroy(self):
        # rules = self.read_google_sheet()
        # self.log.info(f"Total merged network rules count: {len(rules)}")
        # self.prepare_tf_dir(rules)
        # self.run_tf_cmd(["terraform", "init"])
        # self.terraform_import(rules)
        self.run_tf_cmd(["terraform", "destroy", "-auto-approve"])


if __name__ == "__main__":
    aws_secret_name = "devops/snowflake/network_policy"
    gen = RuleTerraformGenerator(aws_secret_name=aws_secret_name)

    # rules = gen.read_google_sheet()
    # gen.prepare_tf_dir(rules)
    # gen.terraform_plan()
    gen.terraform_apply()

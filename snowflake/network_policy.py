from common.Unit_Log import Logger
import snowflake.connector
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import boto3
import json
import base64
from botocore.exceptions import ClientError
import sys
from snowflake.connector import DictCursor

# ===================== 日志配置（关键） =====================


def get_secret(secret_name, region_name="us-east-1"):
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)
    try:
        resp = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        print(f"Secrets Manager Error: {e.response['Error']['Code']}")
        raise e

    if "SecretString" in resp:
        return json.loads(resp["SecretString"])
    decoded_bin = base64.b64decode(resp["SecretBinary"])
    return json.loads(decoded_bin)


class SnowFlakeGenerator:
    def __init__(self, secret_name, region_name="us-east-1"):
        self.log = Logger()
        secret_info = get_secret(secret_name, region_name)
        self.snowflake_account = secret_info.get(
            "snowflake_account", "ofb71810.us-east-1"
        )
        self.snowflake_user = secret_info.get("snowflake_user")
        self.private_key_pem = secret_info.get("private_key")
        self.private_key_pem2 = secret_info.get("private_key2")
        self.private_key_passphrase = secret_info.get("private_key_passphrase", None)
        self.private_key_passphrase2 = secret_info.get("private_key_passphrase2", None)
        self.private_key_path = secret_info.get("private_key_path", None)
        self.private_key_path_passphrase = secret_info.get(
            "private_key_path_passphrase", None
        )
        self.role = secret_info.get(
            "role", "VEGO_NETWORK_POLICY_ADMIN"
        )  # 私钥密码，没有就填 None
        # ==========================================================
        self.warehouse = "COMPUTE_WH"

    def load_private_key(self, key_path=None, passphrase=None):
        if key_path is None:
            return
        """加载P8格式私钥"""
        self.log.info(f"开始加载私钥文件：{key_path}")
        try:
            with open(key_path, "rb") as f:
                key_data = f.read()

            private_key = serialization.load_pem_private_key(
                key_data,
                password=passphrase.encode() if passphrase else None,
                backend=default_backend(),
            )

            pk_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            self.log.info("私钥加载成功")
            return pk_bytes

        except Exception as e:
            self.log.error(f"私钥加载失败：{str(e)}")
            raise

    def load_private_key_from_pem(self, pem_data, passphrase=None):
        password_bytes = passphrase.encode() if passphrase is not None else None
        private_key = serialization.load_pem_private_key(
            pem_data.encode("utf-8"),
            password=password_bytes,
        )

        return private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    def snowflake_str_to_list(self, raw_str: str):
        """
        解析snowflake返回的 ('a','b') 字符串 转python list
        输入样例：'("10.0.0.0/24","223.5.5.5/32")'
        返回：["10.0.0.0/24", "223.5.5.5/32"]
        """
        if not raw_str or raw_str.strip() in ("", "()"):
            return []
        # 去掉前后括号
        content = raw_str.strip().strip("()")
        if not content:
            return []
        # 按逗号分割，去除引号+空格
        items = [item.strip().strip('"') for item in content.split(",")]
        return items

    # 主连接逻辑
    def run(self):
        #
        self.log.info(
            f"开始连接 Snowflake: 用户={self.snowflake_user}, 账户={self.snowflake_account}"
        )

        try:
            if self.private_key_path:
                private_key = self.load_private_key(
                    self.private_key_path, self.private_key_path_passphrase
                )
            else:
                private_key = self.load_private_key_from_pem(
                    self.private_key_pem, self.private_key_passphrase
                )
            ctx = snowflake.connector.connect(
                account=self.snowflake_account,
                user=self.snowflake_user,
                private_key=private_key,
                warehouse=self.warehouse,
                role=self.role,
                login_timeout=10,
                network_timeout=10,
            )

            # self.log.info("✅ Snowflake 连接成功！")
            # self.log.info("✅ 网络策略已生效（当前IP被允许访问）")

            # 测试查询
            cur = ctx.cursor(DictCursor)
            cur.execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_TIMESTAMP(), CURRENT_VERSION(), CURRENT_IP_ADDRESS()"
            )

            # row = cur.fetchone()
            row = cur.fetchall()
            # self.log.info(f"row: {row}")
            self.log.info(
                f"查询结果：用户={row[0].get('CURRENT_USER()')}, 角色={row[0].get('CURRENT_ROLE()')}, 时间={row[0].get('CURRENT_TIMESTAMP()')}, 版本={row[0].get('CURRENT_VERSION()')}, IP={row[0].get('CURRENT_IP_ADDRESS()')}"
            )

            self.log.info("===== ALL NETWORK POLICY OBJECTS =====")
            cur.execute("SHOW NETWORK POLICIES;")
            all_policies = cur.fetchall()
            # self.log.info(f"all_policies: {all_policies}")
            for pol in all_policies:
                pol_name = pol["name"]
                entries_in_allowed_network_rules = pol[
                    "entries_in_allowed_network_rules"
                ]
                comment = pol["comment"]
                self.log.info(
                    f"Policy Name: {pol_name}, Entries in allowed network rules: {entries_in_allowed_network_rules}, Comment: {comment}"
                )

                # 获取该policy的IP规则：ALLOWED_IP_LIST / BLOCKED_IP_LIST
                cur.execute(f"DESCRIBE NETWORK POLICY {pol_name};")
                rules = cur.fetchall()
                for r in rules:
                    # self.log.info(f"rule: {r}")
                    prop_name = r["name"]
                    self.log.info(f"val: {r['value']}")
                    val = json.loads(r["value"])
                    self.log.info(f"  {prop_name}: {val}")
                    if prop_name == "ALLOWED_NETWORK_RULE_LIST":
                        try:
                            for rulename in val:
                                self.log.info(f"rulename: {rulename}")
                                fullyQualifiedRuleName=rulename.get("fullyQualifiedRuleName")
                                self.log.info(f"fullyQualifiedRuleName:{fullyQualifiedRuleName}")
                                db, schema, rule_name = fullyQualifiedRuleName.split(".")
                                sql = f'DESCRIBE NETWORK RULE {db}.{schema}."{rule_name}";'
                                cur.execute(sql)
                                rule_rows = cur.fetchall()
                                self.log.info(f"rule_rows: {rule_rows}")
                                # for rr in rule_rows:
                                #     p_name, p_val = rr[0], rr[1]
                                #     self.log.info(f"{p_name} : {p_val}")
                        except Exception as e:
                            self.log.error(f"查询Network Rule失败: {e}")
                # cur.execute("USE WAREHOUSE COMPUTE_WH;")
                cur.execute(
                    f"SELECT POLICY_NAME, REF_ENTITY_NAME  AS BOUND_TO,  REF_ENTITY_DOMAIN AS LEVEL, POLICY_STATUS FROM SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES WHERE POLICY_NAME = '{pol_name}'  AND POLICY_KIND = 'NETWORK_POLICY';"
                )
                policy_references = cur.fetchall()
                # self.log.info(f"reference: {policy_references}")
                for reference in policy_references:
                    pol_name = reference.get("POLICY_NAME")
                    bound_to = reference.get("BOUND_TO")
                    status = reference.get("POLICY_STATUS")
                    self.log.info(f"策略名: {pol_name}, 绑定用户：{bound_to}, 策略状态: {status}")

            # self.log.info("===== USERS WITH USER-LEVEL NETWORK POLICY (用户绑定的policy, 优先级更高) =====")
            # cur.execute("SHOW USERS;")
            # users = cur.fetchall()
            # # self.log.info(f"users: {users}")
            # for u in users:
            #     pol_name = u.get("NETWORK_POLICY")
            #     if pol_name and pol_name != "":
            #         self.log.info(f"USER: {u['name']}  -> NETWORK_POLICY: {pol_name}")

            cur.close()
            ctx.close()
            self.log.info("✅ 连接正常关闭")

        except snowflake.connector.errors.DatabaseError as e:
            self.log.error(f"❌ Snowflake 数据库异常：{e}")
            if "is not allowed to access Snowflake" in str(e):
                self.log.error(
                    "➡️ 原因: 当前客户端IP不在网络策略白名单内 → 网络策略【已生效】并拦截了访问"
                )
            elif "Failed to connect" in str(e) or "timed out" in str(e):
                self.log.error("➡️ 原因：网络不通/端口443不通/域名无法解析")
            elif "RSA key" in str(e) or "signature" in str(e):
                self.log.error("➡️ 原因：密钥对不匹配/公钥未上传/私钥错误")

        except Exception as e:
            self.log.error(f"❌ 连接失败：{str(e)}")


if __name__ == "__main__":
    # test_snowflake_connection()
    AWS_SECRET = "devops/snowflake/test_network_policy"
    gen = SnowFlakeGenerator(AWS_SECRET)
    gen.run()

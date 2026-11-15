"""在服务器本机验证缓存，不打印密码或登录令牌。"""
import argparse
import json
from getpass import getpass
from urllib.request import Request, urlopen
from urllib.error import HTTPError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--week", type=int, default=1)
args = parser.parse_args()
username = input("网站用户名：")
password = getpass("网站登录密码（不是MySQL密码）：")
base = "http://127.0.0.1:8000"
payload = json.dumps({"username":username,"password":password}).encode()
try:
    with urlopen(Request(base+"/api/auth/login", data=payload,
                         headers={"Content-Type":"application/json"}), timeout=15) as response:
        token = json.load(response)["access_token"]
    headers = {"Authorization":"Bearer "+token}
    with urlopen(Request(base+"/api/schedules",headers=headers),timeout=10) as response:
        schedules = json.load(response)
    if not schedules:
        raise SystemExit("没有可验证的课表")
    schedule = schedules[0]
    print(f"课表：{schedule['label']}；第{args.week}周")
    for attempt in range(1,3):
        with urlopen(Request(base+f"/api/courses?schedule_id={schedule['id']}&week={args.week}",headers=headers),timeout=10) as response:
            data = json.load(response)
            print(f"第{attempt}次查询：X-Cache={response.headers.get('X-Cache','未启用新版')}，返回{len(data)}条安排")
finally:
    # 及时撤销这次诊断产生的会话。
    if "token" in globals():
        try:
            urlopen(Request(base+"/api/auth/logout",data=b"",headers=headers,method="POST"),timeout=5).close()
        except Exception:
            pass

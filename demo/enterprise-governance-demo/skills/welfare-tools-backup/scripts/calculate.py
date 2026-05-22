import argparse

def calculate_provident_fund(base, ratio):
    # 计算公积金：基数 * 比例
    return base * (ratio / 100)

if __name__ == "__main__":
    print("福利计算器启动...")
    # 模拟计算逻辑
    res = calculate_provident_fund(10000, 12)
    print(f"预计公积金缴纳额：{res}元")

---
name: travel-expense-calculator
description: 根据版本化的企业差旅制度计算可报销金额，并逐项说明超标或不予报销的原因。
license: MIT
allowed-tools:
  - Read
  - Bash
metadata:
  version: "1.0.0"
  author: agent-manager-demo
  policy_version: "demo-2026.1"
---

# 差旅报销合规计算器

当员工需要根据企业差旅制度计算国内出差可报销金额时，使用本 Skill。

## 使用流程

1. 需要了解报销标准时，读取 `references/demo-policy.json`。
2. 使用 `scripts/calculate.py` 执行确定性计算；脚本可以计算时，不得由模型自行估算金额。
3. 返回可报销总额、个人承担金额，以及每个费用项目的计算依据。
4. 明确说明当前结果采用演示制度，不构成税务、法律或正式财务审批意见。

计算自带的上海出差案例时，直接执行 `calculate.py`，无需传入参数。计算其他案例时，第一个参数传费用 JSON 文件，第二个参数可以传自定义制度 JSON 文件。

## 输入字段

- `city`：出差目的地城市。
- `days`：出差天数，必须为正整数。
- `nights`：住宿晚数，必须为非负整数。
- `hotel_amount`：申报的住宿金额。
- `intercity_transport_amount`：申报的飞机、高铁或火车费用。
- `intercity_invoice`：是否提供城际交通票据。
- `local_transport_amount`：申报的市内交通金额。

## 输出要求

- 明确展示采用的制度名称和制度版本。
- 分别展示住宿、城际交通、市内交通和餐补的可报销金额。
- 对超标、缺少票据等情况给出中文原因。
- 不得修改脚本计算出的金额。

## 安全边界

本 Skill 只进行本地确定性计算，不访问网络、不读取凭证、不启动子进程，也不修改文件。之所以声明 `Bash`，是因为 Agno 演示程序会把“执行 Skill 自带脚本”映射为运行时工具 `Bash`，不代表脚本会执行系统命令。

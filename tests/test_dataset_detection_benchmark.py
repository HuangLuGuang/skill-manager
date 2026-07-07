#!/usr/bin/env python3
"""
检测能力回归测试脚本 - CLI 驱动全自动测试
使用方式与用户日常手动使用保持一致

========== 配置区域 ==========
修改下面的配置项即可使用
==============================
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ===========================================
# 配置区域 - 在此修改配置
# ===========================================

# 访问令牌在前端“智能体管理 → 凭证管理”创建，需包含 scanner:submit 权限。
# 通过命令行 --token 或环境变量 SKILL_SCANNER_TOKEN 传入，不要写入源码。
TOKEN = ""

# 数据集路径配置
DATASET_BENIGN = "test_data/demo_data/upload_zip/benign"
DATASET_SUSPICIOUS = "test_data/demo_data/upload_zip/suspicious"
DATASET_MALICIOUS = "test_data/demo_data/upload_zip/malicious"

# CLI 和服务配置
CLI_PATH = "~/Downloads/skill-scanner-cli-darwin-amd64"
BASE_URL = "http://localhost:5173"
DB_PATH = "sqlite/admin_starter.db"
DATA_ROOT = "."
SCAN_CACHE_DIR = "~/.agent-manager/scan_cache"

# 最大等待时间（小时）- 后端处理完所有技能的超时时间
MAX_WAIT_HOURS = 48

# 检查间隔（分钟）
CHECK_INTERVAL_MINUTES = 1

# ===========================================
# 配置结束 - 下面的代码一般不需要修改
# ===========================================

# 数据集字典
DATASET_DIRS = {
    "benign": DATASET_BENIGN,
    "suspicious": DATASET_SUSPICIOUS,
    "malicious": DATASET_MALICIOUS,
}

# ===========================================
# 工具函数
# ===========================================

def health_check(base_url: str) -> bool:
    """检查后端健康状态"""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{base_url}/health", timeout=10) as response:
            return response.status == 200
    except Exception as e:
        print(f"健康检查失败: {e}")
        return False

def confirm_purge(db_path: Path, scan_cache_dir: Path, purge_mode: str, yes: bool = False):
    """确认并执行数据清理操作"""
    if purge_mode == "none":
        print("跳过数据清理")
        return

    # 先建议备份数据库
    backup_name = db_path.with_suffix(f".bak.{datetime.now():%Y%m%d-%H%M%S}")
    print(f"⚠️  强烈建议先备份数据库:")
    print(f"   cp {db_path} {backup_name}\n")

    msg = f"即将执行的清理操作:\n"

    if purge_mode == "all":
        msg += "  1. 删除 skill_registry 整张表的数据\n"
        msg += "  2. 删除 skill_review_queue 整张表的数据\n"
    else:
        msg += "  1. 仅删除 benchmark 相关的 skill 记录（本脚本暂不实现此功能，建议使用 --purge=all）\n"

    msg += f"  3. 删除扫描缓存目录: {scan_cache_dir}\n"

    print(msg)

    if not yes:
        answer = input("确认继续？(yes/N): ").strip().lower()
        if answer != "yes":
            print("用户取消操作")
            sys.exit(1)

    # 执行清理
    print(f"📂 数据库完整路径: {db_path.resolve()}")

    with sqlite3.connect(db_path, timeout=30) as conn:
        if purge_mode == "all":
            print("正在清理数据库...")

            # 查询数据库中的表
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            print(f"   数据库中的表: {[t[0] for t in tables]}")

            # 查询删除前的数量
            if any(t[0] == "skill_registry" for t in tables):
                before_count = conn.execute("SELECT COUNT(*) FROM skill_registry").fetchone()[0]
                print(f"   删除前 skill_registry 有 {before_count} 条记录")
            else:
                print(f"   警告: 数据库中没有 skill_registry 表！")
                before_count = 0

            # 执行删除
            conn.execute("DELETE FROM skill_registry")
            conn.execute("DELETE FROM skill_review_queue")
            conn.commit()

            # 查询删除后的数量
            if any(t[0] == "skill_registry" for t in tables):
                after_count = conn.execute("SELECT COUNT(*) FROM skill_registry").fetchone()[0]
                print(f"✅ 数据库清理完成，删除后 skill_registry 有 {after_count} 条记录")

    # 检查是否有其他可能的数据库位置
    home = Path.home()
    agent_manager_dir = home / ".agent-manager"
    if agent_manager_dir.exists():
        print(f"\n💡 检查 {agent_manager_dir} 目录...")
        for db_file in agent_manager_dir.glob("*.db"):
            print(f"   发现数据库: {db_file}")

    # 清理扫描缓存 - 只删除内容，保留目录
    if scan_cache_dir.exists():
        print(f"正在清理扫描缓存: {scan_cache_dir}...")
        # 删除目录下的所有内容，但保留目录本身
        for item in scan_cache_dir.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                print(f"   警告: 无法删除 {item}: {e}")
        print("✅ 扫描缓存清理完成")
    else:
        # 确保目录存在
        scan_cache_dir.mkdir(parents=True, exist_ok=True)
        print(f"✅ 创建扫描缓存目录: {scan_cache_dir}")

def check_cli_available(cli_path: Path) -> bool:
    """检查 CLI 是否可用"""
    try:
        result = subprocess.run(
            [str(cli_path), "scan", "--help"],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False

def run_one_cli(label: str, scan_root: Path, token: str, args: argparse.Namespace, log_dir: Path):
    """运行单个 CLI 进程"""
    report_path = log_dir / f"report_{label}.json"
    stdout_path = log_dir / f"cli_{label}.stdout.log"

    cmd = [
        str(args.cli_path), "scan", str(scan_root),
        "--server", args.base_url,
        "--token", token,
        "--output", str(report_path),
        "--host-id", f"benchmark-{label}",
        "--behavioral",
        "--deep-scan",
        "--sandbox",
        "--llm",
        "--no-cache",
    ]

    # 分开处理以避免 f-string 问题
    cmd_preview = ' '.join(cmd[:8])
    print(f"🚀 启动 {label} 数据集扫描: {cmd_preview}")

    with open(stdout_path, "w") as f:
        result = subprocess.run(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            check=False
        )

    return label, result.returncode, report_path, stdout_path

def run_all_clis(token: str, args: argparse.Namespace, log_dir: Path, dataset_dirs: dict):
    """并行运行所有 CLI 进程"""
    futures = []

    # 检查重复的数据集路径
    seen_paths = {}
    for label in args.labels:
        data_dir = Path(args.data_root) / Path(dataset_dirs[label])
        data_dir_str = str(data_dir.resolve())
        if data_dir_str in seen_paths:
            print(f"⚠️  警告: 数据集 '{label}' 和 '{seen_paths[data_dir_str]}' 使用相同的路径: {data_dir}")
            print("   这会导致重复提交相同的 skill！")
        seen_paths[data_dir_str] = label

    with ThreadPoolExecutor(max_workers=3) as executor:
        for label in args.labels:
            data_dir = Path(args.data_root) / Path(dataset_dirs[label])
            future = executor.submit(
                run_one_cli,
                label,
                data_dir,
                token,
                args,
                log_dir
            )
            futures.append(future)

        results = []
        for future in as_completed(futures):
            results.append(future.result())

    return results

def parse_reports(report_files, dataset_dirs: dict):
    """解析所有报告文件，构建 skill_id 到标签的映射"""
    skill_id_map = {}
    summary = {}
    all_skill_ids = []
    seen_skill_ids = set()
    duplicate_skill_ids = set()

    for label, returncode, report_path, stdout_path in report_files:
        if not report_path.exists():
            print(f"❌ {label} 数据集报告未生成 (返回码: {returncode})")
            print(f"   查看日志: {stdout_path}")
            summary[label] = {"found": 0, "submitted": 0, "failed": 0, "error": "report not found"}
            continue

        try:
            data = json.loads(report_path.read_text())
        except json.JSONDecodeError as e:
            print(f"❌ {label} 数据集报告解析失败: {e}")
            summary[label] = {"found": 0, "submitted": 0, "failed": 0, "error": f"parse failed: {e}"}
            continue

        # 构建 skill_id 映射 - 因为是我们提交的 label，直接关联即可
        label_skill_count = 0
        for skill in data.get("skills", []):
            if skill.get("submitted") and skill.get("submission", {}).get("skill_id"):
                skill_id = skill["submission"]["skill_id"]

                # 检测重复
                if skill_id in seen_skill_ids:
                    duplicate_skill_ids.add(skill_id)
                    # 如果已经存在，保留第一次的标签，跳过后续的
                    continue

                seen_skill_ids.add(skill_id)
                skill_id_map[skill_id] = label
                all_skill_ids.append(skill_id)
                label_skill_count += 1

        summary[label] = {
            "found": data.get("found", 0),
            "submitted": data.get("submitted", 0),
            "failed": data.get("failed", 0),
            "submit_errors": [
                s.get("submit_error") for s in data.get("skills", [])
                if s.get("submit_error")
            ][:5],
        }

        print(f"✅ {label} 数据集: 发现 {summary[label]['found']} 个, 提交 {summary[label]['submitted']} 个, 统计 {label_skill_count} 个（去重后）")

    if duplicate_skill_ids:
        print(f"\n⚠️  警告: 检测到 {len(duplicate_skill_ids)} 个重复提交的 skill_id")
        print(f"   原因: 多个数据集使用了相同的路径，导致同一个 skill 被多次提交")
        print(f"   已自动去重，只保留第一次的标签")

    return skill_id_map, summary, all_skill_ids

def wait_until_quiet(db_path: Path, skill_id_map: dict[str, str], max_hours: int = 48, check_interval_minutes: int = 1):
    """等待直到所有数据集的 skill 都不是 PENDING 状态"""
    if not skill_id_map:
        print("⚠️  没有 skill_id 需要等待")
        return

    skill_ids = list(skill_id_map.keys())
    placeholders = ",".join("?" * len(skill_ids))
    deadline = time.time() + max_hours * 3600

    print(f"\n⏳ 开始等待扫描完成，最多等待 {max_hours} 小时...")
    print(f"   每 {check_interval_minutes} 分钟检查一次状态...")
    print(f"   监控 skill_id 数量: {len(skill_ids)}")

    while time.time() < deadline:
        with sqlite3.connect(db_path, timeout=30) as conn:
            # 按数据集分组检查 PENDING 数量
            rows = conn.execute(f"""
                SELECT skill_id, status
                FROM skill_registry
                WHERE skill_id IN ({placeholders})
            """, skill_ids).fetchall()

        # 统计每个数据集的 pending 数量
        pending_by_label = {"benign": 0, "suspicious": 0, "malicious": 0}
        found_by_label = {"benign": 0, "suspicious": 0, "malicious": 0}

        for skill_id, status in rows:
            label = skill_id_map.get(skill_id)
            if label:
                found_by_label[label] += 1
                if status == "PENDING":
                    pending_by_label[label] += 1

        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 打印各数据集状态
        status_parts = []
        all_zero = True
        for label in ["benign", "suspicious", "malicious"]:
            if label in found_by_label and found_by_label[label] > 0:
                pending = pending_by_label[label]
                total = found_by_label[label]
                status_parts.append(f"{label}: {pending}/{total}")
                if pending > 0:
                    all_zero = False

        print(f"[{current_time_str}] PENDING - {' | '.join(status_parts)}")

        # 检查是否所有数据集的 PENDING 都为 0
        if all_zero:
            print(f"[{current_time_str}] 🎉 所有数据集的技能都已完成扫描！")
            return

        # 等待检查间隔
        time.sleep(check_interval_minutes * 60)

    print(f"⚠️  达到最大等待时间 {max_hours} 小时，停止等待")

def aggregate(db_path: Path, skill_id_map: dict[str, str]):
    """聚合统计结果"""
    buckets = ["benign", "suspicious", "malicious", "null"]
    labels = ["benign", "suspicious", "malicious"]
    stats = {gt: {b: 0 for b in buckets} for gt in labels}

    if not skill_id_map:
        return stats

    placeholders = ",".join("?" * len(skill_id_map))
    skill_ids = list(skill_id_map.keys())

    with sqlite3.connect(db_path, timeout=30) as conn:
        for skill_id, risk_level in conn.execute(f"""
            SELECT skill_id, risk_level
            FROM skill_registry
            WHERE skill_id IN ({placeholders})
        """, skill_ids):
            gt = skill_id_map.get(skill_id)
            if not gt:
                continue
            key = (risk_level or "null").lower()
            if key not in stats[gt]:
                key = "null"
            stats[gt][key] += 1

    return stats

def print_confusion_matrix(stats: dict[str, dict[str, int]], cli_summary: dict[str, Any]):
    """打印混淆矩阵"""
    buckets = ["benign", "suspicious", "malicious", "null"]
    labels = ["benign", "suspicious", "malicious"]

    print("\n" + "=" * 80)
    print("检测能力混淆矩阵")
    print("=" * 80)

    # 打印表头
    header = f"{'真实标签':<15} {'benign':>10} {'suspicious':>12} {'malicious':>12} {'null':>10} {'总数':>10}"
    print(header)
    print("-" * len(header))

    total_correct = 0
    total_total = 0
    per_class_acc = {}

    for gt in labels:
        row = [stats[gt][b] for b in buckets]
        total = sum(row)
        correct = stats[gt][gt] if gt in stats[gt] else 0
        if total > 0:
            acc = correct / total * 100
        else:
            acc = 0.0
        per_class_acc[gt] = acc
        total_correct += correct
        total_total += total

        # 格式化行数据
        row_str = [f"{gt:<15}"]
        for i, b in enumerate(buckets):
            val = row[i]
            if total > 0:
                pct = val / total * 100
                row_str.append(f"{val:>6} ({pct:>5.1f}%)")
            else:
                row_str.append(f"{val:>12}")
        row_str.append(f"{total:>10}")
        print("".join(row_str))

    print("-" * len(header))

    # 计算总体准确率
    if total_total > 0:
        overall_acc = total_correct / total_total * 100
    else:
        overall_acc = 0.0

    print(f"\n📊 各类别准确率:")
    for gt in labels:
        print(f"   {gt}: {per_class_acc.get(gt, 0):.1f}%")

    print(f"\n🎯 总体准确率: {overall_acc:.1f}%")

    # 计算误报率和漏报率
    benign_total = stats["benign"]["benign"] + stats["benign"]["suspicious"] + stats["benign"]["malicious"]
    if benign_total > 0:
        false_positive = (stats["benign"]["suspicious"] + stats["benign"]["malicious"]) / benign_total * 100
        print(f"⚠️  误报率 (benign → non-benign): {false_positive:.1f}%")

    malicious_total = stats["malicious"]["benign"] + stats["malicious"]["suspicious"] + stats["malicious"]["malicious"]
    if malicious_total > 0:
        false_negative = stats["malicious"]["benign"] / malicious_total * 100
        print(f"🚨 漏报率 (malicious → benign): {false_negative:.1f}%")

    print(f"\n📝 各数据集提交汇总:")
    for label in cli_summary:
        s = cli_summary[label]
        print(f"   {label}: 发现 {s.get('found', 0)} 个, 提交 {s.get('submitted', 0)} 个, 失败 {s.get('failed', 0)} 个")
        if s.get('submit_errors'):
            print(f"      前5个错误: {s['submit_errors']}")

    print("=" * 80 + "\n")

def write_output(output_path: Path, args: argparse.Namespace, stats: dict[str, dict[str, int]],
                 cli_summary: dict[str, Any], skill_id_map: dict[str, str], started_at: datetime, ended_at: datetime):
    """写入输出文件"""
    output = {
        "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "stats": stats,
        "cli_summary": cli_summary,
        "skill_id_map": skill_id_map,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": (ended_at - started_at).total_seconds(),
    }

    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"✅ 完整报告已写入: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="检测能力回归测试脚本 - CLI 驱动全自动测试")

    # 必需参数 - 优先命令行，其次文件配置，最后环境变量
    parser.add_argument(
        "--token",
        type=str,
        default=TOKEN or os.environ.get("SKILL_SCANNER_TOKEN") or os.environ.get("AGENT_MANAGER_ACCESS_TOKEN"),
        help="访问令牌 (amat_...)，也可通过 SKILL_SCANNER_TOKEN 环境变量设置",
    )

    # 主要配置 - 默认从上面的配置区域读取
    parser.add_argument("--cli-path", type=Path, default=CLI_PATH,
                        help=f"CLI 路径 (默认: {CLI_PATH})")
    parser.add_argument("--base-url", type=str, default=BASE_URL,
                        help=f"后端服务地址 (默认: {BASE_URL})")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help=f"数据库路径 (默认: {DB_PATH})")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT,
                        help=f"数据集根目录 (默认: {DATA_ROOT})")
    parser.add_argument("--scan-cache-dir", type=Path, default=SCAN_CACHE_DIR,
                        help=f"扫描缓存目录 (默认: {SCAN_CACHE_DIR})")

    # 数据集路径配置
    parser.add_argument("--dataset-benign", type=str, default=DATASET_BENIGN,
                        help=f"Benign 数据集路径 (默认: {DATASET_BENIGN})")
    parser.add_argument("--dataset-suspicious", type=str, default=DATASET_SUSPICIOUS,
                        help=f"Suspicious 数据集路径 (默认: {DATASET_SUSPICIOUS})")
    parser.add_argument("--dataset-malicious", type=str, default=DATASET_MALICIOUS,
                        help=f"Malicious 数据集路径 (默认: {DATASET_MALICIOUS})")

    # 数据集选择
    parser.add_argument("--labels", type=str, nargs="+", default=["benign", "suspicious", "malicious"],
                        choices=["benign", "suspicious", "malicious"],
                        help="要测试的数据集 (默认: 全部)")

    # 清理选项
    parser.add_argument("--purge", type=str, default="none", choices=["none", "benchmark", "all"],
                        help="清理模式 (默认: none，不清理数据)")
    parser.add_argument("--yes", action="store_true", help="跳过确认提示 (CI 使用)")

    # 等待参数
    parser.add_argument("--max-wait-hours", type=int, default=MAX_WAIT_HOURS,
                        help=f"最大等待时间 (小时) (默认: {MAX_WAIT_HOURS})")
    parser.add_argument("--check-interval-minutes", type=int, default=CHECK_INTERVAL_MINUTES,
                        help=f"检查间隔 (分钟) (默认: {CHECK_INTERVAL_MINUTES})")

    # 输出选项
    parser.add_argument("--output", type=Path, help="输出报告 JSON 路径")
    parser.add_argument("--log-dir", type=Path, help="日志目录 (默认: .benchmark_logs/<timestamp>)")

    args = parser.parse_args()

    # 检查令牌
    if not args.token:
        print("❌ 错误: 必须提供访问令牌！")
        print("   方式 1: 通过命令行参数 --token 传入")
        print("   方式 2: 设置环境变量 SKILL_SCANNER_TOKEN")
        print("\n在前端创建: 智能体管理 → 凭证管理 → 创建凭证，选择 scanner:submit 权限")
        sys.exit(1)

    # 构建数据集路径配置
    dataset_dirs = {
        "benign": args.dataset_benign,
        "suspicious": args.dataset_suspicious,
        "malicious": args.dataset_malicious,
    }

    # 路径处理
    args.cli_path = args.cli_path.expanduser()
    args.db = Path(args.db).resolve()
    args.scan_cache_dir = args.scan_cache_dir.expanduser().resolve()

    # 创建日志目录
    if not args.log_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.log_dir = Path(".benchmark_logs") / timestamp
    args.log_dir.mkdir(parents=True, exist_ok=True)

    # 打印启动信息
    started_at = datetime.now(timezone.utc)
    print("=" * 80)
    print("检测能力回归测试脚本")
    print("=" * 80)
    print(f"开始时间: {started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"日志目录: {args.log_dir}")
    print("\n数据集配置:")
    for label in args.labels:
        print(f"  {label:10s}: {Path(args.data_root) / dataset_dirs[label]}")
    print()

    # 1. 健康检查
    print("1. 检查后端服务状态...")
    if not health_check(args.base_url):
        print("❌ 后端服务不可用，请检查服务是否启动")
        sys.exit(1)
    print("✅ 后端服务正常")

    # 2. 检查 CLI
    print("\n2. 检查 CLI 可用性...")
    if not check_cli_available(args.cli_path):
        print(f"⚠️  CLI 可能不可用: {args.cli_path}")
        print(f"   请确保 CLI 已下载到正确位置，或者修改文件开头的 CLI_PATH 配置")
    else:
        print("✅ CLI 可用")

    # 3. 检查数据集目录
    print("\n3. 检查数据集目录...")
    missing = []
    for label in args.labels:
        data_dir = Path(args.data_root) / dataset_dirs[label]
        if not data_dir.exists():
            missing.append(f"{label}: {data_dir}")
    if missing:
        print(f"❌ 以下数据集目录不存在: {', '.join(missing)}")
        print("   请修改文件开头的 DATASET_* 配置项，或者通过命令行参数指定")
        sys.exit(1)
    print("✅ 数据集目录存在")

    # 4. 清理旧数据
    print("\n4. 清理旧数据...")
    confirm_purge(args.db, args.scan_cache_dir, args.purge, args.yes)

    # 5. 运行 CLI 扫描
    print("\n5. 启动 CLI 扫描...")
    cli_results = run_all_clis(args.token, args, args.log_dir, dataset_dirs)

    # 6. 解析报告
    print("\n6. 解析扫描报告...")
    skill_id_map, cli_summary, all_skill_ids = parse_reports(cli_results, dataset_dirs)

    if not skill_id_map:
        print("❌ 没有成功提交的 skill，退出")
        sys.exit(1)

    # 7. 等待扫描完成
    print("\n7. 等待后端扫描处理...")
    wait_until_quiet(args.db, skill_id_map, max_hours=args.max_wait_hours, check_interval_minutes=args.check_interval_minutes)

    # 8. 聚合结果
    print("\n8. 聚合统计结果...")
    stats = aggregate(args.db, skill_id_map)

    # 9. 打印混淆矩阵
    print_confusion_matrix(stats, cli_summary)

    # 10. 写入输出文件
    ended_at = datetime.now(timezone.utc)
    if args.output:
        write_output(args.output, args, stats, cli_summary, skill_id_map, started_at, ended_at)

    # 提示磁盘空间
    print(f"\n💡 提示: 后端可能使用了大量磁盘空间用于存储上传的 skill")
    print(f"   可以查看: ~/.agent-manager/scanner_uploaded_skills/")
    print(f"   如需清理可手动删除该目录下的内容")

    print("\n✅ 测试完成!")
    return 0

if __name__ == "__main__":
    sys.exit(main())

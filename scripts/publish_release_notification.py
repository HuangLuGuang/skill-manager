#!/usr/bin/env python3
"""Verify a release download and send its details to Enterprise WeChat."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request


class PublishError(RuntimeError):
    pass


def verify_download(url, expected_size):
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            status = response.getcode()
            first_byte = response.read(1)
            content_range = response.headers.get("Content-Range", "")
            content_length = response.headers.get("Content-Length", "")
    except urllib.error.HTTPError as exc:
        raise PublishError(f"预签名下载验证失败，HTTP 状态码: {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PublishError("预签名下载验证失败，无法读取 S3 文件") from None

    if status not in (200, 206) or len(first_byte) != 1:
        raise PublishError("预签名下载验证失败，未读取到文件内容")
    if status == 206:
        match = re.fullmatch(r"bytes 0-0/(\d+)", content_range)
        size = match.group(1) if match else ""
    else:
        size = content_length
    if not size.isdigit() or int(size) != expected_size:
        raise PublishError("预签名下载验证失败，S3 文件大小与本地产物不一致")


def format_size(size):
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.2f} {unit}"
        value /= 1024


def format_duration(seconds):
    parts = []
    for unit_seconds, label in ((86400, "天"), (3600, "小时"), (60, "分钟"), (1, "秒")):
        value, seconds = divmod(seconds, unit_seconds)
        if value:
            parts.append(f"{value} {label}")
    return " ".join(parts) or "0 秒"


def send_wechat(webhook_url, content):
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise PublishError(f"企业微信通知失败，HTTP 状态码: {exc.code}") from None
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        raise PublishError("企业微信通知失败，响应不可用") from None
    if not isinstance(result, dict) or result.get("errcode") != 0:
        code = result.get("errcode", "unknown") if isinstance(result, dict) else "unknown"
        raise PublishError(f"企业微信通知失败，errcode={code}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--download-url", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--expires-in", type=int, default=604800)
    args = parser.parse_args()
    webhook_url = os.environ.get("WECHAT_WEBHOOK_URL", "")
    if not webhook_url:
        raise PublishError("缺少环境变量 WECHAT_WEBHOOK_URL")
    if not 1 <= args.expires_in <= 604800:
        raise PublishError("预签名链接有效期必须在 1 到 604800 秒之间")
    try:
        size = args.archive.stat().st_size
        digest = hashlib.md5(usedforsecurity=False)
        with args.archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise PublishError("无法读取本地发布包") from None
    if size == 0:
        raise PublishError("本地发布包为空")
    verify_download(args.download_url, size)
    content = "\n".join([
        "**Agent Manager 发布完成**",
        f">版本：{args.version}",
        f">平台：{args.platform}",
        f">文件：{args.archive.name}",
        f">大小：{format_size(size)}",
        f">MD5：`{digest.hexdigest()}`",
        ">下载链接：",
        args.download_url,
        f">链接有效期：最长 {format_duration(args.expires_in)}（临时凭据到期时可能提前失效）",
    ])
    send_wechat(webhook_url, content)
    print("[INFO] 发布包下载验证通过，企业微信发布通知发送成功")


if __name__ == "__main__":
    try:
        main()
    except PublishError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

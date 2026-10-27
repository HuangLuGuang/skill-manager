"""Bounded inline image inputs and image-specific semantic verdicts."""
import base64
import binascii
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .api_errors import ApiError
from .prompt_guard import SEMANTIC_RULES

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def collect_images(messages):
    images = []
    for message_index, message in enumerate(messages):
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get('type') != 'image_url':
                continue
            if len(images) >= MAX_IMAGES:
                raise ApiError(422, 'prompt_guard.image_limit', '最多检测 3 张图片，每张不超过 2 MB', 'Up to 3 images, each at most 2 MB')
            value = part.get('image_url')
            url = value.get('url') if isinstance(value, dict) else None
            if not isinstance(url, str) or len(url) > MAX_IMAGE_BYTES * 4 // 3 + 128:
                raise ApiError(422, 'prompt_guard.image_invalid', '图片格式无效或超过 2 MB', 'Invalid image or image exceeds 2 MB')
            prefix, sep, encoded = url.partition(',')
            if prefix not in {'data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64'} or not sep:
                raise ApiError(422, 'prompt_guard.image_format', '请使用 PNG、JPEG 或 WebP 的 Base64 图片，暂不支持图片网址', 'Use inline Base64 PNG, JPEG or WebP images; image URLs are not supported')
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raw = b''
            valid = (prefix == 'data:image/png;base64' and raw.startswith(b'\x89PNG\r\n\x1a\n') or
                     prefix == 'data:image/jpeg;base64' and raw.startswith(b'\xff\xd8\xff') or
                     prefix == 'data:image/webp;base64' and raw.startswith(b'RIFF') and raw[8:12] == b'WEBP')
            if not valid or len(raw) > MAX_IMAGE_BYTES:
                raise ApiError(422, 'prompt_guard.image_invalid', '图片格式无效或超过 2 MB', 'Invalid image or image exceeds 2 MB')
            images.append({'message_index': message_index, 'url': url})
    return images


class ImageFinding(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    category: Literal[tuple(SEMANTIC_RULES)]
    severity: Literal['LOW', 'MEDIUM', 'HIGH']
    image_index: int = Field(ge=0)
    evidence: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class ImageVerdict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    findings: list[ImageFinding] = Field(max_length=20)

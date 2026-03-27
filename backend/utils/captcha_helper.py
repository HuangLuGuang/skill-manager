from captcha.image import ImageCaptcha
import random
import string
import base64
from io import BytesIO

def generate_captcha_text(length=4):
    """生成验证码文本，排除容易混淆的字符"""
    chars = 'ACDEFGHJKMNPQRTUVWXY23457'
    return ''.join(random.choice(chars) for _ in range(length))

def generate_captcha_image(text):
    image = ImageCaptcha(
        width=160,
        height=50,
        font_sizes=(36, 40, 44),
    )
    
    buffered = BytesIO()
    image.write(text, buffered)
    img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return img_str

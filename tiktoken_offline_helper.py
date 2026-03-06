"""
tiktoken_offline_helper.py
作用：在内网环境下，强制使用本地文件加载 o200k_base，绕过 tiktoken 的联网校验。
对其他模型无影响，保持原生行为。
"""

import os
import tiktoken
from tiktoken.load import load_tiktoken_bpe
from tiktoken.core import Encoding

# 配置你的本地缓存目录
LOCAL_CACHE_DIR = "/app/tiktoken_cache"
LOCAL_FILE_NAME = "o200k_base.tiktoken"

# o200k_base 专用的正则表达式 (官方标准，不要改)
O200K_BASE_PATTERN = r"""'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""


def get_encoding_safe(name: str):
    """
    安全的获取编码函数。
    如果是 'o200k_base'，则从本地文件加载；否则调用原生 tiktoken.get_encoding。
    """
    if name == "o200k_base":
        file_path = os.path.join(LOCAL_CACHE_DIR, LOCAL_FILE_NAME)

        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"【离线模式错误】找不到本地文件：{file_path}\n"
                f"请确保已将 o200k_base.tiktoken 文件放入该目录。"
            )

        # 【核心魔法】直接读取二进制文件，完全跳过 tiktoken 的 Hash 校验和联网逻辑
        print(f"🚀 [离线助手] 正在从本地加载 {name} ...")
        mergeable_ranks = load_tiktoken_bpe(file_path)

        encoding = Encoding(
            name=name,
            pat_str=O200K_BASE_PATTERN,
            mergeable_ranks=mergeable_ranks,
            special_tokens={}
        )
        print(f"✅ [离线助手] {name} 加载成功！")
        return encoding

    # 如果不是 o200k_base，直接调用原版函数，行为完全一致
    return tiktoken.get_encoding(name)
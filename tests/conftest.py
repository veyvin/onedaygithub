"""pytest 配置：让测试可以直接 import 项目根目录下的模块。"""
import os
import sys

# 将项目根目录加入 sys.path，使 `from generate_post import ...` 可用
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

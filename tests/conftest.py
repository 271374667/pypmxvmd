"""
PyMMD测试配置

提供pytest测试配置和共享fixture。
"""

import sys
from pathlib import Path

import pytest

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 测试数据目录
TEST_DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def test_data_dir():
    """返回测试数据目录路径"""
    return TEST_DATA_DIR


@pytest.fixture
def sample_pmx_file(test_data_dir):
    """返回示例PMX文件路径"""
    return test_data_dir / "api_test.pmx"

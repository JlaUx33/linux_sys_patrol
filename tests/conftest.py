# -*- coding: utf-8 -*-
"""测试共享 fixture：提供 fixtures 目录下真实格式样本的读取。"""

import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def fixture_text():
    """读取 fixtures 样本全文。"""
    def _read(name):
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
            return f.read()
    return _read


@pytest.fixture
def fixture_path():
    """返回 fixtures 样本的绝对路径。"""
    def _path(name):
        return os.path.join(FIXTURES, name)
    return _path

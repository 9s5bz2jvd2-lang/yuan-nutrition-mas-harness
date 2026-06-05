#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无需浏览器：把 state.example.json 复制成当前 state.json。"""
import json, pathlib, shutil
ROOT = pathlib.Path(__file__).resolve().parents[1]
src = ROOT/'data'/'state.example.json'
dst = ROOT/'data'/'state.json'
dst.parent.mkdir(exist_ok=True)
shutil.copyfile(src, dst)
print(f'已加载示例状态：{dst}')

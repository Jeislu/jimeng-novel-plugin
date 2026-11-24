"""剧本解析脚本共用的文本读写。

Python 默认按系统编码读写文件和输出：Windows 上是 GBK、cp1252 这类，读 UTF-8 的中文文件会报错或乱码，
写出的文件别的工具也读不对。这几个脚本读写文件、打印结果都走这里，统一用 UTF-8。
"""
import sys
from pathlib import Path


def read_text(path):
    """读文本文件：UTF-8（带不带 BOM 都行），不是 UTF-8 的按 GB18030 读（Windows 记事本存的中文 txt 常是 GBK）。
    换行统一成 \\n，和文本模式读的结果一致。"""
    data = Path(path).read_bytes()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('gb18030')
    return text.replace('\r\n', '\n').replace('\r', '\n')


def write_text(path, text):
    """写 UTF-8，换行用 \\n：各平台写出的文件一样。"""
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def utf8_stdio():
    """打印的 JSON 和报错带中文：Windows 控制台或管道的默认编码写不出时会报错，改成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')

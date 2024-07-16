import pkg_resources
import os
import sys
import json
import logging
try:
    import tomllib
except :
    import tomli as tomllib

# 配置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s- %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('log.txt')
    ]
)
logging.getLogger("httpx").setLevel(logging.ERROR)
current_package = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(current_package)


with open("config.toml", "rb") as f:
    config = tomllib.load(f)
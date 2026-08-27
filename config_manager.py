"""配置管理模块：加载/解析 API 密钥，环境变量优先"""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_HOT = None
CONFIG_RESERVE = None


def _resolve_key(cfg, env_key_name, env_base_name, env_model_name, default_base, default_model):
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get(env_key_name, "")
    if not cfg.get("api_base"):
        cfg["api_base"] = os.environ.get(env_base_name, default_base)
    if not cfg.get("model"):
        cfg["model"] = os.environ.get(env_model_name, default_model)
    return cfg


def load_config(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for k, v in default.items():
                    if k not in cfg or not cfg[k]:
                        cfg[k] = v
                return cfg
        except Exception:
            pass
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(default, f, ensure_ascii=False, indent=2)
    return default


def init_configs():
    global CONFIG_HOT, CONFIG_RESERVE
    CONFIG_HOT = load_config(os.path.join(BASE_DIR, "config", "config_taptap_hot.json"), {
        "api_base": "", "api_key": "", "model": ""
    })
    CONFIG_HOT = _resolve_key(CONFIG_HOT,
        "DEEPSEEK_API_KEY", "DEEPSEEK_API_BASE", "DEEPSEEK_MODEL",
        "https://api.deepseek.com", "deepseek-chat")
    CONFIG_RESERVE = load_config(os.path.join(BASE_DIR, "config", "config_taptap_reserve.json"), {
        "api_base": "", "api_key": "", "model": ""
    })
    CONFIG_RESERVE = _resolve_key(CONFIG_RESERVE,
        "DEEPSEEK_API_KEY", "DEEPSEEK_API_BASE", "DEEPSEEK_MODEL",
        "https://api.deepseek.com", "deepseek-chat")


def get_hot_config():
    if CONFIG_HOT is None:
        init_configs()
    return CONFIG_HOT


def get_reserve_config():
    if CONFIG_RESERVE is None:
        init_configs()
    return CONFIG_RESERVE

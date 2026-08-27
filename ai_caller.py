"""AI 调用模块：统一的 LLM API 调用与重试逻辑"""

import json
import re
import time
import random
import requests

from config_manager import get_hot_config


def call_ai(config, prompt, response_fields, max_retries=3):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}"
    }
    payload = {
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.01,
        "max_tokens": 4096,
    }
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep((2 ** attempt) + random.uniform(0, 2))
            resp = requests.post(
                f"{config['api_base']}/chat/completions",
                headers=headers, json=payload, timeout=90
            )
            if resp.status_code == 429:
                time.sleep(10); continue
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for f in response_fields:
                    if f not in data: data[f] = ""
                return data
            return {}
        except Exception as e:
            if attempt == max_retries - 1: break
            time.sleep(3)
    return {}


def call_ai_hot(html_text, game_name):
    if not html_text or len(html_text.strip()) < 100:
        return {}
    prompt = f"""从以下 TapTap 游戏页面中提取当前的节点信息，返回 JSON。

**重要时间约束**：只关注最近30天内或未来的事件（忽略"上线日期"等历史信息）。

**判断逻辑**：
1. 如果游戏已经上线（页面有"上线日期"且日期在过去），说明是已运营游戏，则提取"新版本/资料片/日常更新"信息
2. 如果游戏未上线（有"预约""测试招募"等），则提取测试/首发信息

**关键命名规则**：
- test_name 必须是有意义的活动/版本名称（如"折光异境""沉于生者的忘川""躲猫猫派对"），绝不能是纯版本号（如"0.5.1""3.19.2"）
- 如果页面有具体版本名称就用名称，没有就取"版本更新"或"—"

**测试类型规则**（test_type_raw）：
- 已上线游戏 → "新版本" / "资料片" / "日常更新"（不能是"公测""内测""封测"）
- 未上线游戏 → "限量删档计费" / "公测" / "首发" 等

字段:
- game_name: 游戏名称
- test_name: 有意义的版本/活动名称，"0.5.1"这类版本号不算，找名称
- test_time_raw: 节点日期原文（如"2026/05/28""2026/06/11"），没有填"—"
- test_type_raw: 类型（已上线填"新版本"/"资料片"/"日常更新"；未上线填"限量删档计费""公测"等），没有填"—"
- has_activation: 是否需要激活码/抢资格，填"是"或"否"或"—"
- is_wiped: 是否删档，填"是"或"否"或"—"

游戏名称: {game_name}

页面内容:
{html_text[:6000]}"""
    return call_ai(get_hot_config(), prompt, ["game_name", "test_name", "test_time_raw", "test_type_raw", "has_activation", "is_wiped"])

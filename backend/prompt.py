from settings import settings_manager

def get_chat_bot_prompt():
    return settings_manager.get_prompt("chat")

def get_astronomy_bot_prompt():
    return settings_manager.get_prompt("astronomy")

def get_electricity_bot_prompt():
    return settings_manager.get_prompt("electricity")

def get_mechanics_bot_prompt():
    return settings_manager.get_prompt("mechanics")

# 为了保持兼容性，保留原有的常量，但从设置管理器获取值
CHAT_BOT_PROMPT = get_chat_bot_prompt()
ASTRONOMY_BOT_PROMPT = get_astronomy_bot_prompt()
ELECTRICITY_BOT_PROMPT = get_electricity_bot_prompt()
MECHANICS_EXAMINER_PROMPT = get_mechanics_bot_prompt()
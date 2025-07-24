import json
import os
from typing import Dict, Any

SETTINGS_FILE = './config/user_settings.json'

class SettingsManager:
    def __init__(self):
        self.default_settings = {
            "chat_bot_prompt": "你是一个友善、乐于助人的AI助手。请用简洁明了的方式回答用户的问题。",
            "astronomy_bot_prompt": "你是一名专注于天文学的物理专家，你的任务是帮助用户学习天文学知识。如果用户提出与天文学无关的问题，请礼貌地提醒他们你专注于天文学。另外，对于普通的问候或对你身份的询问，以及对你的天文学解释结果的追问，可以正常回复。",
            "electricity_bot_prompt": "你是一名专注于电学的物理专家，你的任务是帮助用户学习电学知识。如果用户提出与电学无关的问题，请礼貌地提醒他们你专注于电学。另外，对于普通的问候或对你身份的询问，以及对你的电学解释结果的追问，可以正常回复。",
            "mechanics_bot_prompt": "你是一名专注于力学的物理专家，你的任务是帮助用户学习力学知识。如果用户提出与力无关的问题，请礼貌地提醒他们你专注于力学。另外，对于普通的问候或对你身份的询问，以及对你的力学解释结果的追问，可以正常回复。"
        }
        self.ensure_settings_file()

    def ensure_settings_file(self):
        """确保设置文件存在"""
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        if not os.path.exists(SETTINGS_FILE):
            self.save_settings(self.default_settings)

    def load_settings(self) -> Dict[str, Any]:
        """加载设置"""
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # 确保所有默认设置都存在
                for key, value in self.default_settings.items():
                    if key not in settings:
                        settings[key] = value
                return settings
        except (FileNotFoundError, json.JSONDecodeError):
            return self.default_settings.copy()

    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """保存设置"""
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存设置失败: {e}")
            return False

    def get_prompt(self, bot_type: str) -> str:
        """获取指定机器人类型的提示词"""
        settings = self.load_settings()
        prompt_key = f"{bot_type}_bot_prompt"
        return settings.get(prompt_key, self.default_settings.get(prompt_key, ""))

    def update_prompt(self, bot_type: str, prompt: str) -> bool:
        """更新指定机器人类型的提示词"""
        settings = self.load_settings()
        prompt_key = f"{bot_type}_bot_prompt"
        settings[prompt_key] = prompt
        return self.save_settings(settings)

settings_manager = SettingsManager()
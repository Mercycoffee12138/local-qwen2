import torch
from typing import List, Dict, Type, final, Union
import re
from abc import ABCMeta, abstractmethod
from model import QwModel
from prompt import *
import weakref
from logger import MyLogger
from transformers import PreTrainedTokenizerBase
import base64
import io
from PIL import Image
from qwen_vl_utils import process_vision_info


LOGGER = MyLogger()


class FlyweightMeta(type):

    def __new__(mcs, name, parents, dct):
        dct['pool'] = weakref.WeakValueDictionary()
        return super().__new__(mcs, name, parents, dct)
    
    @staticmethod
    def _serialize_params(cls, *args, **kwargs):
        args_list = list(map(str, args))
        args_list.extend([str(kwargs), cls.__name__])
        key = ''.join(args_list)
        return key
    
    def __call__(cls, *args, **kwargs):
        key = FlyweightMeta._serialize_params(cls, *args, **kwargs)
        pool = getattr(cls, 'pool', {})

        instance = pool.get(key)
        if instance is None:
            instance = super().__call__(*args, **kwargs)
            pool[key] = instance
        return instance


class Bot():

    __metaclass__ = ABCMeta

    def __init__(self, qw_model: QwModel, max_history: int = 4) -> None:
        self.tokenizer = qw_model.tokenizer
        self.model = qw_model.model
        self.processor = qw_model.processor  # 添加processor
        self.user_histories: Dict[str, List[Dict[str, str]]] = {}
        self.max_history = max_history
    @abstractmethod
    def generate_response(self, user_id: str, new_messages: List[Dict[str, Union[str, dict]]], max_length: int) -> str:
        pass  

    @final
    def _prepare_multimodal_history(self, user_id: str, new_messages: List[Dict[str, Union[str, dict]]], 
                                   system_prompt: Dict[str, str], max_input_tokens: int = 2048) -> List[Dict[str, Union[str, dict]]]:
        """处理包含多模态数据的历史消息"""
        if user_id not in self.user_histories:
            self.user_histories[user_id] = [system_prompt]

        history = self.user_histories[user_id]
        history.extend(new_messages)
        history = [system_prompt] + history[1:][-self.max_history:]

        # 处理多模态数据
        processed_history = []
        for msg in history:
            if isinstance(msg.get('content'), dict):
                # 处理包含媒体数据的消息
                processed_msg = self._process_media_message(msg)
                processed_history.append(processed_msg)
            else:
                processed_history.append(msg)
                
        return processed_history
    
    def _process_media_message(self, message: Dict[str, Union[str, dict]]) -> Dict[str, Union[str, dict]]:
        """处理包含多个媒体文件的消息"""
        content = message['content']

        if isinstance(content, list):
            # 这已经是官网示例的格式，直接返回
            return message
        elif isinstance(content, dict):
            # 兼容旧格式：单个媒体文件
            if content.get('type') == 'video':
                return {
                    'role': message['role'],
                    'content': [
                        {'type': 'video', 'video': content['video'], 'fps': content.get('fps', 1.0)},
                        {'type': 'text', 'text': content.get('text', '请分析这个视频内容。')}
                    ]
                }
            elif content.get('type') == 'image':
                return {
                    'role': message['role'],
                    'content': [
                        {'type': 'image', 'image': content['image']},
                        {'type': 'text', 'text': content.get('text', '请描述这张图片。')}
                    ]
                }

        return message

    @final 
    def generate_multimodal_response(self, messages, max_new_tokens=512):
        """生成多模态响应，支持多文件输入"""
        try:
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        
            print(f"处理的消息: {messages}")  # 调试输出
        
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )
            inputs = inputs.to("cuda")
        
            with torch.no_grad():
                generated_ids = self.model.generate(
                    **inputs, 
                    max_new_tokens=max_new_tokens,
                    min_new_tokens=20,           # 确保有足够的输出
                    do_sample=True,              # 启用采样
                    temperature=0.7,             # 适中的随机性
                    top_p=0.9,                   # nucleus采样
                    repetition_penalty=1.1,      # 减少重复
                    pad_token_id=self.processor.tokenizer.eos_token_id
                )
            
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
        
            output_text = self.processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )
        
            result = output_text[0] if output_text else ""
            print(f"生成的响应: {result}")  # 调试输出
            return result
        
        except Exception as e:
            print(f"多模态生成失败: {e}")
            return "抱歉，处理媒体文件时出现了错误。"
    
    @abstractmethod
    def reset_history(self, user_id: str) -> None:
        pass
    
    @final
    def _prepare_history(self, user_id: str, new_messages: List[Dict[str, str]], system_prompt: Dict[str, str], max_input_tokens: int = 2048, max_msg_tokens: int = 512) -> List[Dict[str, str]]:
        if user_id not in self.user_histories:
            self.user_histories[user_id] = [system_prompt]

        history = self.user_histories[user_id]
        history.extend(new_messages)
        history = [system_prompt] + history[1:][-self.max_history:]

        # 限制每条消息的长度，然后限制总token数
        tokenizer: PreTrainedTokenizerBase = self.tokenizer
        total_tokens = 0
        limited_history = []
    
        # 从后往前加，直到不超限
        for msg in reversed(history):
            content = msg['content']
        
            # 对每条消息进行长度截断
            tokens = tokenizer(content, add_special_tokens=False, return_tensors='pt')
            if tokens.input_ids.shape[-1] > max_msg_tokens:
                # 截断到指定长度
                truncated_tokens = tokens.input_ids[0][:max_msg_tokens]
                content = tokenizer.decode(truncated_tokens, skip_special_tokens=True)
                token_count = max_msg_tokens
            else:
                token_count = tokens.input_ids.shape[-1]
        
            if total_tokens + token_count > max_input_tokens:
                break
            
            # 创建截断后的消息
            truncated_msg = {'role': msg['role'], 'content': content}
            limited_history.insert(0, truncated_msg)
            total_tokens += token_count

        return limited_history
    
    @final
    def _generate_response(self, history: List[Dict[str, str]], max_length: int) -> str:
        input_ids = self.tokenizer.apply_chat_template(
        history, 
        tokenize=False, 
        add_generation_prompt=True,
        enable_thinking=False  # 添加这一行来启用思考模式
    )
        model_inputs = self.tokenizer([input_ids], return_tensors='pt', padding=True, truncation=True).to('cuda')

        with torch.no_grad():
            generated_ids = self.model.generate(
                model_inputs.input_ids,
                max_new_tokens=100000,
                attention_mask=model_inputs.attention_mask,
                do_sample=True,
                temperature=1.1,
                top_p=0.98,
                top_k=75,
            )

        generated_ids = [
            output_ids[len(model_inputs.input_ids[0]):] for output_ids in generated_ids
        ]

        response: str = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return response


class ChatBot(Bot, metaclass = FlyweightMeta):

    def __init__(self, qw_model: QwModel, max_history: int = 8) -> None:
        super().__init__(qw_model, max_history)
        self.user_histories: Dict[str, List[Dict[str, str]]] = {}
        self.__repr__ = self.__str__
        # 动态获取提示词
        self.system_prompt = {
            "role": "system",
            "content": settings_manager.get_prompt("chat")
        }

    def refresh_system_prompt(self):
        """刷新系统提示词"""
        self.system_prompt["content"] = settings_manager.get_prompt("chat")
    #机器人的自我介绍
    def __str__(self) -> str:
        return 'I am your best friend who is very handsome'

    def generate_response(self,user_id: str,new_messages: List[Dict[str, Union[str, dict]]],max_length: int,system_prompt=None) -> str:
        LOGGER.debug(new_messages)

    # 1. 选择 system_prompt
        if system_prompt:
            prompt = {"role": "system", "content": system_prompt}
        else:
            prompt = self.system_prompt

    # 2. 检查是否包含多模态内容
        has_multimodal = any(
            isinstance(msg.get('content'), list) and 
            any(item.get('type') in ['video', 'image'] for item in msg['content'] if isinstance(item, dict))
            for msg in new_messages
        )

        if has_multimodal:
        # 多模态处理
            system_message = [prompt]
            full_messages = system_message + new_messages
            response = self.generate_multimodal_response(full_messages, max_length)

        # 保存到历史 - 只保存文本部分
            if user_id not in self.user_histories:
                self.user_histories[user_id] = [prompt]

            text_only_messages = []
            for msg in new_messages:
                if isinstance(msg.get('content'), list):
                    text_parts = [item.get('text', '') for item in msg['content'] if item.get('type') == 'text']
                    text_content = ' '.join(text_parts) or "用户发送了媒体文件"
                    text_only_messages.append({'role': msg['role'], 'content': text_content})
                else:
                    text_only_messages.append(msg)

            self.user_histories[user_id].extend(text_only_messages)
            self.user_histories[user_id].append({'role': 'assistant', 'content': response})

        else:
        # 纯文本处理
            history = self._prepare_history(user_id, new_messages, prompt)
            response = self._generate_response(history, max_length)
            history.append({'role': 'assistant', 'content': response})
            self.user_histories[user_id] = history

        return response

    def reset_history(self, user_id):
        if user_id in self.user_histories:
            self.user_histories[user_id] = [self.system_prompt]


class AstronomyBot(Bot, metaclass = FlyweightMeta):

    def __init__(self, qw_model: QwModel, max_history: int = 8) -> None:
        super().__init__(qw_model, max_history)
        self.user_histories: Dict[str, List[Dict[str, str]]] = {}
        self.__repr__ = self.__str__
        # 动态获取提示词
        self.system_prompt = {
            "role": "system",
            "content": settings_manager.get_prompt("chat")
        }

    def refresh_system_prompt(self):
        """刷新系统提示词"""
        self.system_prompt["content"] = settings_manager.get_prompt("chat")

    def __str__(self) -> str:
        return 'An astronomy AI teacher who helps students with astronomy learning.'

    def generate_response(self, user_id: str, new_messages: List[Dict[str, str]], max_length: int, system_prompt=None) -> str:
        LOGGER.debug(new_messages)
        if system_prompt:
            prompt = {"role": "system", "content": system_prompt}
        else:
            prompt = self.system_prompt
        history = self._prepare_history(user_id, new_messages, prompt)
        response = self._generate_response(history, max_length)
        history.append({'role': 'assistant', 'content': response})
        self.user_histories[user_id] = history
        return response

    def reset_history(self, user_id):
        if user_id in self.user_histories:
            self.user_histories[user_id] = [self.system_prompt]
    
    def reset_history(self, user_id: str) -> None:
        if user_id in self.user_histories:
            self.user_histories[user_id] = [self.system_prompt]


class ElectricityBot(Bot, metaclass=FlyweightMeta):

    def __init__(self, qw_model: QwModel, max_history: int = 8) -> None:
        super().__init__(qw_model, max_history)
        self.user_histories: Dict[str, List[Dict[str, str]]] = {}
        self.__repr__ = self.__str__
        # 动态获取提示词
        self.system_prompt = {
            "role": "system",
            "content": settings_manager.get_prompt("chat")
        }

    def refresh_system_prompt(self):
        """刷新系统提示词"""
        self.system_prompt["content"] = settings_manager.get_prompt("chat")
        
    def __str__(self) -> str:
        return 'An electricity teacher who concentrates on helping users with electricity learning.'
 
    def generate_response(self, user_id: str, new_messages: List[Dict[str, str]], max_length: int, system_prompt=None) -> str:
        LOGGER.debug(new_messages)
        if system_prompt:
            prompt = {"role": "system", "content": system_prompt}
        else:
            prompt = self.system_prompt
        history = self._prepare_history(user_id, new_messages, prompt)
        response = self._generate_response(history, max_length)
        history.append({'role': 'assistant', 'content': response})
        self.user_histories[user_id] = history
        return response

    def reset_history(self, user_id):
        if user_id in self.user_histories:
            self.user_histories[user_id] = [self.system_prompt]


class MechanicsBot(Bot, metaclass=FlyweightMeta):

    def __init__(self, qw_model: QwModel, max_history: int = 8) -> None:
        super().__init__(qw_model, max_history)
        self.user_histories: Dict[str, List[Dict[str, str]]] = {}
        self.__repr__ = self.__str__
        # 动态获取提示词
        self.system_prompt = {
            "role": "system",
            "content": settings_manager.get_prompt("chat")
        }

    def refresh_system_prompt(self):
        """刷新系统提示词"""
        self.system_prompt["content"] = settings_manager.get_prompt("chat")

    def __str__(self) -> str:
        return 'A mechanics teacher who concentrates on helping users with mechanics learning.'

    def generate_response(self, user_id: str, new_messages: List[Dict[str, str]], max_length: int, system_prompt=None) -> str:
        LOGGER.debug(new_messages)
        if system_prompt:
            prompt = {"role": "system", "content": system_prompt}
        else:
            prompt = self.system_prompt
        history = self._prepare_history(user_id, new_messages, prompt)
        response = self._generate_response(history, max_length)
        history.append({'role': 'assistant', 'content': response})
        self.user_histories[user_id] = history
        return response

    def reset_history(self, user_id):
        if user_id in self.user_histories:
            self.user_histories[user_id] = [self.system_prompt]

class BotShop(object):

    def __init__(self, bot_cls: Type[Bot]) -> None:
        self.bot_cls = bot_cls

    def buy_bot(self, qw_model: QwModel, max_history: int=8) -> Bot:
        bot = self.bot_cls(qw_model, max_history)
        return bot
from pathlib import Path
import sys
import torch
import configargparse
from modelscope import Qwen2_5_VLForConditionalGeneration, AutoProcessor, AutoTokenizer
from qwen_vl_utils import process_vision_info  # 你需要有这个工具文件

parser = configargparse.ArgParser(description='Configuration for a chatbot')
parser.add_argument('-c', '--config', is_config_file=True,
                    help='config file path', default='./config/config.ini')
parser.add_argument('--model_path', help='Path of the model')
parser.add_argument('--bot_type', help='Type of the bot')
parser.add_argument('--origins', nargs='+', help='List of allowed origins', required=True)

args = parser.parse_args()
MODEL_PATH = args.model_path

PROJECT_ROOT = Path(__file__).absolute().parents[0].absolute()
sys.path.insert(0, str(PROJECT_ROOT))

class QwModel(object):
    instance = None
    def __new__(cls, *args, **kwargs):
        if not cls.instance:
            cls.instance = super(QwModel, cls).__new__(cls)
        return cls.instance

    def __init__(self) -> None:
        if hasattr(self, "initialized") and self.initialized:
            return
        self.processor = AutoProcessor.from_pretrained(MODEL_PATH, use_fast=True)
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, use_fast=True)
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            MODEL_PATH,
            torch_dtype=torch.bfloat16,
            device_map="auto"
        )
        #self.model = self.model.to('cuda')
        self.initialized = True

    def generate_multimodal_response(self, messages, max_new_tokens=128):
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
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
            generated_ids = self.model.generate(**inputs, max_new_tokens=max_new_tokens)
        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self.processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        return output_text[0] if output_text else ""

qw_model = QwModel()
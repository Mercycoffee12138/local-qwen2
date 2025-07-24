from gevent import monkey
monkey.patch_all()

from flask import Flask, request, jsonify, make_response, Response
import base64
import mimetypes
import json
from chatbot import *
from flask_cors import CORS
import uuid
from gevent.pywsgi import WSGIServer
import configargparse
from model import qw_model
from logger import MyLogger
import os
from settings import settings_manager


LOGGER: MyLogger = MyLogger()


parser = configargparse.ArgParser(description='Configuration for the server')
parser.add_argument('-c', '--config', is_config_file=True,
                    help='config file path', default='./config/config.ini')
parser.add_argument('--origins', nargs='+', help='List of allowed origins', required=True)
parser.add_argument('--model_path', help='Path of the model')
parser.add_argument('--bot_type', help='Type of the bot')
args = parser.parse_args()


app: Flask = Flask(__name__)
app.secret_key = '123456'  # 使用一个更复杂的密钥

CORS(app, resources={r"/*": {
    'origins': args.origins,
    "supports_credentials": True
}})

chatbot_shop: BotShop = BotShop(ChatBot)
astronomy_bot_shop: BotShop = BotShop(AstronomyBot)
chatbot: ChatBot = chatbot_shop.buy_bot(qw_model=qw_model, max_history=8)
astronomy_chatbot: AstronomyBot = astronomy_bot_shop.buy_bot(
    qw_model=qw_model, max_history=8)
electricity_shop: BotShop = BotShop(ElectricityBot)
electricity_bot: ElectricityBot = electricity_shop.buy_bot(
    qw_model=qw_model, max_history=8)
mechanics_shop: BotShop = BotShop(MechanicsBot)
mechanics_bot: MechanicsBot = mechanics_shop.buy_bot(qw_model=qw_model, max_history=8)

@app.route('/settings', methods=['GET'])
def get_settings():
    """获取所有设置"""
    settings = settings_manager.load_settings()
    response = make_response(jsonify(settings))
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

@app.route('/settings', methods=['POST', 'OPTIONS'])
def update_settings():
    """更新设置"""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, GET')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response

    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # 保存设置
    success = settings_manager.save_settings(data)
    
    if success:
        # 刷新所有机器人的系统提示词
        chatbot.refresh_system_prompt()
        astronomy_chatbot.refresh_system_prompt()
        electricity_bot.refresh_system_prompt()
        mechanics_bot.refresh_system_prompt()
        
        response = make_response(jsonify({'message': 'Settings updated successfully'}))
    else:
        response = make_response(jsonify({'error': 'Failed to update settings'}), 500)
    
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

@app.route('/settings/prompt/<bot_type>', methods=['PUT', 'OPTIONS'])
def update_prompt(bot_type):
    """更新特定机器人的提示词"""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'PUT')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response

    data = request.json
    prompt = data.get('prompt', '')
    
    if not prompt:
        return jsonify({'error': 'Prompt cannot be empty'}), 400

    success = settings_manager.update_prompt(bot_type, prompt)
    
    if success:
        # 刷新对应机器人的系统提示词
        if bot_type == 'chat':
            chatbot.refresh_system_prompt()
        elif bot_type == 'astronomy':
            astronomy_chatbot.refresh_system_prompt()
        elif bot_type == 'electricity':
            electricity_bot.refresh_system_prompt()
        elif bot_type == 'mechanics':
            mechanics_bot.refresh_system_prompt()
        
        response = make_response(jsonify({'message': f'{bot_type} prompt updated successfully'}))
    else:
        response = make_response(jsonify({'error': 'Failed to update prompt'}), 500)
    
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response


@app.route('/upload', methods=['POST', 'OPTIONS'])
def upload_file():
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # 检查文件类型
    mimetype, _ = mimetypes.guess_type(file.filename)
    if not mimetype or not (mimetype.startswith('video/') or mimetype.startswith('image/')):
        return jsonify({'error': 'Only video and image files are supported'}), 400

    # 保存文件到本地
    upload_dir = './uploads'
    os.makedirs(upload_dir, exist_ok=True)
    file_ext = os.path.splitext(file.filename)[1]
    save_name = f"{uuid.uuid4().hex}{file_ext}"
    save_path = os.path.join(upload_dir, save_name)
    file.save(save_path)

    # 返回本地文件路径（file:// 协议）
    file_url = f"file://{os.path.abspath(save_path)}"
    file_type = 'video' if mimetype.startswith('video/') else 'image'

    return jsonify({
        'success': True,
        'file_id': str(uuid.uuid4()),
        'file_type': file_type,
        'file_path': file_url,  # 这里返回本地路径
        'mimetype': mimetype
    })

@app.route('/chat', methods=['POST', 'OPTIONS'])
def generate_response():
    if request.method == 'OPTIONS':
        print("收到OPTIONS预检请求")
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin',
                             request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response
    
    print('====收到的原始请求体====')
    print(request.get_data(as_text=True))  # 新增，打印原始body
    data = request.json
    system_prompt = data.get('system_prompt', None)
    LOGGER.info(f"system_prompt: {system_prompt}")
    print("收到的数据：", data)
    
    bot_type = data.get('bot_type', {'value': 'normal'}).get('value', 'normal')
    messages = data.get('messages', [])
    max_length = data.get('max_length', 100000)
    current_message = data.get('currentMessage', '')
    user_id = request.cookies.get('user_id')
    
    LOGGER.info(f'{user_id}:{current_message}')
    
    # 处理多模态消息（支持多文件）
    if isinstance(current_message, dict) and current_message.get('content'):
        if isinstance(current_message['content'], list):
            # 新的多文件格式
            print(f"处理多文件消息: {len([item for item in current_message['content'] if item.get('type') in ['video', 'image']])} 个媒体文件")
            new_messages = [current_message]
        else:
            # 单文件格式（兼容性）
            new_messages = [current_message]
    else:
        # 普通文本消息
        current_message = current_message['content'] if isinstance(current_message, dict) else current_message
        new_messages = [{'role': 'user', 'content': current_message}]
    
    if not user_id:
        user_id = str(uuid.uuid4())
    
    # 根据bot类型生成响应
    if bot_type == 'normal':
        response = chatbot.generate_response(user_id, new_messages, max_length, system_prompt=system_prompt)
    elif bot_type == 'astronomy':
        response = astronomy_chatbot.generate_response(user_id, new_messages, max_length, system_prompt=system_prompt)
    elif bot_type == 'electricity':
        response = electricity_bot.generate_response(user_id, new_messages, max_length, system_prompt=system_prompt)
    elif bot_type == 'mechanics':
        response = mechanics_bot.generate_response(user_id, new_messages, 16000, system_prompt=system_prompt)
    else:
        return jsonify({'error': 'Invalid bot type'}), 400
    
    resp = make_response(jsonify({'response': response, 'user_id': user_id}))
    resp.headers.add('Access-Control-Allow-Origin',
                     request.headers.get('Origin', '*'))
    resp.headers.add('Access-Control-Allow-Credentials', 'true')
    resp.set_cookie('user_id', user_id, httponly=True,
                    secure=True, samesite='None', max_age=3600*24*30)
    
    LOGGER.info(f'bot: {user_id}->{response}')
    LOGGER.info(f"Setting cookie: user_id={user_id}")
    return resp



@app.route('/reset', methods=['POST'])
def reset_history():
    user_id = request.cookies.get('user_id')
    if user_id:
        chatbot.reset_history(user_id)
        astronomy_chatbot.reset_history(user_id)
        return jsonify({'message': f'History reset for user {user_id}'})
    else:
        return jsonify({'error': 'No user ID found'}), 400


if __name__ == '__main__':
    # app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
    http_server = WSGIServer(('0.0.0.0', 5001), app)
    http_server.serve_forever()

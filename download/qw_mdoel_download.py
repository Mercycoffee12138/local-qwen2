from modelscope import snapshot_download
model_dir = snapshot_download('qwen/Qwen2.5-VL-3B-Instruct', 
                              cache_dir='./qw/qw_model_file/', 
                              revision='master')
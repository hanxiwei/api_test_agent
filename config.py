import os
import yaml

# 全局变量缓存配置
_config = None

def load_config(config_file="config.yaml"):
    """
    加载 yaml 配置文件，如果文件不存在则返回默认配置。
    """
    global _config
    if _config is not None:
        return _config
        
    default_config = {
        "llm": {"model": "gpt-4o-mini", "temperature": 0.2},
        "healing": {"max_rounds": 3, "enable_long_memory": True},
        "api": {"default_base_url": "http://localhost:8080"},
        "execution": {"test_dir": "generated_tests"}
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                user_config = yaml.safe_load(f)
                
            # 简单合并字典 (只合一层)
            if user_config:
                for k, v in user_config.items():
                    if k in default_config and isinstance(v, dict):
                        default_config[k].update(v)
                    else:
                        default_config[k] = v
        except Exception as e:
            print(f"读取配置文件 {config_file} 失败，将使用默认配置。错误: {e}")
            
    _config = default_config
    return _config

def get_config(section, key, default=None):
    """
    快捷获取配置值的函数。例如: get_config('llm', 'model')
    """
    cfg = load_config()
    return cfg.get(section, {}).get(key, default)

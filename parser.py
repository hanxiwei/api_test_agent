import prance

def parse_openapi(file_path):
    """
    解析 OpenAPI (Swagger) 文件，提取出每个 API 接口的详细信息。
    
    返回格式示例：
    [
        {
            'path': '/pet/{petId}', 
            'method': 'GET', 
            'operationId': 'getPetById', 
            'parameters': [...],
            'requestBody': {...}
        }
    ]
    """
    print(f"正在解析 OpenAPI 文件: {file_path}")## hhh:打印解析的文件路径
    
    # ResolvingParser 会自动帮我们解析 YAML/JSON，并处理好内部的 $ref 引用

    parser = prance.ResolvingParser(file_path)## hhh:创建解析器
    spec = parser.specification## hhh:解析OpenAPI文件
    
    endpoints = []## hhh:初始化空列表，用于存储每个 API 接口的详细信息
  
    paths = spec.get('paths', {})## hhh:获取所有路径定义
    
    # 遍历每个路径 (例如: /pet/{petId})
    for path, methods in paths.items():
        # 遍历每个方法 (例如: get, post)
        for method, details in methods.items():
            # 过滤掉非 HTTP 方法的字段（OpenAPI 规范中有些其他字段也会放在这）
            if method.lower() not in ['get', 'post', 'put', 'delete', 'patch']:
                continue
                
            # 提取我们需要喂给大模型的核心信息
            endpoint_info = {
                'path': path,
                'method': method.upper(),
                # 如果 API 没写 operationId，我们自动生成一个（例如 GET_/pet/{petId}）
                'operationId': details.get('operationId', f"{method}_{path.replace('/', '_').replace('{', '').replace('}', '')}"),
                'summary': details.get('summary', ''),
                'parameters': details.get('parameters', []),
                'requestBody': details.get('requestBody', {}),
                # 提取 x-async 扩展字段（异步接口标注）
                'x-async': details.get('x-async')
            }
            endpoints.append(endpoint_info)
            
    print(f"解析完成！共发现 {len(endpoints)} 个 API 接口。")## hhh:打印解析完成的接口数量
    return endpoints


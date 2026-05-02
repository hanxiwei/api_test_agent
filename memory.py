import os
import chromadb
import uuid

# -------------------------
# 1. 短期记忆 (内存字典)
# -------------------------
# 它的生命周期仅在本次运行 (pipeline.py 执行期间) 有效。
# 如果遇到了同样的报错，直接从这里拿上次修好的代码，不花钱去问大模型。
short_memory = {}

def get_short_memory(error_signature):
    """从短期记忆中获取修复代码"""
    if error_signature in short_memory:
        print(f"  [Memory] [Short-term] 命中短期记忆！直接复用修复方案。")
        return short_memory[error_signature]
    return None

def save_short_memory(error_signature, fixed_code):
    """将成功的修复保存到短期记忆"""
    short_memory[error_signature] = fixed_code

# -------------------------
# 2. 长期记忆 (本地硬盘向量库)
# -------------------------
# 它的生命周期是永久的，存在 .chroma_db 文件夹里。
# 以后即使关机重启，遇到类似的报错，也能搜出之前的经验给大模型做参考。

# 初始化 ChromaDB 客户端，数据存在当前目录的 .chroma_db 文件夹
CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(__file__), ".chroma_db")
chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

# 获取或创建一个叫做 "repairs" (修复记录) 的集合
collection = chroma_client.get_or_create_collection(name="repairs")

def get_long_memory(error_log, top_k=2):
    """
    通过相似度检索，从长期记忆中找出最相似的 N 个历史报错和修复方案。
    我们把 "error_log" 作为搜索的 Query 扔给 Chroma。
    """
    # 如果数据库是空的，直接返回空
    if collection.count() == 0:
        return []
        
    print(f"  [Memory] [Long-term] 正在长期记忆库中检索相似错误...")
    results = collection.query(
        query_texts=[error_log],
        n_results=top_k
    )
    
    # 解析 Chroma 返回的结果
    memory_examples = []
    # results['documents'] 存的是历史报错，results['metadatas'] 存的是当时修好的代码
    if results and results['documents'] and len(results['documents'][0]) > 0:
        for i in range(len(results['documents'][0])):
            doc = results['documents'][0][i]
            meta = results['metadatas'][0][i]
            # distance 越小说明越相似
            distance = results['distances'][0][i] if 'distances' in results and results['distances'] else 0
            
            # 只取相对比较相似的经验 (距离阈值可以根据实际情况调)
            if distance < 1.5: 
                memory_examples.append({
                    "past_error": doc,
                    "past_fixed_code": meta.get("fixed_code", "")
                })
                
    if memory_examples:
        print(f"  [Memory] [Long-term] 找到 {len(memory_examples)} 条相似的长期记忆经验！")
        
    return memory_examples

def save_long_memory(error_log, error_signature, fixed_code):
    """
    将一次成功的修复经验存入长期记忆库。
    """
    doc_id = str(uuid.uuid4())
    
    collection.add(
        documents=[error_log], # 正文存完整的报错日志，用来做相似度检索
        metadatas=[{           # 元数据存具体的签名和修复代码，供大模型参考
            "error_signature": error_signature,
            "fixed_code": fixed_code
        }],
        ids=[doc_id]
    )
    print(f"  [Memory] [Long-term] 已将修复经验永久存入长期记忆库 (ID: {doc_id[:8]})")

# -------------------------
# 3. 辅助函数
# -------------------------
def generate_error_signature(error_log):
    """
    生成一个简短的错误签名，用于短期记忆的精确匹配。
    比如从一堆 traceback 里提取出最后一行: "AssertionError: assert 1 == 2"
    """
    lines = error_log.strip().split('\n')
    # 通常最后一行包含了最核心的异常信息
    signature = lines[-1] if lines else "UnknownError"
    # 如果最后一行太短或没营养，可以拼上倒数第二行
    if len(signature) < 10 and len(lines) >= 2:
        signature = lines[-2] + " | " + signature
    return signature

if __name__ == "__main__":
    # 本地简单测试
    print("当前长期记忆库中有", collection.count(), "条记录。")

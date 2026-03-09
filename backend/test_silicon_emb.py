# -*- coding: utf-8 -*-
"""
单独测试 SiliconFlow 向量模型接入
"""
import asyncio
import os
import sys

# 加载 .env
from dotenv import load_dotenv
load_dotenv()

from agents.memory import SiliconFlowEmbeddingProvider

async def main():
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        print("❌ 未在 .env 或环境变量中找到 SILICONFLOW_API_KEY")
        print("请在 backend/.env 中添加 SILICONFLOW_API_KEY=sk-xxxxxx")
        sys.exit(1)

    model = os.environ.get("SILICONFLOW_EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
    print(f"✅ 找到 SILICONFLOW_API_KEY, 准备测试模型: {model}")
    print("-" * 50)
    
    provider = SiliconFlowEmbeddingProvider(api_key=api_key, model=model)
    
    texts = [
        "Silicon flow embedding online: fast, affordable, and high-quality embedding services. come try it out!",
        "这是一个用来测试中文向量生成的样本句子。",
    ]
    
    print(f"正在对 {len(texts)} 条文本进行嵌入计算...")
    try:
        embeddings = await provider.embed(texts)
        print("✅ 嵌入计算成功！")
        for i, (text, emb) in enumerate(zip(texts, embeddings)):
            print(f"\n文本 {i+1}: {text}")
            print(f"向量维度: {len(emb)}")
            print(f"向量前5个值: {emb[:5]}")
            
    except Exception as e:
        print(f"❌ 嵌入计算失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

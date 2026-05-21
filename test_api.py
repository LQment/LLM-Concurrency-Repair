from openai import OpenAI
client = OpenAI(
    api_key="sk-2a5f6e801a9146609d859fdfb1267678",
    base_url="https://api.deepseek.com/v1"
)
try:
    models = client.models.list()
    print("API连接成功！模型列表：")
    for model in models:
        print(f"  - {model.id}")
except Exception as e:
    print(f"错误：{e}")

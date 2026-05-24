import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from constants import *

print(f"Testing with MODEL={MODEL}, BASE_URL={BASE_URL}")
print(f"API_KEY={'***' + API_KEY[-4:] if API_KEY else 'EMPTY'}")

from openai import OpenAI
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 1. 列出模型
try:
    models = client.models.list()
    print("models.list() OK, available models:")
    for m in models:
        print(f"  - {m.id}")
except Exception as e:
    print(f"models.list() FAILED: {e}")

# 2. 发一次 chat completion
try:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "say hello in one word"}],
        max_tokens=10,
    )
    print(f"chat.completions.create OK: {resp.choices[0].message.content}")
except Exception as e:
    print(f"chat.completions.create FAILED: {e}")

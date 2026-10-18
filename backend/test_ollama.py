from ollama import chat

response = chat(
    model="qwen3:4b",
    messages=[
        {
            "role": "user",
            "content": "Explain a graph database in one sentence."
        }
    ],
)

print(response.message.content)

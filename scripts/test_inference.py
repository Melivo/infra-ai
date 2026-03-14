#!/usr/bin/env python3
from openai import OpenAI


def main() -> None:
    client = OpenAI(base_url="http://localhost:8000/v1", api_key="local")

    response = client.chat.completions.create(
        model="Qwen/Qwen3-32B",
        messages=[
            {
                "role": "user",
                "content": "Antworte in einem kurzen Satz: Läuft der lokale vLLM-Server?",
            }
        ],
        temperature=0.2,
        max_tokens=128,
    )

    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()

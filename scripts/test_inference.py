#!/usr/bin/env python3
import os

from openai import OpenAI


def main() -> None:
    base_url = os.environ.get("INFRA_AI_BASE_URL", "http://localhost:8000/v1")
    api_key = os.environ.get("INFRA_AI_API_KEY", "local")

    client = OpenAI(base_url=base_url, api_key=api_key)
    models = client.models.list()
    model_id = os.environ.get("INFRA_AI_MODEL") or models.data[0].id

    response = client.chat.completions.create(
        model=model_id,
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

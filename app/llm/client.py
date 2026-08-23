from langchain_openai import ChatOpenAI

from app.config import config


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=config.lm_base_url,
        api_key=config.lm_api_key,
        model=config.lm_model,
        temperature=temperature,
    )

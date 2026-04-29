from __future__ import annotations

from abc import ABC, abstractmethod


class ModelProvider(ABC):
    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model

    @abstractmethod
    def refine_claim(self, section: str, candidate: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def summarize_section(self, section: str, claims: list[str]) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_response(self, prompt: str, context: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def run_agent(self, prompt: str) -> str:
        """Run an extraction/planning agent prompt and return raw text."""
        raise NotImplementedError

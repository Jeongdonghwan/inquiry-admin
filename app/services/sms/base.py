from abc import ABC, abstractmethod


class SmsProvider(ABC):
    name = "base"

    @abstractmethod
    def send(self, to: str, from_: str, body: str, msg_type: str, title: str | None = None) -> tuple[bool, str | None, str | None]:
        """(ok, provider_msg_id, error)"""

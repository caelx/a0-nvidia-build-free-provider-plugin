from __future__ import annotations

from helpers.api import ApiHandler, Request
from usr.plugins.provider_nvidia_build_free.helpers.catalog import model_response


class Models(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET"]

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    async def process(self, input: dict, request: Request) -> dict:
        return await model_response()

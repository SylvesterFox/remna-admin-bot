import logging

from modules.api.client import RemnaAPI

logger = logging.getLogger(__name__)


class InternalSquadAPI:
    """API client for Remnawave internal squads."""

    @staticmethod
    async def get_all_internal_squads():
        """Fetch all internal squads."""
        try:
            response = await RemnaAPI.get("internal-squads")
        except Exception as exc:
            logger.error("Error fetching internal squads: %s", exc)
            return []

        if not response:
            return []

        if isinstance(response, dict):
            if "internalSquads" in response and isinstance(response["internalSquads"], list):
                return response["internalSquads"]
            if "response" in response and isinstance(response["response"], dict):
                squads = response["response"].get("internalSquads")
                if isinstance(squads, list):
                    return squads

        if isinstance(response, list):
            return response

        logger.warning("Unexpected internal squads response format: %s", type(response).__name__)
        return []

import os
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def configure_web_licensing(args: Dict[str, Any]) -> None:
    """
    Configure ANSYS Web Licensing settings.
    
    Expected:
      - args['web_account_id'] (optional): UUID string for ANSYS_LICENSING_WEB_ACCOUNTS.
        If not provided, falls back to the known UUID supplied by the user.

    Effect:
      - Sets ANSYS_LICENSING_WEB_ACCOUNTS for this process.
      - Sets ANSYS_LICENSING_SERVICE_PRIORITY = "web-shared,fnp,web-elastic".
      - DOES NOT set FlexNet variables (ANSYSLMD_LICENSE_FILE / ANSYSLI_SERVERS).

    Notes:
      - Under Web Licensing, FlexNet checkout logs may be absent. pos_simulation() is adapted.
    """
    # Use provided UUID from args or fallback to the known user-provided UUID
    web_uuid = args.get(
        "web_account_id",
        "bf89e499-5997-4b42-b987-054ba153ab78"
    )

    if not web_uuid or not isinstance(web_uuid, str):
        raise ValueError("A valid web_account_id (UUID) is required for Web Licensing.")

    # Core web licensing configuration
    os.environ["ANSYS_LICENSING_WEB_ACCOUNTS"] = web_uuid
    logger.info("Set ANSYS_LICENSING_WEB_ACCOUNTS for Web Licensing.")

    # Service priority: try web-shared, then FlexNet (fnp), then web-elastic
    os.environ["ANSYS_LICENSING_SERVICE_PRIORITY"] = "web-shared,fnp,web-elastic"
    logger.info("Set ANSYS_LICENSING_SERVICE_PRIORITY=web-shared,fnp,web-elastic")

    # Optional: some environments prefer explicitly setting mode
    # os.environ["ANSYS_LICENSING_MODE"] = "WEB"
    # logger.info("Set ANSYS_LICENSING_MODE=WEB")
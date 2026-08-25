from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...auth import User, current_user
from ...database import Database
from ...dependencies import get_database

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])


class IntegrationsOut(BaseModel):
    slack_connected: bool
    linear_connected: bool
    linear_team_id: str | None


class IntegrationsUpdate(BaseModel):
    # None (the field omitted or explicitly null) leaves that value
    # unchanged; "" clears it. Distinguishing "don't touch" from "clear
    # this" is why these aren't just plain optional strings with no
    # further meaning.
    slack_webhook_url: str | None = Field(default=None, max_length=500)
    linear_api_key: str | None = Field(default=None, max_length=200)
    linear_team_id: str | None = Field(default=None, max_length=100)


def _mask_present(value: str | None) -> bool:
    return bool(value)


@router.get("", response_model=IntegrationsOut)
async def get_integrations(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> IntegrationsOut:
    row = await database.fetch_one(
        "SELECT slack_webhook_url, linear_api_key, linear_team_id FROM users WHERE id=%s", (user.id,)
    )
    row = row or {}
    return IntegrationsOut(
        slack_connected=_mask_present(row.get("slack_webhook_url")),
        linear_connected=_mask_present(row.get("linear_api_key")),
        linear_team_id=row.get("linear_team_id"),
    )


@router.put("", response_model=IntegrationsOut)
async def update_integrations(
    payload: IntegrationsUpdate,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> IntegrationsOut:
    updates: dict[str, str] = payload.model_dump(exclude_none=True)
    if updates:
        set_clause = ", ".join(f"{key}=%s" for key in updates)
        await database.execute(
            f"UPDATE users SET {set_clause} WHERE id=%s",
            (*updates.values(), user.id),
        )
    return await get_integrations(database=database, user=user)

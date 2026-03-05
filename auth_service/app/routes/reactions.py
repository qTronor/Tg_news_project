from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..dependencies import get_current_user
from ..models import MessageReaction, User
from ..schemas import ReactionInfo, ReactionRequest

router = APIRouter(prefix="/messages", tags=["reactions"])


@router.post("/{event_id}/reaction", status_code=status.HTTP_201_CREATED)
async def add_reaction(
    event_id: str,
    body: ReactionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(MessageReaction).where(
            MessageReaction.user_id == user.id,
            MessageReaction.message_event_id == event_id,
        )
    )
    reaction = existing.scalar_one_or_none()

    if reaction:
        if reaction.reaction == body.reaction:
            await db.delete(reaction)
            return {"status": "removed", "reaction": None}
        reaction.reaction = body.reaction
        return {"status": "changed", "reaction": body.reaction}

    new_reaction = MessageReaction(
        user_id=user.id,
        message_event_id=event_id,
        reaction=body.reaction,
    )
    db.add(new_reaction)
    return {"status": "added", "reaction": body.reaction}


@router.get("/{event_id}/reactions", response_model=ReactionInfo)
async def get_reactions(
    event_id: str,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    likes_q = await db.execute(
        select(func.count()).where(
            MessageReaction.message_event_id == event_id,
            MessageReaction.reaction == "like",
        )
    )
    dislikes_q = await db.execute(
        select(func.count()).where(
            MessageReaction.message_event_id == event_id,
            MessageReaction.reaction == "dislike",
        )
    )

    user_reaction = None
    if user:
        user_r = await db.execute(
            select(MessageReaction.reaction).where(
                MessageReaction.user_id == user.id,
                MessageReaction.message_event_id == event_id,
            )
        )
        user_reaction = user_r.scalar_one_or_none()

    return ReactionInfo(
        message_event_id=event_id,
        likes=likes_q.scalar() or 0,
        dislikes=dislikes_q.scalar() or 0,
        user_reaction=user_reaction,
    )


@router.post("/batch-reactions")
async def batch_reactions(
    event_ids: list[str],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(event_ids) > 100:
        raise HTTPException(status_code=400, detail="Max 100 event IDs at once")

    likes_q = await db.execute(
        select(MessageReaction.message_event_id, func.count())
        .where(
            MessageReaction.message_event_id.in_(event_ids),
            MessageReaction.reaction == "like",
        )
        .group_by(MessageReaction.message_event_id)
    )
    dislikes_q = await db.execute(
        select(MessageReaction.message_event_id, func.count())
        .where(
            MessageReaction.message_event_id.in_(event_ids),
            MessageReaction.reaction == "dislike",
        )
        .group_by(MessageReaction.message_event_id)
    )
    user_reactions_q = await db.execute(
        select(MessageReaction.message_event_id, MessageReaction.reaction)
        .where(
            MessageReaction.user_id == user.id,
            MessageReaction.message_event_id.in_(event_ids),
        )
    )

    likes_map = dict(likes_q.all())
    dislikes_map = dict(dislikes_q.all())
    user_map = dict(user_reactions_q.all())

    return [
        ReactionInfo(
            message_event_id=eid,
            likes=likes_map.get(eid, 0),
            dislikes=dislikes_map.get(eid, 0),
            user_reaction=user_map.get(eid),
        )
        for eid in event_ids
    ]

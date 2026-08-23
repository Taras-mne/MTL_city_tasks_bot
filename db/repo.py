from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AccessRequest, AllowedUser, Tag, Task, TaskAssignee, TaskTag, utcnow

PAGE = 9

LINK_DESC_LIMIT = 100


def _pages(total: int) -> int:
    return max(1, ceil(total / PAGE))


def _clamp(page: int, pages: int) -> int:
    return min(max(page, 0), pages - 1)


def cut_link_desc(text: str | None) -> str | None:
    if not text:
        return None
    return text[:LINK_DESC_LIMIT]


# --- задачи ---

async def list_tasks(s: AsyncSession, page: int, show_done: bool):
    where = (Task.deleted_at.is_(None), Task.is_done == bool(show_done))
    total = await s.scalar(select(func.count()).select_from(Task).where(*where)) or 0
    pages = _pages(total)
    page = _clamp(page, pages)
    # активные: сначала горящие дедлайны, потом бездедлайновые по свежести
    order = (Task.id.desc(),) if show_done else (Task.deadline.is_(None), Task.deadline, Task.id.desc())
    items = list(await s.scalars(
        select(Task).where(*where).order_by(*order).limit(PAGE).offset(page * PAGE)
    ))
    return items, total, page, pages


async def get_task(s: AsyncSession, task_id: int) -> Task | None:
    return await s.scalar(select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)))


async def create_task(s: AsyncSession, name: str) -> Task:
    task = Task(name=name)
    s.add(task)
    await s.flush()
    return task


async def delete_task(s: AsyncSession, task_id: int):
    task = await get_task(s, task_id)
    if task:
        task.deleted_at = utcnow()


async def emoji_map(s: AsyncSession, task_ids: list[int]) -> dict[int, str]:
    if not task_ids:
        return {}
    rows = await s.execute(
        select(TaskTag.task_id, Tag.emoji)
        .join(Tag, TaskTag.tag_id == Tag.id)
        .where(
            TaskTag.task_id.in_(task_ids),
            TaskTag.deleted_at.is_(None),
            Tag.deleted_at.is_(None),
        )
        .order_by(Tag.name)
    )
    result: dict[int, str] = {}
    for task_id, emoji in rows:
        result[task_id] = result.get(task_id, "") + emoji
    return result


# --- связки задача-тег ---

async def task_links(s: AsyncSession, task_id: int):
    rows = await s.execute(
        select(TaskTag, Tag)
        .join(Tag, TaskTag.tag_id == Tag.id)
        .where(
            TaskTag.task_id == task_id,
            TaskTag.deleted_at.is_(None),
            Tag.deleted_at.is_(None),
        )
        .order_by(Tag.name)
    )
    return rows.all()


async def get_link(s: AsyncSession, task_id: int, tag_id: int):
    rows = await s.execute(
        select(TaskTag, Tag)
        .join(Tag, TaskTag.tag_id == Tag.id)
        .where(
            TaskTag.task_id == task_id,
            TaskTag.tag_id == tag_id,
            TaskTag.deleted_at.is_(None),
            Tag.deleted_at.is_(None),
        )
    )
    return rows.first()


async def get_raw_link(s: AsyncSession, task_id: int, tag_id: int) -> TaskTag | None:
    return await s.scalar(
        select(TaskTag).where(TaskTag.task_id == task_id, TaskTag.tag_id == tag_id)
    )


async def attach(s: AsyncSession, task_id: int, tag_id: int, description: str | None):
    description = cut_link_desc(description)
    link = await get_raw_link(s, task_id, tag_id)
    if link:
        link.deleted_at = None
        link.description = description
    else:
        s.add(TaskTag(task_id=task_id, tag_id=tag_id, description=description))


async def detach(s: AsyncSession, task_id: int, tag_id: int):
    link = await get_raw_link(s, task_id, tag_id)
    if link and link.deleted_at is None:
        link.deleted_at = utcnow()


# --- теги ---

async def list_tags(s: AsyncSession, page: int):
    where = (Tag.deleted_at.is_(None),)
    total = await s.scalar(select(func.count()).select_from(Tag).where(*where)) or 0
    pages = _pages(total)
    page = _clamp(page, pages)
    items = list(await s.scalars(
        select(Tag).where(*where).order_by(Tag.name).limit(PAGE).offset(page * PAGE)
    ))
    return items, total, page, pages


async def get_tag(s: AsyncSession, tag_id: int) -> Tag | None:
    return await s.scalar(select(Tag).where(Tag.id == tag_id, Tag.deleted_at.is_(None)))


async def create_tag(s: AsyncSession, name: str, emoji: str, description: str | None, needs_description: bool) -> Tag:
    tag = Tag(name=name, emoji=emoji, description=description, needs_description=needs_description)
    s.add(tag)
    await s.flush()
    return tag


async def delete_tag(s: AsyncSession, tag_id: int):
    tag = await get_tag(s, tag_id)
    if tag:
        tag.deleted_at = utcnow()


async def tag_usage(s: AsyncSession, tag_id: int) -> int:
    return await s.scalar(
        select(func.count())
        .select_from(TaskTag)
        .join(Task, TaskTag.task_id == Task.id)
        .where(
            TaskTag.tag_id == tag_id,
            TaskTag.deleted_at.is_(None),
            Task.deleted_at.is_(None),
        )
    ) or 0


async def available_tags(s: AsyncSession, task_id: int, page: int):
    attached = select(TaskTag.tag_id).where(
        TaskTag.task_id == task_id, TaskTag.deleted_at.is_(None)
    )
    where = (Tag.deleted_at.is_(None), Tag.id.not_in(attached))
    total = await s.scalar(select(func.count()).select_from(Tag).where(*where)) or 0
    pages = _pages(total)
    page = _clamp(page, pages)
    items = list(await s.scalars(
        select(Tag).where(*where).order_by(Tag.name).limit(PAGE).offset(page * PAGE)
    ))
    return items, total, page, pages


# --- допущенные пользователи ---

async def list_allowed(s: AsyncSession, page: int):
    total = await s.scalar(select(func.count()).select_from(AllowedUser)) or 0
    pages = _pages(total)
    page = _clamp(page, pages)
    items = list(await s.scalars(
        select(AllowedUser).order_by(AllowedUser.id).limit(PAGE).offset(page * PAGE)
    ))
    return items, total, page, pages


async def find_allowed_by_username(s: AsyncSession, username: str) -> AllowedUser | None:
    return await s.scalar(select(AllowedUser).where(AllowedUser.username == username))


async def add_allowed(s: AsyncSession, username: str, added_by: int) -> AllowedUser:
    user = AllowedUser(username=username, added_by=added_by)
    s.add(user)
    await s.flush()
    return user


# --- ответственные ---

async def task_assignees(s: AsyncSession, task_id: int) -> list[AllowedUser]:
    return list(await s.scalars(
        select(AllowedUser)
        .join(TaskAssignee, TaskAssignee.allowed_user_id == AllowedUser.id)
        .where(TaskAssignee.task_id == task_id, TaskAssignee.deleted_at.is_(None))
        .order_by(AllowedUser.id)
    ))


async def get_raw_assignment(s: AsyncSession, task_id: int, user_id: int) -> TaskAssignee | None:
    return await s.scalar(
        select(TaskAssignee).where(
            TaskAssignee.task_id == task_id, TaskAssignee.allowed_user_id == user_id
        )
    )


async def assign(s: AsyncSession, task_id: int, user_id: int):
    link = await get_raw_assignment(s, task_id, user_id)
    if link:
        link.deleted_at = None
    else:
        s.add(TaskAssignee(task_id=task_id, allowed_user_id=user_id))


async def unassign(s: AsyncSession, task_id: int, user_id: int):
    link = await get_raw_assignment(s, task_id, user_id)
    if link and link.deleted_at is None:
        link.deleted_at = utcnow()


async def available_assignees(s: AsyncSession, task_id: int, page: int):
    assigned = select(TaskAssignee.allowed_user_id).where(
        TaskAssignee.task_id == task_id, TaskAssignee.deleted_at.is_(None)
    )
    where = (AllowedUser.id.not_in(assigned),)
    total = await s.scalar(select(func.count()).select_from(AllowedUser).where(*where)) or 0
    pages = _pages(total)
    page = _clamp(page, pages)
    items = list(await s.scalars(
        select(AllowedUser).where(*where).order_by(AllowedUser.id).limit(PAGE).offset(page * PAGE)
    ))
    return items, total, page, pages


async def feed_tasks(s: AsyncSession, user_id: int) -> list[Task]:
    """Фид: задачи, за которые отвечает пользователь, плюс задачи с продвигаемым
    тегом (они первыми), дальше по дедлайну."""
    mine = select(TaskAssignee.task_id).where(
        TaskAssignee.allowed_user_id == user_id, TaskAssignee.deleted_at.is_(None)
    )
    promoted = (
        select(TaskTag.task_id)
        .join(Tag, TaskTag.tag_id == Tag.id)
        .where(
            TaskTag.deleted_at.is_(None),
            Tag.deleted_at.is_(None),
            Tag.promote_feed == True,  # noqa: E712
        )
    )
    return list(await s.scalars(
        select(Task)
        .where(
            Task.deleted_at.is_(None),
            Task.is_done == False,  # noqa: E712
            Task.id.in_(mine) | Task.id.in_(promoted),
        )
        .order_by(
            Task.id.not_in(promoted),  # продвигаемые (False) первыми
            Task.deadline.is_(None), Task.deadline, Task.id.desc(),
        )
    ))


async def links_map(s: AsyncSession, task_ids: list[int]) -> dict[int, list]:
    """{task_id: [(TaskTag, Tag), ...]} для пачки задач."""
    if not task_ids:
        return {}
    rows = await s.execute(
        select(TaskTag, Tag)
        .join(Tag, TaskTag.tag_id == Tag.id)
        .where(
            TaskTag.task_id.in_(task_ids),
            TaskTag.deleted_at.is_(None),
            Tag.deleted_at.is_(None),
        )
        .order_by(Tag.name)
    )
    result: dict[int, list] = {}
    for link, tag in rows:
        result.setdefault(link.task_id, []).append((link, tag))
    return result


async def is_assigned(s: AsyncSession, task_id: int, user_id: int) -> bool:
    link = await get_raw_assignment(s, task_id, user_id)
    return bool(link and link.deleted_at is None)


async def digest_data(s: AsyncSession):
    """(AllowedUser, [Task, ...]) для всех, кому есть что напомнить и до кого
    бот может достучаться (известен telegram_id)."""
    rows = await s.execute(
        select(AllowedUser, Task)
        .join(TaskAssignee, TaskAssignee.allowed_user_id == AllowedUser.id)
        .join(Task, TaskAssignee.task_id == Task.id)
        .where(
            AllowedUser.telegram_id.is_not(None),
            TaskAssignee.deleted_at.is_(None),
            Task.deleted_at.is_(None),
            Task.is_done == False,  # noqa: E712
        )
        .order_by(AllowedUser.id, Task.deadline.is_(None), Task.deadline, Task.id.desc())
    )
    grouped: dict[int, list] = {}
    result = []
    for user, task in rows:
        if user.id not in grouped:
            grouped[user.id] = []
            result.append((user, grouped[user.id]))
        grouped[user.id].append(task)
    return result


# --- заявки на доступ (постучавшиеся) ---

async def count_requests(s: AsyncSession) -> int:
    return await s.scalar(select(func.count()).select_from(AccessRequest)) or 0


async def list_requests(s: AsyncSession, page: int):
    total = await count_requests(s)
    pages = _pages(total)
    page = _clamp(page, pages)
    items = list(await s.scalars(
        select(AccessRequest).order_by(AccessRequest.id).limit(PAGE).offset(page * PAGE)
    ))
    return items, total, page, pages


async def get_request(s: AsyncSession, request_id: int) -> AccessRequest | None:
    return await s.scalar(select(AccessRequest).where(AccessRequest.id == request_id))


async def find_request_by_tid(s: AsyncSession, telegram_id: int) -> AccessRequest | None:
    return await s.scalar(select(AccessRequest).where(AccessRequest.telegram_id == telegram_id))


async def upsert_request(s: AsyncSession, telegram_id: int, username: str | None, full_name: str):
    req = await find_request_by_tid(s, telegram_id)
    if req:
        req.username = username
        req.full_name = full_name
        return req
    req = AccessRequest(telegram_id=telegram_id, username=username, full_name=full_name)
    s.add(req)
    await s.flush()
    return req


async def approve_request(s: AsyncSession, request_id: int, added_by: int) -> int | None:
    """Впускает постучавшегося: переносит в allowed_users и убирает заявку.
    Возвращает telegram_id впущенного (или None, если заявки уже нет)."""
    req = await get_request(s, request_id)
    if not req:
        return None
    existing = await s.scalar(
        select(AllowedUser).where(AllowedUser.telegram_id == req.telegram_id)
    )
    if not existing and req.username:
        existing = await find_allowed_by_username(s, req.username)
    if existing:
        existing.telegram_id = existing.telegram_id or req.telegram_id
    else:
        s.add(AllowedUser(username=req.username, telegram_id=req.telegram_id, added_by=added_by))
    telegram_id = req.telegram_id
    await s.delete(req)
    return telegram_id

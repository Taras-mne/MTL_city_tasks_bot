from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    # локальное время; дата без времени хранится как 23:59 (конец дня)
    deadline: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    emoji: Mapped[str] = mapped_column(String(16))
    description: Mapped[str | None] = mapped_column(Text)
    needs_description: Mapped[bool] = mapped_column(Boolean, default=False)
    # задачи с таким тегом попадают в фид всем и встают первыми
    promote_feed: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class TaskTag(Base):
    __tablename__ = "task_tags"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    description: Mapped[str | None] = mapped_column(String(100))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class TaskAssignee(Base):
    __tablename__ = "task_assignees"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    allowed_user_id: Mapped[int] = mapped_column(ForeignKey("allowed_users.id"), primary_key=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class AllowedUser(Base):
    __tablename__ = "allowed_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # nullable: постучавшегося без юзернейма впускаем по telegram_id
    username: Mapped[str | None] = mapped_column(String(32), unique=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    added_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(32))
    full_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

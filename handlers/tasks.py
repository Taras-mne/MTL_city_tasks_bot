import re
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db import repo
from screens import esc, finish, kb, prompt, reprompt, show

from .states import St

router = Router()

DEADLINE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?$")

DEADLINE_HINT = (
    "Форматы: <code>31.12</code>, <code>31.12 18:00</code>, "
    "<code>31.12.2026</code>, <code>31.12.2026 18:00</code>.\n"
    "Без года — ближайшая такая дата, без времени — конец дня."
)


def parse_deadline(text: str) -> datetime | None:
    m = DEADLINE_RE.match(text.strip())
    if not m:
        return None
    day, month, year, hour, minute = m.groups()
    now = datetime.now()
    try:
        dt = datetime(
            int(year) if year else now.year, int(month), int(day),
            int(hour) if hour else 23, int(minute) if minute is not None else 59,
        )
    except ValueError:
        return None
    if not year and dt < now:
        try:
            dt = dt.replace(year=dt.year + 1)
        except ValueError:
            return None
    return dt


# --- список ---

@router.callback_query(F.data == "tl")
async def cb_list(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, "tl")


@router.callback_query(F.data.startswith("tlp:"))
async def cb_list_page(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.update_data(tp=int(cb.data.split(":")[1]))
    await show(cb, session, state, "tl")


@router.callback_query(F.data == "tld")
async def cb_toggle_done_view(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    await state.update_data(td=0 if data.get("td") else 1, tp=0)
    await show(cb, session, state, "tl")


# --- создание ---

@router.callback_query(F.data == "tnew")
async def cb_new(cb: CallbackQuery, state: FSMContext):
    await prompt(cb, state, St.task_new_name, "➕ Название новой задачи?", "tl")


@router.message(St.task_new_name)
async def msg_new_name(message: Message, state: FSMContext, session: AsyncSession):
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        return await reprompt(message, state, "Нужен текст до 100 символов.")
    task = await repo.create_task(session, name)
    await finish(message, state, session, f"tc:{task.id}")


# --- карточка ---

@router.callback_query(F.data.startswith("tc:"))
async def cb_card(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, cb.data)


@router.callback_query(F.data.startswith("tdone:"))
async def cb_toggle_done(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    task = await repo.get_task(session, task_id)
    if task:
        task.is_done = not task.is_done
    await show(cb, session, state, f"tc:{task_id}")


@router.callback_query(F.data.startswith("tdel:"))
async def cb_delete_ask(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    task = await repo.get_task(session, task_id)
    if not task:
        return await show(cb, session, state, "tl")
    await cb.message.edit_text(
        f"🗑 Удалить задачу «{esc(task.name)}»?",
        reply_markup=kb([[("🗑 Да, удалить", f"tdely:{task_id}"), ("❌ Нет", f"tc:{task_id}")]]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("tdely:"))
async def cb_delete_yes(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await repo.delete_task(session, int(cb.data.split(":")[1]))
    await show(cb, session, state, "tl", "Удалил 🗑")


# --- правка названия и описания ---

@router.callback_query(F.data.startswith("ten:"))
async def cb_edit_name(cb: CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    await state.update_data(t_id=task_id)
    await prompt(cb, state, St.task_name, "✏️ Новое название задачи?", f"tc:{task_id}")


@router.message(St.task_name)
async def msg_edit_name(message: Message, state: FSMContext, session: AsyncSession):
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        return await reprompt(message, state, "Нужен текст до 100 символов.")
    data = await state.get_data()
    task = await repo.get_task(session, data["t_id"])
    if task:
        task.name = name
    await finish(message, state, session)


@router.callback_query(F.data.startswith("ted:"))
async def cb_edit_desc(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    task = await repo.get_task(session, task_id)
    if not task:
        return await show(cb, session, state, "tl")
    extra = [[("🧹 Очистить", f"tdc:{task_id}")]] if task.description else None
    await state.update_data(t_id=task_id)
    await prompt(cb, state, St.task_desc, "📝 Новое описание задачи?", f"tc:{task_id}", extra)


@router.message(St.task_desc)
async def msg_edit_desc(message: Message, state: FSMContext, session: AsyncSession):
    text = (message.text or "").strip()
    if not text or len(text) > 1000:
        return await reprompt(message, state, "Нужен текст до 1000 символов.")
    data = await state.get_data()
    task = await repo.get_task(session, data["t_id"])
    if task:
        task.description = text
    await finish(message, state, session)


@router.callback_query(F.data.startswith("tdc:"))
async def cb_clear_desc(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    task = await repo.get_task(session, task_id)
    if task:
        task.description = None
    await state.set_state(None)
    await show(cb, session, state, f"tc:{task_id}", "Очистил 🧹")


# --- дедлайн ---

@router.callback_query(F.data.startswith("tdl:"))
async def cb_edit_deadline(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    task = await repo.get_task(session, task_id)
    if not task:
        return await show(cb, session, state, "tl")
    extra = [[("🧹 Убрать дедлайн", f"tdlc:{task_id}")]] if task.deadline else None
    await state.update_data(t_id=task_id)
    await prompt(
        cb, state, St.task_deadline,
        "⏰ Когда дедлайн?\n" + DEADLINE_HINT,
        f"tc:{task_id}", extra,
    )


@router.message(St.task_deadline)
async def msg_edit_deadline(message: Message, state: FSMContext, session: AsyncSession):
    deadline = parse_deadline(message.text or "")
    if not deadline:
        return await reprompt(message, state, "Не разобрал дату.")
    data = await state.get_data()
    task = await repo.get_task(session, data["t_id"])
    if task:
        task.deadline = deadline
    await finish(message, state, session)


@router.callback_query(F.data.startswith("tdlc:"))
async def cb_clear_deadline(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    task = await repo.get_task(session, task_id)
    if task:
        task.deadline = None
    await state.set_state(None)
    await show(cb, session, state, f"tc:{task_id}", "Убрал дедлайн 🧹")


# --- теги задачи ---

@router.callback_query(F.data.startswith("tt:"))
async def cb_task_tags(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, cb.data)


@router.callback_query(F.data.startswith("lnk:"))
async def cb_link(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, cb.data)


@router.callback_query(F.data.startswith("det:"))
async def cb_detach(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, task_id, tag_id = cb.data.split(":")
    await repo.detach(session, int(task_id), int(tag_id))
    await show(cb, session, state, f"tt:{task_id}", "Открепил ➖")


@router.callback_query(F.data.startswith("lde:"))
async def cb_link_desc_edit(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, task_id, tag_id = cb.data.split(":")
    pair = await repo.get_link(session, int(task_id), int(tag_id))
    if not pair:
        return await show(cb, session, state, f"tt:{task_id}")
    link, _tag = pair
    extra = [[("🧹 Очистить", f"ldc:{task_id}:{tag_id}")]] if link.description else None
    await state.update_data(l_task=int(task_id), l_tag=int(tag_id), ld_mode="edit")
    await prompt(
        cb, state, St.link_desc,
        "✏️ Описание связки? (до 100 символов, лишнее обрежу)",
        f"lnk:{task_id}:{tag_id}", extra,
    )


@router.callback_query(F.data.startswith("ldc:"))
async def cb_link_desc_clear(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, task_id, tag_id = cb.data.split(":")
    link = await repo.get_raw_link(session, int(task_id), int(tag_id))
    if link:
        link.description = None
    await state.set_state(None)
    await show(cb, session, state, f"lnk:{task_id}:{tag_id}", "Очистил 🧹")


# --- мой фид (назначить/снять себя) ---

@router.callback_query(F.data.startswith("tf:"))
async def cb_toggle_feed(cb: CallbackQuery, session: AsyncSession, state: FSMContext, me):
    task_id = int(cb.data.split(":")[1])
    if await repo.is_assigned(session, task_id, me.id):
        await repo.unassign(session, task_id, me.id)
        toast = "Убрал из фида ➖"
    else:
        await repo.assign(session, task_id, me.id)
        toast = "Добавил в фид 📌"
    await show(cb, session, state, f"tc:{task_id}", toast)


# --- ответственные ---

@router.callback_query(F.data.startswith("ta:"))
async def cb_assignees(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, cb.data)


@router.callback_query(F.data.startswith("tad:"))
async def cb_unassign(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, task_id, user_id = cb.data.split(":")
    await repo.unassign(session, int(task_id), int(user_id))
    await show(cb, session, state, f"ta:{task_id}", "Снял 👋")


@router.callback_query(F.data.startswith("taa:"))
async def cb_assign_list(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.update_data(sp=0)
    await show(cb, session, state, cb.data)


@router.callback_query(F.data.startswith("tap:"))
async def cb_assign_page(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, task_id, page = cb.data.split(":")
    await state.update_data(sp=int(page))
    await show(cb, session, state, f"taa:{task_id}")


@router.callback_query(F.data.startswith("tas:"))
async def cb_assign_do(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, task_id, user_id = cb.data.split(":")
    await repo.assign(session, int(task_id), int(user_id))
    await show(cb, session, state, f"ta:{task_id}", "Назначил ✅")


# --- прикрепление ---

@router.callback_query(F.data.startswith("at:"))
async def cb_attach_list(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.update_data(ap=0)
    await show(cb, session, state, cb.data)


@router.callback_query(F.data.startswith("atp:"))
async def cb_attach_page(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, task_id, page = cb.data.split(":")
    await state.update_data(ap=int(page))
    await show(cb, session, state, f"at:{task_id}")


@router.callback_query(F.data.startswith("atd:"))
async def cb_attach_do(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, task_id, tag_id = cb.data.split(":")
    tag = await repo.get_tag(session, int(tag_id))
    if not tag:
        return await show(cb, session, state, f"at:{task_id}")
    if tag.needs_description:
        await state.update_data(l_task=int(task_id), l_tag=int(tag_id), ld_mode="attach")
        await prompt(
            cb, state, St.link_desc,
            f"Тег {tag.emoji} «{esc(tag.name)}» требует описание связки.\n"
            "Пришли текст (до 100 символов):",
            f"at:{task_id}",
        )
    else:
        await repo.attach(session, int(task_id), int(tag_id), None)
        await show(cb, session, state, f"tt:{task_id}", "Прикрепил ✅")


@router.message(St.link_desc)
async def msg_link_desc(message: Message, state: FSMContext, session: AsyncSession):
    text = (message.text or "").strip()
    if not text:
        return await reprompt(message, state, "Нужен текст.")
    data = await state.get_data()
    task_id, tag_id = data["l_task"], data["l_tag"]
    if data.get("ld_mode") == "attach":
        await repo.attach(session, task_id, tag_id, text)
        await finish(message, state, session, f"tt:{task_id}")
    else:
        link = await repo.get_raw_link(session, task_id, tag_id)
        if link:
            link.description = repo.cut_link_desc(text)
        await finish(message, state, session, f"lnk:{task_id}:{tag_id}")

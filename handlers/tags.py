from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db import repo
from screens import esc, finish, kb, prompt, prompt_msg, reprompt, safe_edit, show, try_delete

from .states import St

router = Router()


def _valid_emoji(s: str) -> bool:
    return bool(s) and len(s) <= 16 and " " not in s and "\n" not in s


# --- список и карточка ---

@router.callback_query(F.data == "gl")
async def cb_list(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, "gl")


@router.callback_query(F.data.startswith("glp:"))
async def cb_list_page(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.update_data(gp=int(cb.data.split(":")[1]))
    await show(cb, session, state, "gl")


@router.callback_query(F.data.startswith("gc:"))
async def cb_card(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, cb.data)


# --- правки полей ---

@router.callback_query(F.data.startswith("gen:"))
async def cb_edit_name(cb: CallbackQuery, state: FSMContext):
    tag_id = int(cb.data.split(":")[1])
    await state.update_data(g_id=tag_id)
    await prompt(cb, state, St.tag_edit_name, "✏️ Новое название тега?", f"gc:{tag_id}")


@router.message(St.tag_edit_name)
async def msg_edit_name(message: Message, state: FSMContext, session: AsyncSession):
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        return await reprompt(message, state, "Нужен текст до 100 символов.")
    data = await state.get_data()
    tag = await repo.get_tag(session, data["g_id"])
    if tag:
        tag.name = name
    await finish(message, state, session)


@router.callback_query(F.data.startswith("gee:"))
async def cb_edit_emoji(cb: CallbackQuery, state: FSMContext):
    tag_id = int(cb.data.split(":")[1])
    await state.update_data(g_id=tag_id)
    await prompt(cb, state, St.tag_edit_emoji, "😀 Новый эмодзи для тега?", f"gc:{tag_id}")


@router.message(St.tag_edit_emoji)
async def msg_edit_emoji(message: Message, state: FSMContext, session: AsyncSession):
    emoji = (message.text or "").strip()
    if not _valid_emoji(emoji):
        return await reprompt(message, state, "Пришли один эмодзи.")
    data = await state.get_data()
    tag = await repo.get_tag(session, data["g_id"])
    if tag:
        tag.emoji = emoji
    await finish(message, state, session)


@router.callback_query(F.data.startswith("ged:"))
async def cb_edit_desc(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    tag_id = int(cb.data.split(":")[1])
    tag = await repo.get_tag(session, tag_id)
    if not tag:
        return await show(cb, session, state, "gl")
    extra = [[("🧹 Очистить", f"gdc:{tag_id}")]] if tag.description else None
    await state.update_data(g_id=tag_id)
    await prompt(cb, state, St.tag_edit_desc, "📝 Новое описание тега?", f"gc:{tag_id}", extra)


@router.message(St.tag_edit_desc)
async def msg_edit_desc(message: Message, state: FSMContext, session: AsyncSession):
    text = (message.text or "").strip()
    if not text or len(text) > 500:
        return await reprompt(message, state, "Нужен текст до 500 символов.")
    data = await state.get_data()
    tag = await repo.get_tag(session, data["g_id"])
    if tag:
        tag.description = text
    await finish(message, state, session)


@router.callback_query(F.data.startswith("gdc:"))
async def cb_clear_desc(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    tag_id = int(cb.data.split(":")[1])
    tag = await repo.get_tag(session, tag_id)
    if tag:
        tag.description = None
    await state.set_state(None)
    await show(cb, session, state, f"gc:{tag_id}", "Очистил 🧹")


@router.callback_query(F.data.startswith("gnd:"))
async def cb_toggle_needs(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    tag_id = int(cb.data.split(":")[1])
    tag = await repo.get_tag(session, tag_id)
    if tag:
        tag.needs_description = not tag.needs_description
    await show(cb, session, state, f"gc:{tag_id}")


@router.callback_query(F.data.startswith("gpf:"))
async def cb_toggle_promote(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    tag_id = int(cb.data.split(":")[1])
    tag = await repo.get_tag(session, tag_id)
    if tag:
        tag.promote_feed = not tag.promote_feed
    await show(cb, session, state, f"gc:{tag_id}")


# --- удаление ---

@router.callback_query(F.data.startswith("gdel:"))
async def cb_delete_ask(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    tag_id = int(cb.data.split(":")[1])
    tag = await repo.get_tag(session, tag_id)
    if not tag:
        return await show(cb, session, state, "gl")
    await cb.message.edit_text(
        f"🗑 Удалить тег {tag.emoji} «{esc(tag.name)}»? Он пропадёт из всех задач.",
        reply_markup=kb([[("🗑 Да, удалить", f"gdely:{tag_id}"), ("❌ Нет", f"gc:{tag_id}")]]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("gdely:"))
async def cb_delete_yes(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await repo.delete_tag(session, int(cb.data.split(":")[1]))
    await show(cb, session, state, "gl", "Удалил 🗑")


# --- создание тега (цепочка: имя → эмодзи → описание → флаг) ---

@router.callback_query(F.data.startswith("ntg:"))
async def cb_new_tag(cb: CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split(":")[1])  # 0 = из раздела тегов, иначе создаём из задачи
    await state.update_data(nt_task=task_id)
    ret = f"tt:{task_id}" if task_id else "gl"
    await prompt(cb, state, St.tag_name, "🆕 Название нового тега?", ret)


@router.message(St.tag_name)
async def msg_new_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        return await reprompt(message, state, "Нужен текст до 100 символов.")
    await try_delete(message)
    await state.update_data(nt_name=name)
    await prompt_msg(message.bot, message.chat.id, state, St.tag_emoji, "😀 Эмодзи для тега?")


@router.message(St.tag_emoji)
async def msg_new_emoji(message: Message, state: FSMContext):
    emoji = (message.text or "").strip()
    if not _valid_emoji(emoji):
        return await reprompt(message, state, "Пришли один эмодзи.")
    await try_delete(message)
    await state.update_data(nt_emoji=emoji)
    await prompt_msg(
        message.bot, message.chat.id, state, St.tag_desc,
        "📝 Описание тега? (необязательно)",
        [[("⏭ Пропустить", "ntskip")]],
    )


async def _ask_needs(bot, chat_id, state: FSMContext):
    await state.set_state(None)
    data = await state.get_data()
    rows = [
        [("❗ Да, обязательно", "ntnd:1"), ("Нет", "ntnd:0")],
        [("❌ Отмена", "cxl")],
    ]
    await safe_edit(
        bot, chat_id, data["smid"],
        "Требовать описание связки при прикреплении этого тега?",
        kb(rows),
    )


@router.message(St.tag_desc)
async def msg_new_desc(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text or len(text) > 500:
        return await reprompt(message, state, "Нужен текст до 500 символов.")
    await try_delete(message)
    await state.update_data(nt_desc=text)
    await _ask_needs(message.bot, message.chat.id, state)


@router.callback_query(F.data == "ntskip")
async def cb_skip_desc(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("nt_name"):
        return await cb.answer("Устарело")
    await state.update_data(nt_desc=None)
    await _ask_needs(cb.bot, cb.message.chat.id, state)
    await cb.answer()


@router.callback_query(F.data.startswith("ntnd:"))
async def cb_needs_choice(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    if not data.get("nt_name"):
        return await cb.answer("Устарело")
    needs = cb.data.endswith("1")
    tag = await repo.create_tag(session, data["nt_name"], data["nt_emoji"], data.get("nt_desc"), needs)
    task_id = data.get("nt_task") or 0
    await state.update_data(nt_name=None, nt_desc=None)
    if not task_id:
        return await show(cb, session, state, f"gc:{tag.id}", "Создал ✅")
    if needs:
        await state.update_data(l_task=task_id, l_tag=tag.id, ld_mode="attach")
        await prompt(
            cb, state, St.link_desc,
            f"Тег {tag.emoji} «{esc(tag.name)}» требует описание связки.\n"
            "Пришли текст (до 100 символов):",
            f"tt:{task_id}",
        )
    else:
        await repo.attach(session, task_id, tag.id, None)
        await show(cb, session, state, f"tt:{task_id}", "Создал и прикрепил ✅")

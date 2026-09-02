from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db import repo
from screens import hide_images, render_screen, screen_menu, show

router = Router()


@router.callback_query(F.data == "knock")
async def cb_knock(cb: CallbackQuery, session: AsyncSession):
    user = cb.from_user
    username = (user.username or "").lower() or None
    await repo.upsert_request(session, user.id, username, user.full_name)
    try:
        await cb.message.edit_text("🚪 Заявка отправлена. Как впустят — бот напишет.")
    except Exception:
        pass
    await cb.answer("Постучался ✅")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession):
    await hide_images(message.bot, message.chat.id, state)
    await state.set_state(None)
    text, markup = await screen_menu(session)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.set_state(None)
    await show(cb, session, state, "menu")


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data == "cxl")
async def cb_cancel(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await hide_images(cb.bot, cb.message.chat.id, state)
    data = await state.get_data()
    await state.set_state(None)
    await render_screen(
        cb.bot, cb.message.chat.id, cb.message.message_id,
        state, session, data, data.get("ret", "menu"),
    )
    await cb.answer("Отменил")


@router.message(StateFilter(None))
async def any_message(message: Message, session: AsyncSession, state: FSMContext):
    await hide_images(message.bot, message.chat.id, state)
    text, markup = await screen_menu(session)
    await message.answer(text, reply_markup=markup)

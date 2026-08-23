"""Сборка экранов (текст + inline-клавиатура) и общие помощники навигации.

Бот живёт в одном сообщении-«экране» и редактирует его. Все экраны собираются
здесь и используются как из колбэков, так и после текстового ввода (FSM).
"""

import html
from contextvars import ContextVar
from datetime import datetime

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import repo

# кто сейчас работает с ботом (AllowedUser); ставится в middleware на каждый апдейт
CURRENT_USER: ContextVar = ContextVar("current_user", default=None)

FEED_LIMIT = 15


def esc(s):
    return html.escape(s or "")


def trunc(s, n=56):
    return s if len(s) <= n else s[: n - 1] + "…"


def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=c) for t, c in row]
            for row in rows
        ]
    )


def user_label(u):
    return f"@{u.username}" if u.username else f"без ника (id {u.telegram_id})"


def fmt_deadline(dt):
    text = dt.strftime("%d.%m.%Y")
    if (dt.hour, dt.minute) != (23, 59):
        text += dt.strftime(" %H:%M")
    return text


def deadline_note(dt):
    now = datetime.now()
    if dt < now:
        return "⚠️ просрочен"
    days = (dt.date() - now.date()).days
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    return f"через {days} дн."


def nav_row(prefix, page, pages):
    if pages <= 1:
        return None
    return [
        ("«", f"{prefix}:{(page - 1) % pages}"),
        (f"{page + 1}/{pages}", "noop"),
        ("»", f"{prefix}:{(page + 1) % pages}"),
    ]


def grid(items, label, cbdata, per_row=3):
    rows, row = [], []
    for it in items:
        row.append((trunc(label(it), 24), cbdata(it)))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


async def safe_edit(bot, chat_id, message_id, text, markup):
    try:
        await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)


async def try_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


# --- экраны ---

def feed_lines(tasks, links):
    now = datetime.now()
    lines = []
    for t in tasks:
        if t.deadline:
            marker = "🔥" if t.deadline < now else "⏰"
            line = f"{marker} <b>{esc(t.name)}</b> — {fmt_deadline(t.deadline)} ({deadline_note(t.deadline)})"
        else:
            line = f"• <b>{esc(t.name)}</b>"
        lines.append(line)
        tags = links.get(t.id, [])
        if tags:
            parts = []
            for link, tag in tags:
                part = f"{tag.emoji} {esc(tag.name)}"
                if link.description:
                    part += f" <i>({esc(link.description)})</i>"
                parts.append(part)
            lines.append("    " + ", ".join(parts))
    return lines


async def screen_menu(session=None):
    me = CURRENT_USER.get()
    lines = ["🗂 <b>Трекер задач</b>", ""]
    if session is not None and me is not None:
        tasks = await repo.feed_tasks(session, me.id)
        if tasks:
            shown = tasks[:FEED_LIMIT]
            links = await repo.links_map(session, [t.id for t in shown])
            lines.append(f"📌 <b>Мой фид</b> — {len(tasks)}")
            lines.extend(feed_lines(shown, links))
            if len(tasks) > len(shown):
                lines.append(f"<i>…и ещё {len(tasks) - len(shown)}</i>")
        else:
            lines.append("📌 <b>Мой фид</b> пуст.")
            lines.append(
                "<i>Сюда попадают задачи, где ты ответственный («В мой фид» в карточке), "
                "и задачи с продвигаемым тегом.</i>"
            )
    return "\n".join(lines), kb([
        [("📋 Задачи", "tl")],
        [("🏷 Теги", "gl")],
        [("👥 Доступ", "ul")],
    ])


async def screen_task_list(session, page, show_done):
    tasks, total, page, pages = await repo.list_tasks(session, page, show_done)
    emojis = await repo.emoji_map(session, [t.id for t in tasks])
    title = "✅ <b>Выполненные</b>" if show_done else "📋 <b>Задачи</b>"
    text = f"{title} — {total}" + ("" if tasks else "\n\nПока пусто.")
    now = datetime.now()
    rows = []
    for t in tasks:
        marker = ""
        if t.deadline:
            marker = "🔥" if not show_done and t.deadline < now else "⏰"
        label = (marker + emojis.get(t.id, "") + " " + t.name).strip()
        rows.append([(trunc(label), f"tc:{t.id}")])
    nav = nav_row("tlp", page, pages)
    if nav:
        rows.append(nav)
    rows.append([("➕ Новая задача", "tnew")])
    rows.append([("👁 Активные" if show_done else "👁 Выполненные", "tld")])
    rows.append([("🏠 Меню", "menu")])
    return text, kb(rows)


async def screen_task_card(session, task_id):
    task = await repo.get_task(session, task_id)
    if not task:
        return None
    links = await repo.task_links(session, task_id)
    assignees = await repo.task_assignees(session, task_id)
    lines = [f"📋 <b>{esc(task.name)}</b>" + (" ✅" if task.is_done else "")]
    if task.description:
        lines.append(f"<i>{esc(task.description)}</i>")
    if task.deadline:
        line = f"⏰ Дедлайн: <b>{fmt_deadline(task.deadline)}</b>"
        if not task.is_done:
            line += f" — {deadline_note(task.deadline)}"
        lines.append(line)
    if assignees:
        lines.append("👤 Ответственные: " + ", ".join(esc(user_label(u)) for u in assignees))
    me = CURRENT_USER.get()
    in_feed = me is not None and any(u.id == me.id for u in assignees)
    if links:
        lines.append("")
        lines.append("🏷 Теги:")
        for link, tag in links:
            item = f"• {tag.emoji} <b>{esc(tag.name)}</b>"
            if link.description:
                item += f" — <i>{esc(link.description)}</i>"
            lines.append(item)
    rows = [
        [("✏️ Название", f"ten:{task_id}"), ("📝 Описание", f"ted:{task_id}")],
        [("⏰ Дедлайн", f"tdl:{task_id}")],
        [(f"🏷 Теги ({len(links)})", f"tt:{task_id}"),
         (f"👤 Отв. ({len(assignees)})", f"ta:{task_id}")],
        [("➖ Из моего фида" if in_feed else "📌 В мой фид", f"tf:{task_id}")],
        [("↩️ Вернуть в работу" if task.is_done else "✅ Выполнена", f"tdone:{task_id}")],
        [("🗑 Удалить", f"tdel:{task_id}")],
        [("⬅️ К списку", "tl")],
    ]
    return "\n".join(lines), kb(rows)


async def screen_task_tags(session, task_id):
    task = await repo.get_task(session, task_id)
    if not task:
        return None
    links = await repo.task_links(session, task_id)
    text = f"🏷 Теги задачи «{esc(task.name)}»\n\n"
    text += "Тап по тегу — описание связки и открепление." if links else "Пока ни одного тега."
    rows = [
        [(
            trunc(f"{tag.emoji} {tag.name}" + (" · 📝" if link.description else "")),
            f"lnk:{task_id}:{tag.id}",
        )]
        for link, tag in links
    ]
    rows.append([("➕ Прикрепить", f"at:{task_id}")])
    rows.append([("🆕 Создать тег", f"ntg:{task_id}")])
    rows.append([("⬅️ Назад", f"tc:{task_id}")])
    return text, kb(rows)


async def screen_link(session, task_id, tag_id):
    pair = await repo.get_link(session, task_id, tag_id)
    if not pair:
        return None
    link, tag = pair
    text = f"{tag.emoji} <b>{esc(tag.name)}</b>"
    if tag.description:
        text += f"\n<i>{esc(tag.description)}</i>"
    text += "\n\n📝 Описание связки: " + (
        esc(link.description) if link.description else "<i>нет</i>"
    )
    first_row = [("✏️ Описание связки", f"lde:{task_id}:{tag_id}")]
    if link.description:
        first_row.append(("🧹 Очистить", f"ldc:{task_id}:{tag_id}"))
    rows = [
        first_row,
        [("➖ Открепить", f"det:{task_id}:{tag_id}")],
        [("⬅️ Назад", f"tt:{task_id}")],
    ]
    return text, kb(rows)


async def screen_attach(session, task_id, page):
    task = await repo.get_task(session, task_id)
    if not task:
        return None
    tags, total, page, pages = await repo.available_tags(session, task_id, page)
    text = f"➕ Прикрепить тег к «{esc(task.name)}»"
    if not tags:
        text += "\n\nСвободных тегов нет — создай новый."
    rows = grid(tags, lambda g: f"{g.emoji} {g.name}", lambda g: f"atd:{task_id}:{g.id}")
    nav = nav_row(f"atp:{task_id}", page, pages)
    if nav:
        rows.append(nav)
    rows.append([("🆕 Создать тег", f"ntg:{task_id}")])
    rows.append([("⬅️ Назад", f"tt:{task_id}")])
    return text, kb(rows)


async def screen_task_assignees(session, task_id):
    task = await repo.get_task(session, task_id)
    if not task:
        return None
    assignees = await repo.task_assignees(session, task_id)
    text = f"👤 Ответственные по «{esc(task.name)}»\n\n"
    text += "Тап по человеку — снять с задачи." if assignees else "Пока никого."
    rows = [[(trunc(user_label(u)), f"tad:{task_id}:{u.id}")] for u in assignees]
    rows.append([("➕ Назначить", f"taa:{task_id}")])
    rows.append([("⬅️ Назад", f"tc:{task_id}")])
    return text, kb(rows)


async def screen_assign(session, task_id, page):
    task = await repo.get_task(session, task_id)
    if not task:
        return None
    users, total, page, pages = await repo.available_assignees(session, task_id, page)
    text = f"➕ Назначить ответственного за «{esc(task.name)}»"
    if not users:
        text += "\n\nВсе допущенные уже назначены."
    rows = [[(trunc(user_label(u)), f"tas:{task_id}:{u.id}")] for u in users]
    nav = nav_row(f"tap:{task_id}", page, pages)
    if nav:
        rows.append(nav)
    rows.append([("⬅️ Назад", f"ta:{task_id}")])
    return text, kb(rows)


async def screen_tags_list(session, page):
    tags, total, page, pages = await repo.list_tags(session, page)
    text = f"🏷 <b>Теги</b> — {total}" + ("" if tags else "\n\nПока пусто.")
    rows = grid(tags, lambda g: f"{g.emoji} {g.name}", lambda g: f"gc:{g.id}")
    nav = nav_row("glp", page, pages)
    if nav:
        rows.append(nav)
    rows.append([("➕ Новый тег", "ntg:0")])
    rows.append([("🏠 Меню", "menu")])
    return text, kb(rows)


async def screen_tag_card(session, tag_id):
    tag = await repo.get_tag(session, tag_id)
    if not tag:
        return None
    used = await repo.tag_usage(session, tag_id)
    text = f"{tag.emoji} <b>{esc(tag.name)}</b>"
    if tag.description:
        text += f"\n<i>{esc(tag.description)}</i>"
    text += "\n\n❗ Описание связки при прикреплении: " + (
        "обязательно" if tag.needs_description else "не требуется"
    )
    text += "\n🚀 Продвигает задачи в фид всем: " + ("да" if tag.promote_feed else "нет")
    text += f"\n📎 Прикреплён к задачам: {used}"
    rows = [
        [("✏️ Название", f"gen:{tag_id}"), ("😀 Эмодзи", f"gee:{tag_id}")],
        [("📝 Описание", f"ged:{tag_id}")],
        [(
            "❗ Не требовать описание" if tag.needs_description else "❗ Требовать описание",
            f"gnd:{tag_id}",
        )],
        [(
            "🚀 Не продвигать в фид" if tag.promote_feed else "🚀 Продвигать в фид",
            f"gpf:{tag_id}",
        )],
        [("🗑 Удалить", f"gdel:{tag_id}")],
        [("⬅️ К списку", "gl")],
    ]
    return text, kb(rows)


async def screen_users(session, page):
    users, total, page, pages = await repo.list_allowed(session, page)
    knocks = await repo.count_requests(session)
    lines = [
        f"👥 <b>Допущенные</b> — {total}",
        "",
        "Владелец допущен всегда. Убрать из списка нельзя — только добавить.",
    ]
    if users:
        lines.append("")
        for u in users:
            who = f"@{esc(u.username)}" if u.username else f"<i>без ника</i> (id {u.telegram_id})"
            lines.append(f"• {who}" + (" ✅" if u.telegram_id else ""))
        lines.append("")
        lines.append("<i>✅ — человек уже писал боту</i>")
    rows = []
    nav = nav_row("ulp", page, pages)
    if nav:
        rows.append(nav)
    rows.append([("➕ Добавить", "uadd")])
    if knocks:
        rows.append([(f"🚪 Постучавшиеся ({knocks})", "kl")])
    rows.append([("🏠 Меню", "menu")])
    return "\n".join(lines), kb(rows)


async def screen_knocks(session, page):
    reqs, total, page, pages = await repo.list_requests(session, page)
    text = f"🚪 <b>Постучавшиеся</b> — {total}"
    if not reqs:
        text += "\n\nНикто не стучится."
    else:
        text += "\n\nТап по человеку — посмотреть и впустить."
    rows = [
        [(
            trunc(r.full_name + (f" (@{r.username})" if r.username else "")),
            f"kc:{r.id}",
        )]
        for r in reqs
    ]
    nav = nav_row("klp", page, pages)
    if nav:
        rows.append(nav)
    rows.append([("⬅️ Назад", "ul")])
    return text, kb(rows)


async def screen_knock_card(session, request_id):
    req = await repo.get_request(session, request_id)
    if not req:
        return None
    text = (
        f"🚪 <b>{esc(req.full_name)}</b>\n"
        + (f"@{esc(req.username)}" if req.username else "<i>без юзернейма</i>")
        + f"\nid: <code>{req.telegram_id}</code>"
        + f"\nПостучался: {req.created_at:%d.%m.%Y %H:%M} UTC"
    )
    rows = [
        [("✅ Впустить", f"kok:{request_id}")],
        [("⬅️ Назад", "kl")],
    ]
    return text, kb(rows)


async def build_target(session, data, target):
    """Собирает экран по строке-цели вида "tc:5"; при пропаже сущности
    (софт-делит из-под ног) откатывается на родительский экран."""
    p = (target or "menu").split(":")
    if p[0] == "tl":
        return await screen_task_list(session, data.get("tp", 0), data.get("td", 0))
    if p[0] == "tc":
        return await screen_task_card(session, int(p[1])) or await build_target(session, data, "tl")
    if p[0] == "tt":
        return await screen_task_tags(session, int(p[1])) or await build_target(session, data, "tl")
    if p[0] == "lnk":
        return await screen_link(session, int(p[1]), int(p[2])) or await build_target(session, data, f"tt:{p[1]}")
    if p[0] == "at":
        return await screen_attach(session, int(p[1]), data.get("ap", 0)) or await build_target(session, data, "tl")
    if p[0] == "ta":
        return await screen_task_assignees(session, int(p[1])) or await build_target(session, data, "tl")
    if p[0] == "taa":
        return await screen_assign(session, int(p[1]), data.get("sp", 0)) or await build_target(session, data, "tl")
    if p[0] == "gl":
        return await screen_tags_list(session, data.get("gp", 0))
    if p[0] == "gc":
        return await screen_tag_card(session, int(p[1])) or await build_target(session, data, "gl")
    if p[0] == "ul":
        return await screen_users(session, data.get("up", 0))
    if p[0] == "kl":
        return await screen_knocks(session, data.get("kp", 0))
    if p[0] == "kc":
        return await screen_knock_card(session, int(p[1])) or await build_target(session, data, "kl")
    return await screen_menu(session)


# --- помощники обработчиков ---

async def show(cb, session, state, target, toast=None):
    data = await state.get_data()
    text, markup = await build_target(session, data, target)
    await safe_edit(cb.bot, cb.message.chat.id, cb.message.message_id, text, markup)
    await cb.answer(toast)


async def prompt(cb, state, st, text, ret, extra=None):
    """Переводит экран в режим текстового ввода: ставит состояние и рисует
    приглашение с кнопкой отмены (и доп. кнопками вроде «Очистить»)."""
    rows = list(extra or [])
    rows.append([("❌ Отмена", "cxl")])
    await state.set_state(st)
    await state.update_data(ret=ret, smid=cb.message.message_id, p_text=text, p_kb=rows)
    await safe_edit(cb.bot, cb.message.chat.id, cb.message.message_id, text, kb(rows))
    await cb.answer()


async def prompt_msg(bot, chat_id, state, st, text, extra=None):
    """То же, что prompt, но из обработчика сообщения (следующий шаг цепочки)."""
    rows = list(extra or [])
    rows.append([("❌ Отмена", "cxl")])
    data = await state.get_data()
    await state.set_state(st)
    await state.update_data(p_text=text, p_kb=rows)
    await safe_edit(bot, chat_id, data["smid"], text, kb(rows))


async def reprompt(message, state, warn):
    data = await state.get_data()
    await try_delete(message)
    if not data.get("smid") or not data.get("p_text"):
        return
    await safe_edit(
        message.bot, message.chat.id, data["smid"],
        data["p_text"] + f"\n\n⚠️ {warn}", kb(data["p_kb"]),
    )


async def finish(message, state, session, target=None):
    """Завершает текстовый ввод: чистит состояние и возвращает экран."""
    data = await state.get_data()
    await state.set_state(None)
    await try_delete(message)
    text, markup = await build_target(session, data, target or data.get("ret", "menu"))
    if data.get("smid"):
        await safe_edit(message.bot, message.chat.id, data["smid"], text, markup)
    else:
        await message.answer(text, reply_markup=markup)

from aiogram.fsm.state import State, StatesGroup


class St(StatesGroup):
    task_new_name = State()
    task_name = State()
    task_desc = State()
    task_deadline = State()
    task_image_add = State()
    link_desc = State()
    tag_name = State()
    tag_emoji = State()
    tag_desc = State()
    tag_edit_name = State()
    tag_edit_emoji = State()
    tag_edit_desc = State()
    user_add = State()

from aiogram.fsm.state import State, StatesGroup


class ApplyStates(StatesGroup):
    ASK_NAME = State()
    ASK_EMAIL = State()
    ASK_PHONE = State()
    ASK_ORG = State()
    ASK_POSITION = State()
    ASK_COUNTRY_CITY = State()
    ASK_FORMAT = State()
    ASK_SECTION = State()
    ASK_TITLE = State()
    ASK_ABSTRACT = State()
    ASK_REFERENCES = State()
    ASK_COAUTHORS = State()
    ASK_FILE = State()
    ASK_CONSENT = State()
    CONFIRM = State()
    EDIT = State()


class FeedbackStates(StatesGroup):
    TYPE = State()
    TEXT = State()
    FILE = State()


class AdminStates(StatesGroup):
    COMMENT = State()
    BROADCAST = State()
    SET_DEADLINE = State()
    SET_EVENT = State()
    ADD_FAQ = State()
    FAQ_ANSWER = State()
    TICKET_REPLY = State()

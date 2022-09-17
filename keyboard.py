import sqlite3
from copy import deepcopy 
from telegram.inline.inlinekeyboardmarkup import InlineKeyboardMarkup, InlineKeyboardButton
from constants import *
from util import is_director
from itertools import chain

NAVIGATION_KEYBOARD = [InlineKeyboardButton("back",  callback_data="bm:back"),
                       InlineKeyboardButton("restart",  callback_data="bm:restart")]
CONTRACTS_KEYBOARD = [[InlineKeyboardButton(text=str(i), callback_data=f"bm:{i}") for i in range(1, 8)],
    [InlineKeyboardButton(s, callback_data=f"bm:{s}") for s in list(reversed(SUITS_UNICODE)) + ["NT"]],
    [InlineKeyboardButton(text=x, callback_data=f"bm:{x}") for x in ["x", "xx", "pass"]],
    [InlineKeyboardButton(s, callback_data=f"bm:{s}") for s in list("NESW")]]

ADJ_RESULTS = ['50/50', '60/40', '40/60' if CONFIG["scoring"] == "MPs" else ['A/A', 'A+/A-', 'A-/A+']]
ADJS = [InlineKeyboardButton(text=r, callback_data=f"bm:{r}") for r in ADJ_RESULTS]


def contracts_keyboard(update):
    lists = deepcopy(CONTRACTS_KEYBOARD)
    if is_director(update):
        lists.append(ADJS + NAVIGATION_KEYBOARD)
    else:
        lists.append(NAVIGATION_KEYBOARD)
    return InlineKeyboardMarkup(lists)


def lead_keyboard():
    rows = []

    for i, s in enumerate(SUITS_UNICODE):
        suit_cards = [InlineKeyboardButton(text, callback_data="bm:" + "shdc"[i] + text)
                      for text in [SUITS_UNICODE[i]] + CARDS_WITH_DIGIT_TEN]
        half = (len(suit_cards) + 1) // 2
        rows.extend([suit_cards[:half], suit_cards[half:]])
    rows.append(NAVIGATION_KEYBOARD)
    return InlineKeyboardMarkup(rows)


def pairs_keyboard(update, context, exclude=0, use_movement=True):
    pairs = context.bot_data["maxpair"]
    movement = context.bot_data["movement"] if use_movement else ''

    board = context.user_data["board"].number
    n_rounds = pairs - 1 + (pairs % 2)
    board_set = int(board) // n_rounds + 1
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(f"Select ns,ew from protocols where number={board}")
    denied = list(set(chain(*[c for c in cursor.fetchall()])))
    conn.close()
    allowed = [b for b in range(1, pairs + 1) if b not in denied and b != int(exclude)]
    rows = []
    if movement:
        allowed_tuples = [f"{ns} vs {ew}" for (ns, ew, bs) in movement if bs == board_set and ns in allowed and ew in allowed]
        for i in range(len(allowed_tuples) // 3):
            rows.append([InlineKeyboardButton(text=str(p), callback_data=f"bm:{p}")
                         for p in allowed_tuples[3 * i:3 + 3 * i]])
        if len(allowed_tuples) % 3:
            rows.append([InlineKeyboardButton(text=str(p), callback_data=f"bm:{p}")
                         for p in allowed_tuples[len(allowed_tuples) // 3 * 3:]])

        if not is_director(update):
            rows.append(NAVIGATION_KEYBOARD)
            return InlineKeyboardMarkup(rows)
    else:
        for i in range(len(allowed) // 7):
            rows.append([InlineKeyboardButton(text=str(p), callback_data=f"bm:{p}") for p in allowed[7 * i:7 + 7 * i]])
        if len(allowed) % 7:
            rows.append([InlineKeyboardButton(text=str(p), callback_data=f"bm:{p}") for p in allowed[len(allowed) // 7 * 7:]])
    rows.append(NAVIGATION_KEYBOARD)
    if is_director(update):
        rows.append([InlineKeyboardButton("Remove all records", callback_data=f"bm:rmall")])

    return InlineKeyboardMarkup(rows)


def results_keyboard(context):
    result = context.user_data["result"]
    level = int(result.text.split("Contract: ")[1][0])

    rows = [[InlineKeyboardButton(text="=", callback_data=f"bm:=")] +
            [InlineKeyboardButton(text=f"+{i}", callback_data=f"bm:+{i}") for i in range(1, 8 - level)],

            [InlineKeyboardButton(text=f"-{i}", callback_data=f"bm:-{i}") for i in range(1, level + 7)],
            NAVIGATION_KEYBOARD
            ]
    return InlineKeyboardMarkup(rows)


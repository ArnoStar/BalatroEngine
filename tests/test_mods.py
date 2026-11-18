"""Mods (balatro.mods): a run without mods is the original game; the PvP mode's rules."""

import math

import pytest

from balatro import Game, IllegalAction, make_mod
from balatro.mods import Mod
from balatro.mods.pvp import LOSS_DAMAGE, START_HP, PvP, damage, match_state

PLAY = {"cmd": "play", "cards": [0, 1, 2, 3, 4]}


def test_unknown_mod():
    with pytest.raises(ValueError):
        make_mod("nope")
    assert isinstance(make_mod({"key": "pvp"}), PvP)
    assert make_mod("pvp").spec() == {"key": "pvp"}


def test_a_mod_that_changes_nothing_changes_nothing():
    # every hook with its default: the same run as without mods
    plain = Game("TESTSEED").start_run()
    modded = Game("TESTSEED", mods=[Mod()]).start_run()
    for cmd in ({"cmd": "select_blind"}, PLAY, {"cmd": "discard", "cards": [0, 1]}, PLAY):
        plain.do(cmd)
        modded.do(cmd)
    assert plain.snapshot() == modded.snapshot()


def test_pvp_is_the_original_game_until_a_round_is_lost():
    plain = Game("TESTSEED").start_run()
    pvp = Game("TESTSEED", mods=["pvp"]).start_run()
    for cmd in ({"cmd": "select_blind"}, PLAY, {"cmd": "cheat", "win": True}, {"cmd": "cash_out"},
                {"cmd": "end_shop"}, {"cmd": "skip_blind"}, {"cmd": "select_blind"}, PLAY):
        plain.do(cmd)
        pvp.do(cmd)
    assert plain.snapshot() == pvp.snapshot()
    blinds = pvp.mod("pvp").blinds
    assert [(b["slot"], b["lost"], b["skipped"]) for b in blinds] == [("Small", False, False), ("Big", False, True)]


def test_a_lost_round_goes_on_to_the_shop():
    G = Game("TESTSEED", mods=["pvp"]).start_run()
    G.do({"cmd": "select_blind"})
    G.do(PLAY)
    G.do({"cmd": "forfeit_round"})
    assert G.STATE == G.STATES.ROUND_EVAL and not G.is_game_over()
    assert G.round_eval_rows[0] == ("blind", 0)  # no blind reward
    b = G.mod("pvp").blinds[-1]
    assert b["lost"] and b["chips"] == 56 and b["target"] == 300 and b["ante"] == 1
    G.do({"cmd": "cash_out"})
    assert G.in_shop()
    # without the mod, the same round is the end of the run
    plain = Game("TESTSEED").start_run()
    plain.do({"cmd": "select_blind"})
    for _ in range(4):
        plain.do(PLAY)
    assert plain.is_game_over()


def test_playing_every_hand_loses_the_round_without_ending_the_run():
    G = Game("TESTSEED", mods=["pvp"]).start_run()
    G.do({"cmd": "select_blind"})
    while G.STATE == G.STATES.SELECTING_HAND:
        G.do({"cmd": "play", "cards": [0]})
    assert G.STATE == G.STATES.ROUND_EVAL
    assert G.mod("pvp").blinds[-1]["lost"]


def test_forfeit_only_in_a_round():
    G = Game("TESTSEED", mods=["pvp"]).start_run()
    with pytest.raises(IllegalAction):
        G.do({"cmd": "forfeit_round"})
    with pytest.raises(IllegalAction):
        Game("TESTSEED").start_run().do({"cmd": "forfeit_round"})  # (not a command without the mod)


def test_timeout_commands_move_a_late_player_on():
    G = Game("TESTSEED", mods=["pvp"]).start_run()
    m = G.mod("pvp")
    assert m.timeout_command(G) is None  # the blind select: the match decides
    G.do({"cmd": "select_blind"})
    seen = []
    while (c := m.timeout_command(G)) is not None:
        seen.append(c["cmd"])
        G.do(c)
    assert seen == ["forfeit_round", "cash_out", "end_shop"]
    assert G.STATE == G.STATES.BLIND_SELECT


def test_clone_copies_the_mod():
    G = Game("TESTSEED", mods=["pvp"]).start_run()
    G.do({"cmd": "select_blind"})
    copy = G.clone()
    copy.do({"cmd": "forfeit_round"})
    assert len(copy.mod("pvp").blinds) == 1 and G.mod("pvp").blinds == []


def entry(chips: float = 0, ante: int = 4, lost: bool = False, skipped: bool = False) -> dict:
    return {"ante": ante, "chips": chips, "lost": lost, "skipped": skipped}


def test_damage():
    assert damage(entry(100), entry(400)) == 4  # 4 times fewer chips: 4 hit points
    assert damage(entry(100), entry(399)) == 3
    assert damage(entry(400), entry(100)) == 0
    assert damage(entry(100, ante=3), entry(10000, ante=3)) == 0  # the first three antes are safe
    assert damage(entry(100, ante=1, lost=True), entry(400)) == LOSS_DAMAGE  # but not from a lost round
    assert damage(entry(50, lost=True), entry(1e9)) == LOSS_DAMAGE  # (instead)
    assert damage(entry(skipped=True), entry(skipped=True)) == 0
    assert damage(entry(100), entry(math.inf)) >= START_HP
    assert damage(entry(math.inf), entry(math.inf)) == 0
    assert damage(entry(math.nan), entry(100)) == 0


def test_match_state():
    a = [entry(100, ante=1), entry(100), entry(100)]
    b = [entry(1000, ante=1), entry(1000), entry(50, lost=True), entry(10000)]
    s = match_state([a, b])
    assert s["hp"] == [40, 40] and not s["over"] and s["winner"] is None
    assert [r["damage"] for r in s["rounds"]] == [[0, 0], [10, 0], [0, 10]]
    # a knock-out ends it at that blind
    s = match_state([[entry(1)], [entry(1e6)]])
    assert s["over"] and s["winner"] == 1 and s["hp"] == [0, 50]
    # both at once: a draw when even
    s = match_state([[entry(1, lost=True)] * 5, [entry(1, lost=True)] * 5])
    assert s["over"] and s["winner"] is None and s["hp"] == [0, 0]
    # a run over for good (the game's own game over)
    s = match_state([[], []], eliminated=[False, True])
    assert s["over"] and s["winner"] == 0


# ------------------------------------------------------------------ coop
def coop() -> Game:
    return Game("TESTSEED", mods=["coop"]).start_run()


def test_coop_set_up():
    G = coop()
    m = G.mod("coop")
    assert len(G.playing_cards) == 104 and len(m.seats[1].deck.cards) == 52
    assert G.GAME.round_resets.discards == 8 and G.GAME.round_resets.hands == 4  # (the Red Deck's 4 discards, doubled)
    assert G.jokers.config.card_limit == 10 and m.limits == [5, 5]
    assert G.get_blind_amount(1) == 300 and G.get_blind_amount(4) == 10000 and G.get_blind_amount(8) == 170000


def test_coop_first_player_deals_as_the_original_game():
    G = coop()
    G.do({"cmd": "select_blind", "seat": 0})
    assert [c.config.card_key for c in G.hand.cards] == ["H_A", "H_K", "D_Q", "S_9", "C_9", "C_5", "D_5", "C_4"]


def test_coop_turns():
    G = coop()
    m = G.mod("coop")
    with pytest.raises(IllegalAction):
        G.do({"cmd": "select_blind", "seat": 1})
    G.do({"cmd": "select_blind", "seat": 0})
    first = [c.sort_id for c in G.hand.cards]
    with pytest.raises(IllegalAction):
        G.do({"cmd": "play", "cards": [0], "seat": 1})
    G.do({"cmd": "discard", "cards": [0], "seat": 0})  # (a discard keeps the turn)
    assert m.turn == 0 and G.GAME.current_round.discards_left == 7
    fb = G.start_feedback()
    G.do({"cmd": "play", "cards": [0, 1, 2, 3, 4], "seat": 0})
    G.stop_feedback()
    assert m.turn == 1 and G.hand is m.seats[1].hand and len(G.hand.cards) == 8
    assert not set(first) & {c.sort_id for c in G.hand.cards}  # (the other player's own cards)
    assert any(e["type"] == "turn" and e["seat"] == 1 for e in fb)
    assert G.GAME.current_round.hands_left == 3  # (hands are shared)
    G.do({"cmd": "play", "cards": [0], "seat": 1})
    assert m.turn == 0 and G.hand is m.seats[0].hand and len(G.hand.cards) == 8


def test_coop_round_end_and_next_starter():
    G = coop()
    m = G.mod("coop")
    G.do({"cmd": "select_blind", "seat": 0})
    G.do({"cmd": "play", "cards": [0], "seat": 0})
    G.do({"cmd": "cheat", "win": True, "seat": 1})  # (player 2's turn: the blind is beaten)
    assert G.STATE == G.STATES.ROUND_EVAL
    assert all(not s.hand.cards and not s.discard.cards and len(s.deck.cards) == 52 for s in m.seats)
    G.do({"cmd": "cash_out", "seat": 0})
    G.do({"cmd": "end_shop", "seat": 0})
    assert G.in_shop()  # (the other player is still shopping)
    G.do({"cmd": "end_shop", "seat": 1})
    assert G.STATE == G.STATES.BLIND_SELECT
    assert m.turn == 1  # (player 1 played the last hand: player 2 starts the next round)
    G.do({"cmd": "select_blind", "seat": 1})
    assert G.hand is m.seats[1].hand and len(G.hand.cards) == 8


def test_coop_jokers_are_each_players():
    G = coop()
    m = G.mod("coop")
    G.do({"cmd": "add_joker", "key": "j_joker", "seat": 1})
    G.do({"cmd": "add_joker", "key": "j_juggler", "seat": 0})
    assert [(c.config.center.key, m.owner(c)) for c in G.jokers.cards] == [("j_juggler", 0), ("j_joker", 1)]
    assert all(s.hand.config.card_limit == 9 for s in m.seats)  # (the hand's size is both players')
    with pytest.raises(IllegalAction):
        G.do({"cmd": "sell", "area": "jokers", "index": 1, "seat": 0})
    G.do({"cmd": "sell", "area": "jokers", "index": 1, "seat": 1})
    assert [c.config.center.key for c in G.jokers.cards] == ["j_juggler"]
    for _ in range(5):
        G.do({"cmd": "add_joker", "key": "j_joker", "seat": 0})
    assert [m.owner(c) for c in G.jokers.cards] == [0, 0, 0, 0, 0, 1]  # (player 1's half is full)
    m.viewer = 1
    assert all(a["index"] == 5 for a in G.legal_actions() if a["cmd"] == "sell" and a["area"] == "jokers")


def test_coop_shop():
    G = coop()
    m = G.mod("coop")
    G.do({"cmd": "select_blind", "seat": 0})
    G.do({"cmd": "cheat", "win": True, "dollars": 100, "seat": 0})
    G.do({"cmd": "cash_out", "seat": 1})
    joker = next(i for i, c in enumerate(G.shop_jokers.cards) if c.ability.set == "Joker")
    G.do({"cmd": "buy", "area": "shop_jokers", "index": joker, "seat": 1})
    assert [m.owner(c) for c in G.jokers.cards] == [1]
    assert G.hand is m.seats[m.turn].hand  # (back to the turn's areas after a player's purchase)
    # a pack is its opener's (an Arcana or Spectral pack deals their cards)
    G.do({"cmd": "buy", "area": "shop_booster", "index": 0, "seat": 1})
    assert G.in_pack() and m.pack_seat == 1
    with pytest.raises(IllegalAction):
        G.do({"cmd": "skip_pack", "seat": 0})
    G.do({"cmd": "skip_pack", "seat": 1})
    assert G.in_shop() and m.pack_seat is None and G.hand is m.seats[m.turn].hand

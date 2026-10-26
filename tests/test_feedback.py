"""Front-end helpers: the feedback log, the hand preview, sprite data.
None of them may change the run."""

import random

from balatro import Game, IllegalAction, STATES
from balatro.data import sprites

from test_api import concrete, play_random


def test_feedback_does_not_change_the_run():
    G1, trace = play_random("FEEDBACK", steps=80, rnd_seed=3)
    G2 = Game("FEEDBACK").start_run()
    for cmd in trace:
        G2.start_feedback()
        G2.do(cmd)
        G2.stop_feedback()
    assert G2.snapshot() == G1.snapshot()


def test_feedback_of_a_played_hand():
    G = Game("TESTSEED").start_run()
    G.act_select_blind()
    played = [c.sort_id for c in G.hand.cards[:5]]
    fb = G.start_feedback()
    G.act_play([0, 1, 2, 3, 4])
    G.stop_feedback()
    kinds = [e["type"] for e in fb]
    assert kinds.count("card_moved") >= 10  # to the play area, to the discard pile, the new draw
    # (selecting the cards one by one updates the hand panel, as in the game)
    names = [e["handname"] for e in fb if e["type"] == "hand" and e.get("handname")]
    assert names[-1] == "Pair"
    texts = [e for e in fb if e["type"] == "card_text"]
    assert texts and all(e["card"] in played for e in texts) and all(e["effect"] == "chips" for e in texts)
    assert fb[-1]["t"] >= fb[0]["t"] >= 0
    scored = [e for e in fb if e["type"] == "hand_scored"]
    assert len(scored) == 1 and scored[0]["score"] == scored[0]["round_score"] == G.GAME.chips == 56
    assert all(sorted(e) == sorted(set(e)) for e in fb)


def test_preview_hand_matches_the_game_and_changes_nothing():
    rnd = random.Random(5)
    for seed in ("TESTSEED", "PREVIEW1", "PREVIEW2"):
        G = Game(seed).start_run()
        G.act_select_blind()
        for _ in range(4):
            if G.STATE != STATES.SELECTING_HAND:
                break
            n = len(G.hand.cards)
            idxs = sorted(rnd.sample(range(n), rnd.randint(1, min(5, n))))
            before = G.snapshot()
            p = G.preview_hand(idxs)
            assert G.snapshot() == before
            assert p["selected"] == idxs and set(p["scoring"]) <= set(idxs)
            G.act_play(idxs)
            assert G.last_score.hand == p["hand"]


def test_preview_hand_rejects_bad_selections():
    G = Game("TESTSEED").start_run()
    try:
        G.preview_hand([0])
        raise AssertionError("preview outside a round")
    except IllegalAction:
        pass
    G.act_select_blind()
    for bad in ([0, 0], [99], [0, 1, 2, 3, 4, 5]):
        try:
            G.preview_hand(bad)
            raise AssertionError(bad)
        except IllegalAction:
            pass
    assert G.preview_hand([])["hand"] is None


def test_round_eval_rows_add_up():
    rnd = random.Random(1)
    G = Game("ROWS1234").start_run()
    G.act_select_blind()
    while G.STATE == STATES.SELECTING_HAND:
        G.do({"cmd": "cheat", "win": True})
    assert G.STATE == STATES.ROUND_EVAL
    total = sum(v for _, v in G.round_eval_rows)
    dollars = G.GAME.dollars
    G.act_cash_out()
    assert G.GAME.dollars == dollars + total
    assert concrete(G, {"cmd": "end_shop"}, rnd) == {"cmd": "end_shop"}


def test_sprites_cover_every_key():
    s = sprites()
    G = Game("X")
    assert set(s["centers"]) == set(G.P_CENTERS)
    assert set(s["cards"]) == set(G.P_CARDS)
    assert set(s["blinds"]) == set(G.P_BLINDS) and set(s["tags"]) == set(G.P_TAGS)
    for group in ("centers", "cards", "blinds", "tags", "seals", "stakes", "stickers"):
        for key, v in s[group].items():
            assert v["atlas"] in s["atlases"] and v["pos"] is not None, (group, key)


def test_feedback_names_the_joker_that_scores_a_card():
    # juice_card: the joker of a scored card's suit wiggles as its +4 mult shows on the card
    G = Game("TESTSEED").start_run()
    for key in ("j_greedy_joker", "j_lusty_joker", "j_wrathful_joker", "j_gluttenous_joker"):
        G.do({"cmd": "add_joker", "key": key})
    jokers = {j.sort_id for j in G.jokers.cards}
    G.act_select_blind()
    played = G.hand.cards[0].sort_id
    fb = G.start_feedback()
    G.act_play([0])
    G.stop_feedback()
    juiced = [i for i, e in enumerate(fb) if e["type"] == "card_juiced"]
    assert len(juiced) == 1 and fb[juiced[0]]["card"] in jokers
    mult = next(e for e in fb[juiced[0]:] if e["type"] == "card_text" and e["effect"] == "mult")
    assert mult["card"] == played and mult["amount"] == 3

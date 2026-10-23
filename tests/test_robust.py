"""Random runs with every kind of card injected: no exceptions, no lost cards."""

import random

import pytest

from balatro import Game
from balatro.oracle.fuzz import DECKS, SEED_CHARS, candidates, choose


def check_invariants(G):
    if G.is_game_over():
        return
    areas = [G.deck, G.hand, G.discard, G.play]
    cards = [c for a in areas for c in a.cards if c.ability.set in ("Default", "Enhanced")]
    assert len({id(c) for c in cards}) == len(cards), "a card is in two areas"
    assert {id(c) for c in cards} == {id(c) for c in G.playing_cards}, "playing cards lost or duplicated"
    for a in areas + [G.jokers, G.consumeables]:
        for c in a.cards:
            assert c.area is a and not c.removed


def random_run(rnd):
    g0 = Game("X")
    seed = "".join(rnd.choice(SEED_CHARS) for _ in range(8))
    challenge = rnd.choice([c.id for c in g0.data.challenges]) if rnd.random() < 0.15 else None
    deck = g0.data.center_by_name(rnd.choice(DECKS)).key
    G = Game(seed, deck=deck, stake=1 if challenge else rnd.randint(1, 8), challenge=challenge).start_run()
    items = [v.key for v in G.P_CENTER_POOLS["Joker"]]
    items += [v.key for p in ("Tarot", "Planet", "Spectral") for v in G.P_CENTER_POOLS[p]] + ["c_soul", "c_black_hole"]
    vouchers = [v.key for v in G.P_CENTER_POOLS["Voucher"]]
    bosses = [k for k, v in G.P_BLINDS.items() if v.boss]
    for _ in range(150):
        if G.is_game_over() or G.GAME.round_resets.ante > 12:
            break
        r = rnd.random()
        if G.STATE == G.STATES.SHOP and r < 0.25:
            cmd = {"cmd": "cheat", "dollars": G.GAME.dollars + rnd.randint(10, 80)}
        elif r < 0.12:
            cmd = {"cmd": "add_joker", "key": rnd.choice(items)}
        elif r < 0.14:
            cmd = {"cmd": "add_voucher", "key": rnd.choice(vouchers)}
        elif r < 0.16:
            cmd = {"cmd": "add_tag", "key": rnd.choice(sorted(G.P_TAGS))}
        elif G.STATE == G.STATES.BLIND_SELECT and r < 0.25:
            cmd = {"cmd": "cheat", "boss": rnd.choice(bosses)}
        elif G.STATE == G.STATES.SELECTING_HAND and G.GAME.current_round.hands_left <= 1 and r < 0.8:
            cmd = {"cmd": "cheat", "win": True}
        else:
            cmd = choose(rnd, candidates(G, rnd))
        G.do(cmd)
        check_invariants(G)


@pytest.mark.parametrize("seed", range(8))
def test_random_runs(seed):
    random_run(random.Random(seed))

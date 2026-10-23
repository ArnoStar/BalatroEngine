"""The library API: legal actions, cloning, determinism."""

import random

import pytest

from balatro import Game, IllegalAction, STATES


def concrete(G, a, rnd):
    """Turn a legal_actions() entry into a full command."""
    c = dict(a)
    n = len(G.hand.cards) if G.hand is not None else 0
    if c["cmd"] in ("play", "discard"):
        c.pop("n")
        c["cards"] = sorted(rnd.sample(range(n), rnd.randint(1, min(5, n))))
    elif c["cmd"] in ("use", "pick") and "max" in c:
        lo, hi = c.pop("min"), c.pop("max")
        if n < lo:
            return None
        c["targets"] = sorted(rnd.sample(range(n), rnd.randint(lo, min(hi, n))))
    return c


def play_random(seed, steps=60, rnd_seed=0, **kw):
    rnd = random.Random(rnd_seed)
    G = Game(seed, **kw).start_run()
    trace = []
    for _ in range(steps):
        if G.is_game_over():
            break
        acts = G.legal_actions()
        assert acts, f"no legal action in state {G.STATE}"
        before = G.snapshot()
        assert G.snapshot() == before, "legal_actions() changed the game"
        cmd = None
        for _ in range(10):
            cmd = concrete(G, rnd.choice(acts), rnd)
            if cmd is None:
                continue
            try:
                G.do(cmd)
                break
            except IllegalAction:
                # targets / cards chosen at random may not fit this consumable
                assert cmd["cmd"] in ("use", "pick"), cmd
                cmd = None
        if cmd is not None:
            trace.append(cmd)
    return G, trace


def test_legal_actions_are_playable():
    for i, seed in enumerate(("TESTSEED", "ABCD1234", "QWERTY12")):
        play_random(seed, steps=60, rnd_seed=i)


def test_same_actions_same_run():
    G1, trace = play_random("ZZZZ9999", steps=50, rnd_seed=7)
    G2 = Game("ZZZZ9999").start_run()
    for cmd in trace:
        G2.do(cmd)
    assert G1.snapshot() == G2.snapshot()


def test_clone_is_independent():
    G = Game("TESTSEED").start_run()
    G.act_select_blind()
    before = G.snapshot()
    H = G.clone()
    H.act_play([0, 1, 2, 3, 4])
    assert G.snapshot() == before
    G.act_play([0, 1, 2, 3, 4])
    assert G.snapshot() == H.snapshot()


def test_illegal_actions_are_rejected():
    G = Game("TESTSEED").start_run()
    with pytest.raises(IllegalAction):
        G.act_play([0])
    with pytest.raises(IllegalAction):
        G.act_cash_out()
    G.act_select_blind()
    with pytest.raises(IllegalAction):
        G.act_play([0, 1, 2, 3, 4, 5])
    with pytest.raises(IllegalAction):
        G.act_play([99])
    assert G.STATE == STATES.SELECTING_HAND


def test_game_speed_changes_only_timing():
    # the first hand and score of a plain run don't depend on the speed setting
    out = []
    for speed in (0.5, 1, 2, 4):
        G = Game("TESTSEED", game_speed=speed).start_run()
        G.act_select_blind()
        G.act_play([0, 1, 2, 3, 4])
        out.append((G.GAME.chips, [c.config.card_key for c in G.hand.cards]))
    assert all(o == out[0] for o in out)


@pytest.mark.parametrize("seed,deck", [("TESTSEED", "red"), ("8BALLZ22", "plasma"), ("MAGIC123", "magic"),
                                       ("GHOSTLY1", "ghost")])
def test_fast_forward_is_exact(seed, deck):
    """Skipping idle frames must give exactly the frame-by-frame run."""
    G1, t1 = play_random(seed, steps=80, rnd_seed=3, deck=deck, fast_forward=False)
    G2, t2 = play_random(seed, steps=80, rnd_seed=3, deck=deck, fast_forward=True)
    assert t1 == t2
    assert G1.snapshot() == G2.snapshot()
    assert (G1.FRAMES_MOVE, G1.TIMERS) == (G2.FRAMES_MOVE, G2.TIMERS)


def test_clone_with_pending_events():
    """A clone taken mid-animation finishes on its own objects, like the original."""
    G = Game("TESTSEED").start_run()
    G.act_select_blind()
    G._select([0, 1, 2, 3, 4])
    G.play_cards_from_highlighted()
    for _ in range(120):
        G.frame()
    assert G.E_MANAGER.queue
    H = G.clone()
    G.settle()
    H.settle()
    assert G.snapshot() == H.snapshot()
    K = Game("TESTSEED").start_run()
    K.act_select_blind()
    K.act_play([0, 1, 2, 3, 4])
    assert K.snapshot() == G.snapshot()

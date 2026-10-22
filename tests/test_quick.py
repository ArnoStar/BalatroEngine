"""balatro.quick must agree with the full engine."""

import random

import pytest

from balatro import Game
from balatro.quick import Ante1
from balatro.rng import SEED_ALPHABET

DECKS = ["b_red", "b_blue", "b_yellow", "b_green", "b_black", "b_magic", "b_nebula", "b_ghost", "b_abandoned",
         "b_checkered", "b_zodiac", "b_painted", "b_anaglyph", "b_plasma", "b_erratic"]


def seeds(n, rng_seed=1234):
    r = random.Random(rng_seed)
    return ["".join(r.choice(SEED_ALPHABET) for _ in range(8)) for _ in range(n)]


@pytest.mark.parametrize("deck", DECKS)
def test_quick_matches_engine(deck):
    for seed in seeds(25, hash(deck) & 0xFFFF):
        q = Ante1(seed, deck)
        G = Game(seed, deck=deck).start_run()
        rr = G.GAME.round_resets
        assert q.tags == (rr.blind_tags.Small, rr.blind_tags.Big), seed
        assert q.boss == rr.blind_choices.Boss, seed
        assert q.voucher == G.GAME.current_round.voucher, seed
        assert q.starting_deck() == [c.config.card_key for c in sorted(G.playing_cards, key=lambda c: c.sort_id)], seed
        G.select_blind()
        assert sorted(q.first_hand()) == sorted(c.config.card_key for c in G.hand.cards), seed

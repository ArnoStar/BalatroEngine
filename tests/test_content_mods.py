"""Content mods (balatro.mods.content): packages of data, the example mods, creative mode."""

import copy

import pytest

from balatro import Game, IllegalAction
from balatro.data import load
from balatro.mods import examples, make_mod
from balatro.mods import expr as E
from balatro.mods.content import ContentMod, ModError
from balatro.mods.spec import validate

EX = examples()
FRUIT, WILD, CREATIVE = EX["fruit_stand"], EX["wild_rules"], EX["creative"]


def game(*packages, seed="MODTEST", deck="b_red", creative=True):
    return Game(seed, deck=deck, mods=[*packages, *([CREATIVE] if creative else [])]).start_run()


def cr(G, **cmd):
    G.do({"cmd": "creative", **cmd})


def hand_of(G, *cards):
    """Put these cards in the hand (creative), returning their indices."""
    before = {id(c) for c in G.hand.cards}
    for rank, suit in cards:
        cr(G, op="add_card", rank=rank, suit=suit, to="hand")
    return [i for i, c in enumerate(G.hand.cards) if id(c) not in before]


def minimal(**extra):
    return {"format": 1, "id": "tiny", "name": "Tiny", "version": "1.0.0", **extra}


# ------------------------------------------------------------------ the format
def test_the_examples_are_valid():
    assert set(EX) == {"fruit_stand", "wild_rules", "creative"}
    for pkg in EX.values():
        assert validate(pkg) == []


def test_a_package_without_its_images_plays():
    from balatro.mods.spec import logic
    assert "assets" not in logic(FRUIT) and validate(logic(FRUIT)) == []
    G = Game("MODTEST", mods=[logic(FRUIT)]).start_run()
    assert "j_fruit_stand_cherry_seven" in G.P_CENTERS
    broken = copy.deepcopy(FRUIT)
    del broken["assets"]["orchard"]
    assert validate(broken) == ["jokers[2].sprite: no asset named 'orchard' in the package's assets"]


def test_errors_name_the_place():
    bad = minimal(jokers=[{"key": "x", "name": "X", "config": {"mult": 1}, "effects": [
        {"on": "card_scored", "if": "cardd.rank == 7", "do": [{"mult": "self.mlt"}]},
        {"on": "round_end", "do": [{"chips": 5}]},
        {"on": "nope", "do": []},
    ]}])
    errors = validate(bad)
    assert "jokers[0].effects[0].if: unknown name 'cardd'" in errors
    assert any(e.startswith("jokers[0].effects[0].do[0].mult: 'self' has no field 'mlt'") for e in errors)
    assert any(e.startswith("jokers[0].effects[1].do[0].chips: only scores in") for e in errors)
    assert any(e.startswith("jokers[0].effects[2].on: must be one of") for e in errors)
    with pytest.raises(ModError) as e:
        make_mod(bad)
    assert e.value.mod_id == "tiny" and len(e.value.errors) == len(errors)


def test_what_the_game_only_reads_draws_no_random_number():
    # a description's values, a blind's debuff and a consumable's can_use run where the game only looks
    errors = validate(minimal(jokers=[{"key": "x", "name": "X", "vars": ["chance(1, 2)"]}]))
    assert any("draws a random number" in e for e in errors)
    errors = validate(minimal(blinds=[{"key": "b", "name": "B", "debuff_card": "random(1, 2) == 1"}]))
    assert any("draws a random number" in e for e in errors)


def test_package_basics():
    assert validate(minimal()) == []
    assert any(e.startswith("id:") for e in validate(minimal(id="Bad Id")))
    assert any(e.startswith("id:") for e in validate(minimal(id="pvp")))
    assert any(e.startswith("version:") for e in validate(minimal(version="1.0")))
    assert any(e.startswith("format:") for e in validate(minimal(format=2)))
    assert any("unknown field 'jokes'" in e for e in validate(minimal(jokes=[])))
    assert any(e.startswith("assets.x:") for e in validate(minimal(assets={"x": "data:image/png;base64,AAAA"})))


def test_references_must_exist_when_played():
    pkg = minimal(decks=[{"key": "d", "name": "D", "jokers": ["j_nowhere"]}])
    assert validate(pkg) == []  # (another mod of the run may bring it)
    with pytest.raises(ModError, match="j_nowhere"):
        Game("A", mods=[pkg])


def test_two_mods_with_one_id():
    with pytest.raises(ModError, match="twice"):
        Game("A", mods=[FRUIT, copy.deepcopy(FRUIT)])


def test_expressions():
    env = E.Env()
    ev = lambda s: E.evaluate(E.parse(s), env)  # noqa: E731
    assert ev("1 + 2 * 3") == 7 and ev("(1 + 2) * 3") == 9 and ev("2 ^ 3 ^ 2") == 512
    assert ev("-7 % 3") == 2 and ev("7 / 2") == 3.5 and ev("1 / 0") == float("inf")
    assert ev("nil or 5") == 5 and ev("0 and 3") == 3 and ev("false or nil") is None  # (Lua: 0 is true)
    assert ev("not 0") is False and ev("1 == 1.0") is True and ev("'a' == 'a'") is True and ev("1 < 'a'") is None
    assert ev("if(1 > 2, 'yes', 'no')") == "no" and ev("max(1, 5, 3)") == 5 and ev("clamp(9, 0, 4)") == 4
    assert ev("1 + nil") is None and ev("floor(2.7)") == 2 and ev("round(2.5)") == 3
    for bad in ("1 +", "a..b", "1 < 2 < 3", "f(", "'open", "#"):
        with pytest.raises(E.ExprError):
            E.parse(bad)


# ------------------------------------------------------------------ the original game stays
def test_the_games_tables_stay_the_originals():
    d = load()
    n = len(d.P_CENTERS)
    G = game(FRUIT, WILD)
    assert "j_fruit_stand_cherry_seven" in G.P_CENTERS and "j_fruit_stand_cherry_seven" not in d.P_CENTERS
    assert len(d.P_CENTERS) == n and G.data is not d
    assert Game("MODTEST").start_run().data is d


def test_a_modded_run_unlocks_nothing():
    from balatro import Profile
    G = Game("MODTEST", profile=Profile(), seeded=False, mods=[FRUIT]).start_run()
    assert not G.unlocking


# ------------------------------------------------------------------ jokers
def score_with(joker, cards, discard=None, seed="MODTEST"):
    G = game(FRUIT, seed=seed)
    if joker:
        cr(G, op="add", key=joker)
    G.do({"cmd": "select_blind"})
    if discard:
        G.do({"cmd": "discard", "cards": hand_of(G, *discard)})
    G.do({"cmd": "play", "cards": hand_of(G, *cards)})
    return G


def test_cherry_seven():
    sevens = [("7", "Hearts"), ("7", "Spades")]
    assert score_with(None, sevens).last_score.score == (10 + 14) * 2
    assert score_with("j_fruit_stand_cherry_seven", sevens).last_score.score == (10 + 14) * (2 + 7 + 7)


def test_banana_bunch():
    G = score_with("j_fruit_stand_banana_bunch", [("7", "Hearts"), ("7", "Spades")])
    assert G.last_score.score == (10 + 14) * 2 * 3


def test_orchard_grows_with_discarded_hearts():
    G = score_with("j_fruit_stand_orchard", [("7", "Hearts"), ("7", "Spades")],
                   discard=[("2", "Hearts"), ("3", "Hearts"), ("4", "Clubs")])
    assert G.jokers.cards[0].ability.extra.chips == 8
    assert G.last_score.score == (10 + 14 + 8) * 2


def test_fruit_salad_retriggers_four_suits():
    four = [("Ace", "Hearts"), ("Ace", "Spades"), ("Ace", "Clubs"), ("Ace", "Diamonds")]
    assert score_with(None, four).last_score.score == (60 + 44) * 7
    assert score_with("j_fruit_stand_fruit_salad", four).last_score.score == (60 + 88) * 7


def test_market_stall_slot_and_cash_out():
    G = game(FRUIT)
    limit = G.consumeables.config.card_limit
    cr(G, op="add", key="j_fruit_stand_market_stall")
    assert G.consumeables.config.card_limit == limit + 1
    cr(G, op="add", key="c_pluto")
    cr(G, op="add", key="c_mars")
    G.do({"cmd": "select_blind"})
    cr(G, op="win")
    assert ("joker:j_fruit_stand_market_stall", 4) in G.round_eval_rows
    G.do({"cmd": "cash_out"})
    G.do({"cmd": "sell", "area": "jokers", "index": 0})
    assert G.consumeables.config.card_limit == limit


def test_seed_packet_makes_a_planet_every_third_blind():
    G = game(FRUIT)
    cr(G, op="add", key="j_fruit_stand_seed_packet")
    made = []
    for _ in range(3):
        G.do({"cmd": "select_blind"})
        made.append([c.ability.set for c in G.consumeables.cards])
        cr(G, op="win")
        G.do({"cmd": "cash_out"})
        G.do({"cmd": "end_shop"})
    assert made == [[], [], ["Planet"]]
    assert G.jokers.cards[0].ability.extra.rounds == 0


def test_a_mod_joker_shows_its_messages():
    G = game(FRUIT)
    cr(G, op="add", key="j_fruit_stand_orchard")
    G.do({"cmd": "select_blind"})
    idx = hand_of(G, ("2", "Hearts"))
    G.start_feedback()
    G.do({"cmd": "discard", "cards": idx})
    fb = G.stop_feedback()
    assert any(e["type"] == "card_text" and e.get("message") == "k_upgrade_ex" for e in fb)


def test_mod_jokers_come_in_the_shop():
    G = Game("MODTEST", mods=[FRUIT])
    pool, _ = G.get_current_pool("Joker", 0)  # (commons)
    assert "j_fruit_stand_cherry_seven" in pool and "j_fruit_stand_orchard" in pool


# ------------------------------------------------------------------ decks, blinds, consumables, vouchers
def test_gardeners_deck():
    G = game(WILD, deck="b_wild_rules_gardener")
    assert len(G.playing_cards) == 40 and all(c.base.value not in ("2", "3", "4") for c in G.playing_cards)
    assert G.GAME.dollars == 4 + 10 and G.GAME.used_vouchers.v_seed_money


def test_duet_deck():
    G = game(WILD, deck="b_wild_rules_duet")
    assert len(G.playing_cards) == 26 and {c.base.suit for c in G.playing_cards} == {"Hearts", "Spades"}
    assert G.hand.config.card_limit == 9 and G.GAME.round_resets.hands == 3


def test_the_house_rule():
    assert game(WILD).GAME.interest_cap == 25 + 25


def boss(G, key):
    cr(G, op="boss", key=key)
    for _ in range(2):
        G.do({"cmd": "select_blind"})
        cr(G, op="win")
        G.do({"cmd": "cash_out"})
        G.do({"cmd": "end_shop"})
    G.do({"cmd": "select_blind"})
    assert G.GAME.blind.config.blind.key == key


def test_the_toll():
    G = game(WILD)
    boss(G, "bl_wild_rules_toll")
    two = hand_of(G, ("King", "Hearts"), ("King", "Spades"))
    assert G.preview_hand(two)["not_allowed"]
    cr(G, op="set", what="money", value=10)
    G.do({"cmd": "play", "cards": hand_of(G, ("Queen", "Hearts"), ("Queen", "Spades"), ("Queen", "Clubs"))})
    assert G.GAME.dollars == 9


def test_the_rot_and_the_drought():
    G = game(WILD)
    boss(G, "bl_wild_rules_rot")
    cr(G, op="add_card", rank="Ace", suit="Hearts", enhancement="m_gold", to="hand")
    assert [c.debuff for c in G.hand.cards if c.ability.set == "Enhanced"] == [True]
    G = game(WILD)
    size = G.hand.config.card_limit
    boss(G, "bl_wild_rules_drought")
    assert G.hand.config.card_limit == size - 1
    assert G.GAME.current_round.discards_left == G.GAME.round_resets.discards - 1
    cr(G, op="win")
    assert G.hand.config.card_limit == size


def test_the_gardener_and_the_harvest():
    G = game(WILD)
    G.do({"cmd": "select_blind"})
    cr(G, op="add", key="c_wild_rules_gardener")
    use = [a for a in G.legal_actions() if a["cmd"] == "use"]
    assert use == [{"cmd": "use", "index": 0, "min": 1, "max": 2}]
    G.do({"cmd": "use", "index": 0, "targets": [0, 1]})
    assert [c.config.center.key for c in G.hand.cards[:2]] == ["m_lucky", "m_lucky"]
    cr(G, op="add", key="c_wild_rules_harvest")
    assert not any(a["cmd"] == "use" for a in G.legal_actions())  # (no Gold Card yet)
    cr(G, op="add_card", rank="Ace", suit="Hearts", enhancement="m_gold", to="deck")
    money = G.GAME.dollars
    G.do({"cmd": "use", "index": 0})
    assert G.GAME.dollars == money + 4


def test_graft_and_pomona():
    G = game(WILD)
    G.do({"cmd": "select_blind"})
    size = G.hand.config.card_limit
    cr(G, op="add", key="c_wild_rules_graft")
    G.do({"cmd": "use", "index": 0, "targets": [2]})
    assert G.hand.config.card_limit == size - 1
    assert sum(1 for c in G.hand.cards if c.edition and c.edition.polychrome) == 1
    cr(G, op="add", key="c_wild_rules_pomona")
    G.do({"cmd": "use", "index": 0})
    assert G.GAME.hands["Two Pair"].level == 2


def test_vouchers():
    G = game(WILD)
    pool, _ = G.get_current_pool("Voucher")
    assert "v_wild_rules_greenhouse" in pool and "v_wild_rules_hothouse" not in pool
    size = G.hand.config.card_limit
    cr(G, op="add", key="v_wild_rules_greenhouse")
    assert G.hand.config.card_limit == size + 1
    pool, _ = G.get_current_pool("Voucher")
    assert "v_wild_rules_hothouse" in pool


# ------------------------------------------------------------------ creative mode
def test_creative_changes_go_through_the_game():
    G = game(FRUIT)
    cr(G, op="set", what="money", value=123)
    cr(G, op="set", what="joker_slots", value=7)
    cr(G, op="level", hand="Flush", value=5)
    cr(G, op="add", key="j_blueprint", edition="negative")
    cr(G, op="add", key="tag_double")
    cr(G, op="add", key="v_grabber")
    G.do({"cmd": "select_blind"})
    cr(G, op="set", what="hands", value=9)
    cr(G, op="set", what="hand_size", value=10)
    cr(G, op="edit", area="hand", index=0, enhancement="m_steel", seal="Red", edition="foil")
    cr(G, op="edit", area="jokers", index=0, edition="none", eternal=True)
    n = len(G.hand.cards)
    cr(G, op="remove", area="hand", index=1)
    GAME = G.GAME
    assert GAME.dollars == 123 and G.jokers.config.card_limit == 7 and GAME.hands.Flush.level == 5
    assert G.jokers.cards[0].key == "j_blueprint" and not G.jokers.cards[0].edition
    assert G.jokers.cards[0].ability.eternal and [t.key for t in GAME.tags] == ["tag_double"]
    assert GAME.used_vouchers.v_grabber and GAME.current_round.hands_left == 9
    assert G.hand.config.card_limit == 10 and len(G.hand.cards) == n - 1
    c = next(c for c in G.hand.cards if c.config.center.key == "m_steel")
    assert c.seal == "Red" and c.edition.foil


def test_creative_errors_are_illegal_actions():
    G = game()
    for bad in ({"op": "fly"}, {"op": "set", "what": "money"}, {"op": "add", "key": "j_nope"},
                {"op": "win"}, {"op": "edit", "area": "hand", "index": 0}, {"op": "boss", "key": "bl_small"}):
        with pytest.raises(IllegalAction):
            cr(G, **bad)
    with pytest.raises(IllegalAction):  # (no creative mod: no creative commands)
        Game("MODTEST", mods=[FRUIT]).start_run().do({"cmd": "creative", "op": "win"})
    assert {"cmd": "creative"} in game().legal_actions()


COMMANDS = [
    {"cmd": "creative", "op": "add", "key": "j_fruit_stand_cherry_seven"},
    {"cmd": "creative", "op": "add", "key": "j_fruit_stand_seed_packet"},
    {"cmd": "creative", "op": "add", "key": "j_fruit_stand_banana_bunch"},
    {"cmd": "select_blind"},
    {"cmd": "creative", "op": "add_card", "rank": "7", "suit": "Clubs", "to": "hand"},
    {"cmd": "play", "cards": [0, 1, 2, 3, 4]},
    {"cmd": "discard", "cards": [0, 1]},
    {"cmd": "creative", "op": "win"},
    {"cmd": "cash_out"},
    {"cmd": "reroll"},
    {"cmd": "end_shop"},
    {"cmd": "select_blind"},
    {"cmd": "play", "cards": [0, 1, 2]},
]


def test_a_modded_run_replays_exactly():
    runs = []
    for _ in range(2):
        G = game(FRUIT, WILD)
        for cmd in COMMANDS:
            try:
                G.do(dict(cmd))
            except IllegalAction:
                pass
        runs.append(G.snapshot())
    assert runs[0] == runs[1]


def test_a_modded_run_clones():
    G = game(FRUIT, WILD)
    for cmd in COMMANDS[:6]:
        G.do(dict(cmd))
    twin = G.clone()
    assert twin.mods[0] is G.mods[0]  # (content mods have no state: shared)
    for g in (G, twin):
        for cmd in COMMANDS[6:]:
            try:
                g.do(dict(cmd))
            except IllegalAction:
                pass
    assert G.snapshot() == twin.snapshot()


def test_content_mod_spec_is_its_package():
    m = make_mod(FRUIT)
    assert isinstance(m, ContentMod) and m.spec() is not None and m.spec()["id"] == "fruit_stand"
    assert m.state() == {"id": "fruit_stand", "version": "1.0.0", "creative": False}

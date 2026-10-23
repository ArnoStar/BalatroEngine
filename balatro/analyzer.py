"""Seed analyzer: what a seed contains, ante by ante.

The analyzer drives the real engine along a canonical path (the convention
used by Balatro seed finders):

* every blind is selected (never skipped) and beaten without playing a hand,
* in every shop both packs are opened (and skipped) first, then the shop is
  rerolled ``rerolls`` times; nothing is bought, so pools only contain what
  the starting deck/stake allows,
* money is topped up so rerolls/packs are always affordable (money never
  feeds the RNG).

Everything that depends only on the seed and that path comes out exactly as
in the game: bosses, tags (incl. Orbital hands), vouchers, the full shop
queue with editions and stickers, booster packs and their contents, and the
first hand of every round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .card import Card, card_label
from .game import Game, Profile
from .lua import T


def describe(card: Card) -> str:
    """Human readable description of a card."""
    G = card.G
    ab = card.ability
    if ab.set in ("Default", "Enhanced"):
        s = card_label(card)
    else:
        s = G.data.display_name(card.config.center.key)
    extras = []
    if card.edition:
        extras.append(card.edition.type.capitalize())
    if ab.eternal:
        extras.append("Eternal")
    if ab.perishable:
        extras.append("Perishable")
    if ab.rental:
        extras.append("Rental")
    if extras:
        s += " (" + ", ".join(extras) + ")"
    return s


@dataclass
class CardInfo:
    key: str
    name: str
    set: str
    edition: str | None = None
    seal: str | None = None
    card: str | None = None  # playing card key, e.g. 'H_A'
    eternal: bool = False
    perishable: bool = False
    rental: bool = False
    cost: int = 0

    @classmethod
    def of(cls, c: Card) -> "CardInfo":
        return cls(key=c.config.center.key, name=describe(c), set=c.ability.set,
                   edition=c.edition.type if c.edition else None, seal=c.seal, card=c.config.card_key,
                   eternal=bool(c.ability.eternal), perishable=bool(c.ability.perishable),
                   rental=bool(c.ability.rental), cost=c.cost)

    def __str__(self) -> str:
        return self.name


@dataclass
class PackInfo:
    key: str
    name: str
    contents: list[CardInfo] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.name}: " + ", ".join(map(str, self.contents))


@dataclass
class ShopInfo:
    blind: str  # which blind was just beaten: Small / Big / Boss
    cards: list[CardInfo]  # shop queue: initial 2 + 2 per reroll
    vouchers: list[CardInfo]
    packs: list[PackInfo]


@dataclass
class BlindInfo:
    kind: str  # Small / Big / Boss
    key: str
    name: str
    chips: float
    tag: str | None = None
    tag_name: str | None = None
    orbital_hand: str | None = None
    first_hand: list[str] = field(default_factory=list)


@dataclass
class AnteInfo:
    ante: int
    boss: str
    boss_name: str
    voucher: str | None
    voucher_name: str | None
    blinds: list[BlindInfo] = field(default_factory=list)
    shops: list[ShopInfo] = field(default_factory=list)


@dataclass
class SeedReport:
    seed: str
    deck: str
    stake: int
    starting_deck: list[str]
    antes: list[AnteInfo] = field(default_factory=list)

    def to_text(self) -> str:
        out = [f"Seed {self.seed}  deck {self.deck}  stake {self.stake}",
               "(* = depends on the game session's hash order, not only on the seed)"]
        for a in self.antes:
            out.append("")
            out.append(f"== Ante {a.ante} ==  Boss: {a.boss_name}   Voucher: {a.voucher_name}")
            for b in a.blinds:
                tag = f"  skip tag: {b.tag_name}" if b.tag_name else ""
                if b.orbital_hand:
                    tag += f" ({b.orbital_hand}*)"
                out.append(f"  {b.kind:5s} {b.name:15s} {b.chips:>12,.0f} chips{tag}")
                if b.first_hand:
                    out.append(f"        first hand: {' '.join(b.first_hand)}")
            for s in a.shops:
                out.append(f"  Shop after {s.blind}:")
                if s.vouchers:
                    out.append("    vouchers: " + ", ".join(map(str, s.vouchers)))
                out.append("    cards:    " + ", ".join(map(str, s.cards)))
                for p in s.packs:
                    out.append(f"    pack:     {p}")
        return "\n".join(out)


class Analyzer:
    def __init__(self, seed: str, deck: str = "b_red", stake: int = 1, challenge: str | None = None,
                 profile: Profile | None = None, hands_order: Any = None) -> None:
        self.G = Game(seed, deck=deck, stake=stake, challenge=challenge, profile=profile, hands_order=hands_order)

    # ------------------------------------------------------------ driving
    def _money(self) -> None:
        self.G.GAME.dollars = max(self.G.GAME.dollars, 10_000)

    def _force_win(self) -> None:
        """Beat the current blind without playing a hand."""
        self.G.do({"cmd": "cheat", "win": True})

    def _open_and_skip_pack(self) -> PackInfo:
        G = self.G
        booster = G.shop_booster.cards[0]
        info = PackInfo(key=booster.config.center.key, name=G.data.display_name(booster.config.center.key))
        self._money()
        G.act_buy("shop_booster", 0)
        info.contents = [CardInfo.of(c) for c in (G.pack_cards.cards if G.pack_cards is not None else [])]
        if G.can_skip_pack():
            G.act_skip_pack()
        return info

    def _shop(self, blind_kind: str, rerolls: int, open_packs: bool) -> ShopInfo:
        G = self.G
        vouchers = [CardInfo.of(c) for c in G.shop_vouchers.cards]
        packs = []
        if open_packs:
            for _ in range(len(G.shop_booster.cards)):
                packs.append(self._open_and_skip_pack())
        else:
            packs = [PackInfo(key=c.config.center.key, name=G.data.display_name(c.config.center.key))
                     for c in G.shop_booster.cards]
        cards = [CardInfo.of(c) for c in G.shop_jokers.cards]
        for _ in range(rerolls):
            self._money()
            G.act_reroll()
            cards.extend(CardInfo.of(c) for c in G.shop_jokers.cards)
        G.act_end_shop()
        return ShopInfo(blind=blind_kind, cards=cards, vouchers=vouchers, packs=packs)

    def run(self, antes: int = 8, rerolls: int = 2, open_packs: bool = True, first_hands: bool = True) -> SeedReport:
        G = self.G
        G.start_run()
        report = SeedReport(seed=G.seed, deck=G.deck_key, stake=G.stake,
                            starting_deck=[card_label(c) for c in sorted(G.playing_cards, key=lambda c: c.sort_id)])
        ante_info: AnteInfo | None = None
        while G.STATE != G.STATES.GAME_OVER:
            ante = G.GAME.round_resets.ante
            if ante > antes:
                break
            rr = G.GAME.round_resets
            if ante_info is None or ante_info.ante != ante:
                boss = rr.blind_choices.Boss
                v = G.GAME.current_round.voucher
                ante_info = AnteInfo(ante=ante, boss=boss, boss_name=G.data.display_name(boss), voucher=v,
                                     voucher_name=G.data.display_name(v) if v else None)
                report.antes.append(ante_info)
            assert G.STATE == G.STATES.BLIND_SELECT, G.STATE
            kind = G.GAME.blind_on_deck
            key = rr.blind_choices[kind]
            binfo = BlindInfo(kind=kind, key=key, name=G.data.display_name(key),
                              chips=G.get_blind_amount(ante) * G.P_BLINDS[key].mult * G.GAME.starting_params.ante_scaling)
            if kind in ("Small", "Big") and rr.blind_tags:
                tkey = rr.blind_tags.get(kind)
                binfo.tag = tkey
                binfo.tag_name = G.data.display_name(tkey) if tkey else None
                if tkey == "tag_orbital":
                    binfo.orbital_hand = (G.GAME.orbital_choices or T()).get(ante, T()).get(kind)
            G.act_select_blind()
            if first_hands:
                binfo.first_hand = [card_label(c) for c in G.hand.cards]
            ante_info.blinds.append(binfo)
            self._force_win()
            if G.STATE != G.STATES.ROUND_EVAL:
                break
            G.act_cash_out()
            if G.STATE == G.STATES.SHOP:
                ante_info.shops.append(self._shop(kind, rerolls, open_packs))
        return report


def analyze(seed: str, deck: str = "b_red", stake: int = 1, antes: int = 8, rerolls: int = 2,
            open_packs: bool = True, **kw: Any) -> SeedReport:
    return Analyzer(seed, deck=deck, stake=stake, **kw).run(antes=antes, rerolls=rerolls, open_packs=open_packs)

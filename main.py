from abc import ABC
import math
from lua_rng import LuaJITRandom, RandomStream, RandomStreamSaver, pseudohash
from blind.blinds import get_all_boss_blind, get_all_current_boss_blind
from tag.tag import get_all_tags

from card.playing_card import PlayingCard, Suits, Ranks
from deck.decks import Deck, RedDeck
from tag.tag import Tag
from blind.blinds import Blind, SmallBlind, BigBlind, BossBlind
import blind.boss_blinds
import tag.tags
from event.events import on_end_ante, on_end_blint, on_start_ante, on_start_blind

class DeckType(ABC):
    ...


class Stack(ABC):
    ...


class PockerHand(ABC):
    ...


class Vouchers(ABC):
    ...


class Run:
    def __init__(self, stack:Stack, deck:Deck, seed:str | None = None):
        self.seed: str = seed.replace("0", "O")
        
        self.rng_saver:RandomStreamSaver = RandomStreamSaver(self.seed)
        
        self.stack: Stack = stack
        self.deck: Deck = deck
        self.max_hand: int = 4
        self.max_discard: int = 3
        self.ante: int = 0
        self.round: int = 0
        self.hand_size: int = 8
        

        self.tags: list[Tag] = get_all_tags()

        self.bosses: list[BossBlind] = get_all_boss_blind()
        
        self.deck.shuffle(RandomStream(self.seed, "shuffle"))
        self.current_rng_shuffle: RandomStream = RandomStream(self.seed, f"nr{self.ante}")

        self.start_ante()

        self.current_blinds: list[Blind] = self.get_next_blinds()
        self.current_blind: Blind = self.current_blinds[0]

        self.hand: list[PlayingCard] = list()
        
        on_start_blind.sub(lambda: self.start_ante())
        on_end_blint.sub(lambda: self.finish_bind())
        on_start_ante.sub(lambda: self.start_ante())
        on_end_ante.sub(lambda: self.finish_ante())

    def get_next_tag(self) -> Tag:
        tag_rng:RandomStream = self.rng_saver.get(f"Tag{self.ante}")
        index:int = tag_rng.next_value(len(self.tags))
        tag:Tag = self.tags[index-1]
        resample:int = 2

        while tag.min_ante > self.ante:
            tag_rng = self.rng_saver.get(f"Tag{self.ante}_resample{resample}")
            index:int = tag_rng.next_value(len(self.tags))
            tag:Tag = self.tags[index-1]
            resample += 1

        return tag

    def get_next_boss(self) -> BossBlind:
        available_bosses: list[BossBlind] = get_all_current_boss_blind(self.ante)
        boss_rng = self.rng_saver.get("boss")
        index:int = boss_rng.next_value(len(available_bosses))
        boss:BossBlind = available_bosses[index-1]

        return boss

    def get_next_blinds(self) -> list[Blind]:
        small_blind : SmallBlind = SmallBlind(self.get_next_tag())
        big_blind : BigBlind = BigBlind(self.get_next_tag())
        boss_blind : BossBlind = self.get_next_boss()()
        return [
            small_blind,
            big_blind,
            boss_blind
        ]

    def start_bind(self):
        for _ in range(self.hand_size):
            self.hand.append(self.deck.draw_card())

    def finish_bind(self):
        self.deck.shuffle(self.current_rng_shuffle)

    def start_ante(self):
        self.ante += 1
        self.current_rng_shuffle = RandomStream(self.seed, f"nr{self.ante}")
        self.deck.shuffle(self.current_rng_shuffle)

    def finish_ante(self):
        ...
        
    def __str__(self):
        result:str = ""
        for blind in self.current_blinds:
            result += f"{blind.__str__()}\n"
        return result


def main():
    seed = "11111111"
    run: Run = Run(None, RedDeck(), seed)

    print(run.deck)
    royal_flush = [
        PlayingCard(Suits.CLUB, Ranks.ACE),
        PlayingCard(Suits.CLUB, Ranks.KING),
        PlayingCard(Suits.CLUB, Ranks.QUEEN),
        PlayingCard(Suits.CLUB, Ranks.JACK),
        PlayingCard(Suits.CLUB, Ranks.N10),
    ]

    for seed in range(1000_0000, 9999_9999):
        seed = str(seed)

        run: Run = Run(None, RedDeck(), seed)

        run.start_bind()

        if run.current_blinds[0].tag.name == "Uncommon" and run.current_blinds[1].tag.name == "Uncommon":
            print(seed)
            is_royal = True
            for card in royal_flush:
                if card not in run.hand:
                    is_royal = False
                    break
                print(f"{seed} have {str(card)}")
            if is_royal: 
                print(seed)
                break
        

main()

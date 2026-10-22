from lua_rng import LuaJITRandom, RandomStream

from card.playing_card import PlayingCard, Suits, Ranks

def basic_start_card() -> list[tuple[Suits, Ranks]]:
    card_deck: list[tuple[Suits, Rank]] = list()
    
    for suit in Suits:
        for rank in Ranks:
            card_deck.append((suit, rank))

    return card_deck

def set_start_cards(list_description_card:list[tuple[Suits, Ranks]]) -> list[PlayingCard]:
    sorted_cards = sorted(
        list_description_card,
        key=lambda card: (
            card[0].value,
            card[1].value
        )
    )

    return [
        PlayingCard(suit, rank)
        for suit, rank in sorted_cards
    ]

class Deck:
    start_cards: list[PlayingCard] = set_start_cards(basic_start_card())

    def __init__(self):
        self.full_deck: list[PlayingCard] = self.start_cards.copy()
        self.current_deck: list[PlayingCard] = self.full_deck

    def draw_card(self) -> PlayingCard:
        return self.current_deck.pop()

    def shuffle(self, rng_stream:RandomStream):
        self.full_deck.sort(key=lambda card: card.sort_id)

        self.current_deck = self.full_deck

        rng_seed = rng_stream.next_seed()

        rng = LuaJITRandom(rng_seed)

        for i in range(len(self.current_deck), 1, -1):
            j = rng.randint(i)

            # Lua arrays are 1-based
            # Python lists are 0-based
            i_index = i - 1
            j_index = j - 1

            self.current_deck[i_index], self.current_deck[j_index] = (
                self.current_deck[j_index],
                self.current_deck[i_index],
            )

    def __str__(self):
        result:str = ""
        for card in self.current_deck:
            result += f"{card.__str__()}\n"
        return result
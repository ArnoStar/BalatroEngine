from card.card import Card

from enum import Enum

class Suits(str, Enum):
    SPADE = "S"
    HEART = "H"
    CLUB = "C"
    DIAMOND = "D"
    

    
class Ranks(str, Enum):
    ACE = "A"
    KING = "K"
    QUEEN = "Q"
    JACK = "J"
    N10 = "T"
    N9 = "9"
    N8 = "8"
    N7 = "7"
    N6 = "6"
    N5 = "5"
    N4 = "4"
    N3 = "3"
    N2 = "2"
    
    
    
    
    

class PlayingCard(Card):
    def __init__(self, suit:Suits, rank:Ranks):
        super().__init__()
        self.suit = suit
        self.rank = rank

    def __eq__(self, other:list):
        return other.suit == self.suit and other.rank == self.rank

    def __str__(self):
        return super().__str__()+f"{self.suit} {self.rank}"
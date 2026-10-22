from uuid import uuid4, UUID

class Card:
    next_sort_id:int = 1
    def __init__(self):
        self.id:UUID = uuid4()
        self.sort_id:int = Card.next_sort_id
        Card.next_sort_id += 1
    
    def __str__(self):
        return ""
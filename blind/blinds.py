from tag.tag import Tag

class Blind:
    blind_type:str = "Unknown"

    def __str__(self):
        return f"{self.blind_type}:\n"

class SmallBlind(Blind):
    blind_type:str = "Small Blind"

    def __init__(self, tag:Tag):
        self.tag = tag

    def __str__(self):
        return super().__str__()+f"Tag: {self.tag.__str__(self.tag)}\n"


class BigBlind(Blind):
    blind_type:str = "Big Blind"

    def __init__(self, tag:Tag):
        self.tag = tag

    def __str__(self):
        return super().__str__()+f"Tag: {self.tag.__str__(self.tag)}\n"


class BossBlind(Blind):
    blind_type:str = "Boss Blind"

    name:str = "Unknown"
    min_ante:int = 1

    def __str__(self):
        return super().__str__()+f"Boss name: {self.name}"


class ShowdownBossBlind(BossBlind):
    min_ante:int = 8


def get_all_boss_blind() -> list[BossBlind]:
    return BossBlind.__subclasses__()

def get_all_current_boss_blind(ante:int) -> list[BossBlind]:
    if ante == 8:
        return ShowdownBossBlind.__subclasses__()

    all_current_boss_blinds:list[BossBlind] = list()
    for boss_blind in BossBlind.__subclasses__():
        if boss_blind.min_ante <= ante:
            all_current_boss_blinds.append(boss_blind)
    
    return sorted(
        all_current_boss_blinds,
        key=lambda boss: boss.name
    )

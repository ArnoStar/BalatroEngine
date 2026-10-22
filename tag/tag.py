class Tag:
    name:str = "Unknown"
    min_ante:int = 1

    def __str__(self):
        return f"Name: {self.name}"


def get_all_tags() -> list[Tag]:
    return Tag.__subclasses__()


def get_all_current_tags(ante:int) -> list[Tag]:
    all_current_tags:list[Tag] = list()
    for tag in Tag.__subclasses__():
        if tag.min_ante <= ante:
            all_current_tags.append(tag)
    
    return all_current_tags

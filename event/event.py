class Event:
    def __init__(self):
        self.subsribers:list = list()

    def sub(self, func):
        self.subsribers.append(func)
    
    def trigger(self):
        for subsriber in self.subscribers:
            subscribers()
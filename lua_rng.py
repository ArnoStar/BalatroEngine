import struct
import math


MASK64 = 0xFFFFFFFFFFFFFFFF


def double_to_u64(value: float) -> int:
    """
    Equivalent of:
    U64double u;
    u.d = value;
    u.u64
    """
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def u64_to_double(value: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", value))[0]


class LuaJITRandom:
    def __init__(self, seed: float):
        self.u = [0, 0, 0, 0]

        self.seed(seed)

    def seed(self, d: float):
        r = 0x11090601

        for i in range(4):
            m = 1 << (r & 255)
            r >>= 8

            d = d * math.pi + 2.7182818284590452354

            u = double_to_u64(d)

            if u < m:
                u += m

            self.u[i] = u & MASK64

        # warm up
        for _ in range(10):
            self.next_u64()


    def next_u64(self) -> int:
      result = 0

      parameters = (
          # k, q, s
          (63, 31, 18),
          (58, 19, 28),
          (55, 24, 7),
          (47, 21, 8),
      )

      for i, (k, q, s) in enumerate(parameters):
          old = self.u[i]

          # C uint64_t truncates the left shift before the XOR.
          shifted = (old << q) & MASK64
          part_a = (shifted ^ old) >> (k - s)

          mask = (MASK64 << (64 - k)) & MASK64
          part_b = (old & mask) << s

          state = (part_a ^ part_b) & MASK64

          self.u[i] = state
          result ^= state

      return result & MASK64


    def random(self):
        """
        Equivalent of:
        lj_prng_u64d()
        then d = u.d - 1.0
        """

        r = self.next_u64()

        # (r & 0x000fffff_ffffffff) | 0x3ff00000_00000000
        bits = (r & 0x000FFFFFFFFFFFFF) | 0x3FF0000000000000

        d = u64_to_double(bits)

        return d - 1.0


    def randint(self, n):
        return math.floor(self.random() * n) + 1


def pseudohash(s: str) -> float:
    num = 1.0

    # Lua:
    # for i=#str, 1, -1 do
    #
    # means:
    # start at length of string
    # go down to 1 (inclusive)

    for i in range(len(s), 0, -1):
        # Lua string.byte(str, i)
        # uses 1-based indexing
        byte = ord(s[i - 1])

        num = (
            (1.1239285023 / num)
            * byte
            * math.pi
            + math.pi * i
        ) % 1

    return num


class RandomStream:
    already_used_seeds = dict()
    def __init__(self, seed:str, name:str):
        self.run_seed = seed
        self.name = name
        self.state = pseudohash(name + seed)
        self.hashed_seed = pseudohash(seed)


    def next_seed(self) -> float:
        value = (
            2.134453429141
            + self.state * 1.72431234
        ) % 1

        self.state = abs(float(f"{value:.13f}"))

        return (
            self.state + self.hashed_seed
        ) / 2


    def next_value(self, maximum:int):
        value = (
            2.134453429141
            + self.state * 1.72431234
        ) % 1

        # Mirrors Lua's string.format("%.13f", value).
        self.state = abs(float(f"{value:.13f}"))

        rng_seed = (
            self.state + self.hashed_seed
        ) / 2

        # Balatro reseeds LuaJIT for every pseudorandom call.
        rng = LuaJITRandom(rng_seed)
        return rng.randint(maximum)


class RandomStreamSaver:
    def __init__(self, seed):
        self.random_streams: dict[str, RandomStream] = dict()
        self.seed = seed

    def get(self, name:str) -> RandomStream:
        save:RandomStream = self.random_streams.get(name + self.seed)
        if save:
            return save
        new_stream: RandomStream = RandomStream(self.seed, name)
        self.random_streams[name + self.seed] = new_stream
        return new_stream
from scripts import (
    shadow_v1_historical_replay,
)


def main():
    shadow_v1_historical_replay.MAX_CASES = 1000

    shadow_v1_historical_replay.main()


if __name__ == "__main__":
    main()
import csv
from pathlib import Path


CSV_DIR = Path(
    "data/private/clarity/csv"
)


def main() -> None:
    found = []

    for path in sorted(
        CSV_DIR.glob("*.csv")
    ):
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(
                handle
            )

            for row in reader:
                if (
                    (
                        row.get(
                            "Typ události"
                        )
                        or ""
                    ).strip()
                    == "Aktivita"
                ):
                    found.append(
                        (
                            path.name,
                            row,
                        )
                    )

    print(
        f"ACTIVITY ROWS: "
        f"{len(found)}"
    )

    for (
        filename,
        row,
    ) in found:
        print()
        print(
            f"FILE: {filename}"
        )

        for (
            key,
            value,
        ) in row.items():
            if (
                value is not None
                and value.strip()
            ):
                print(
                    f"{key}: {value}"
                )


if __name__ == "__main__":
    main()
from borsdata_client import instruments


def main():
    data = instruments()
    rows = data.get("instruments", data)
    print(f"Börsdata connection OK. Instruments returned: {len(rows)}")
    for row in rows[:5]:
        print(row)


if __name__ == "__main__":
    main()

from argparse import ArgumentParser

if __name__ == "__main__":
    parser = ArgumentParser(
        prog="fly-in",
        description="Route a fleet of drones from the "
        "start hub to the end hub."
    )

    parser.add_argument("map", )

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from robot.config import ConfigurationError, load_settings
from robot.worker import ContinuousRobot


def main() -> int:
    parser = argparse.ArgumentParser(description="BTC/USDC robot – hitelesített Binance USDⓈ-M megfigyelő mód")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("robot.cfg"), help="robot.cfg elérési útja")
    parser.add_argument("--once", action="store_true", help="Egy ciklust futtat, majd kilép")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = load_settings(args.config)
    except ConfigurationError as error:
        logging.error("%s", error)
        return 2

    worker = ContinuousRobot(settings)
    if args.once:
        try:
            worker.tick()
        except Exception as error:
            logging.error("Egyszeri robotciklus hiba: %s", error)
            return 1
        return 0

    try:
        worker.run_forever()
    except KeyboardInterrupt:
        logging.info("A külön robot leállt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

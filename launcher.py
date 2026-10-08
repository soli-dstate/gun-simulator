"""Entry script for the PyInstaller build (see gun_sim.spec)."""

import multiprocessing

from gun_sim.ui.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # the simulation's worker processes start from this exe too
    main()

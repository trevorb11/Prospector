#!/usr/bin/env python3
"""
Prospector - Industry Lead Finder for MCA/Business Financing
=============================================================

Main entry point for running the Prospector tools.

Usage:
    python main.py trucking [OPTIONS]
    python main.py enrich INPUT_FILE [OPTIONS]
    python main.py lookup DOT_NUMBER
    python main.py search "COMPANY NAME" [OPTIONS]
    python main.py city CITY STATE [OPTIONS]

For help:
    python main.py --help
    python main.py trucking --help
"""

from prospector.cli import main

if __name__ == "__main__":
    main()

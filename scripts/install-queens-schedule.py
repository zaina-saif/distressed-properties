#!/usr/bin/env python3
"""Write a macOS LaunchAgent for daily Queens refreshes on the operator machine.

Use --output for review, then copy/load the plist with launchctl as documented.
"""
import argparse
from pathlib import Path
import plistlib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
run = root / '.local' / 'queens-refresh'
run.mkdir(parents=True, exist_ok=True)
args.output.write_bytes(plistlib.dumps({
    'Label': 'ai.sheriffsalehunter.queens-refresh',
    'ProgramArguments': [str(root / '.venv/bin/python'), '-m', 'pipeline.queens_foreclosure_refresh'],
    'WorkingDirectory': str(root / 'backend'),
    'StartCalendarInterval': {'Hour': 7, 'Minute': 15},
    'StandardOutPath': str(run / 'scheduler.log'),
    'StandardErrorPath': str(run / 'scheduler-error.log'),
    'ProcessType': 'Background',
    'Umask': 0o077,
}))
print(args.output)

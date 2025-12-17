#!/usr/bin/env python3
"""
Compile all ApiumSlicer_XX.po files to ApiumSlicer.mo files in their respective language directories.
This script uses msgfmt (from gettext) to compile .po files to .mo format.
"""

import os
import subprocess
import sys
from pathlib import Path


def compile_po_files():
    """Find and compile all ApiumSlicer_XX.po files to .mo format."""

    # Get the directory where this script is located
    script_dir = Path(__file__).parent

    # Track compiled files
    compiled_count = 0
    failed_files = []

    print("=" * 60)
    print("ApiumSlicer PO to MO Compiler")
    print("=" * 60)
    print(f"Script directory: {script_dir}\n")

    # Search for all ApiumSlicer_*.po files in subdirectories
    for po_file in script_dir.rglob("ApiumSlicer_*.po"):
        try:
            # Get the language directory
            lang_dir = po_file.parent
            lang_name = lang_dir.name

            # Create output path
            mo_file = lang_dir / "ApiumSlicer.mo"

            print(f"Compiling: {po_file.relative_to(script_dir)}")

            # Use msgfmt to compile .po to .mo
            result = subprocess.run(
                ["msgfmt", "-o", str(mo_file), str(po_file)],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                print(f"  Created: {mo_file.relative_to(script_dir)}")
                compiled_count += 1
            else:
                error_msg = f"msgfmt error: {result.stderr}"
                print(f"  {error_msg}")
                failed_files.append((po_file.name, error_msg))

        except FileNotFoundError:
            error_msg = "msgfmt not found. Please install gettext tools."
            print(f"  {error_msg}")
            failed_files.append((po_file.name, error_msg))
            break
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            print(f"  {error_msg}")
            failed_files.append((po_file.name, error_msg))

    # Print summary
    print("\n" + "=" * 60)
    print("Compilation Summary")
    print("=" * 60)
    print(f"Successfully compiled: {compiled_count} file(s)")

    if failed_files:
        print(f"Failed: {len(failed_files)} file(s)")
        for filename, error in failed_files:
            print(f"  - {filename}: {error}")
        return 1
    else:
        print("All files compiled successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(compile_po_files())

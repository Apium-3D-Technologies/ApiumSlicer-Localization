#!/usr/bin/env python3
"""
Compile all ApiumSlicer_XX.po files to ApiumSlicer.mo files in their respective language directories.
This script first removes duplicates using msguniq and then uses msgfmt for compilation.
"""

import os
import subprocess
import sys
from pathlib import Path


def remove_duplicates(po_file):
    """Use msguniq to remove duplicate entries from the .po file."""
    try:
        # msguniq reads the file and writes the cleaned version back to it (-o)
        result = subprocess.run(
            ["msguniq", "-o", str(po_file), str(po_file)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  Warning: msguniq failed for {po_file.name}: {result.stderr}")
            return False
        return True
    except FileNotFoundError:
        print("  Warning: msguniq not found. Please install gettext tools.")
        return False
    except Exception as e:
        print(f"  Warning: Error executing msguniq: {str(e)}")
        return False


def compile_po_files():
    """Find, clean, and compile all ApiumSlicer_*.po files."""

    # Get the directory where this script is located
    script_dir = Path(__file__).parent

    compiled_count = 0
    failed_files = []

    print("=" * 60)
    print("ApiumSlicer PO to MO Compiler (incl. Duplicate Cleanup)")
    print("=" * 60)
    print(f"Script directory: {script_dir}\n")

    # Search for all ApiumSlicer_*.po files in subdirectories
    for po_file in script_dir.rglob("ApiumSlicer_*.po"):
        try:
            lang_dir = po_file.parent
            mo_file = lang_dir / "ApiumSlicer.mo"

            # Step 1: Remove duplicates
            print(f"Cleaning duplicates: {po_file.relative_to(script_dir)}")
            remove_duplicates(po_file)

            # Step 2: Compile
            print(f"Compiling: {po_file.relative_to(script_dir)}")

            result = subprocess.run(
                ["msgfmt", "-o", str(mo_file), str(po_file)],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                print(f"  Successfully created: {mo_file.relative_to(script_dir)}")
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
        print("All files cleaned and compiled successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(compile_po_files())

#!/usr/bin/env python3
"""
Compile all ApiumSlicer_XX.po files to ApiumSlicer.mo files in their respective language directories.
This script first removes duplicates using msguniq and then uses msgfmt for compilation.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def temporary_output_path(target_file):
    """Create a closed temporary output file next to the target."""
    file_descriptor, filename = tempfile.mkstemp(
        prefix=f".{target_file.name}.",
        suffix=".tmp",
        dir=target_file.parent,
    )
    os.close(file_descriptor)
    return Path(filename)


def replace_output_file(temp_file, target_file):
    """Atomically replace a generated file while preserving its permissions."""
    if target_file.exists():
        temp_file.chmod(target_file.stat().st_mode)
    os.replace(temp_file, target_file)


def remove_duplicates(po_file):
    """Remove duplicate entries without using the PO file as its own output."""
    temp_file = temporary_output_path(po_file)
    try:
        result = subprocess.run(
            ["msguniq", "-o", str(temp_file), str(po_file)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"msguniq error: {result.stderr.strip()}"
        replace_output_file(temp_file, po_file)
        return None
    except FileNotFoundError:
        return "msguniq not found. Please install gettext tools."
    except Exception as e:
        return f"Error executing msguniq: {str(e)}"
    finally:
        if temp_file.exists():
            temp_file.unlink()


def compile_po_file(po_file, mo_file):
    """Compile a PO file without replacing a valid catalog on failure."""
    temp_file = temporary_output_path(mo_file)
    try:
        result = subprocess.run(
            ["msgfmt", "-o", str(temp_file), str(po_file)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"msgfmt error: {result.stderr.strip()}"
        replace_output_file(temp_file, mo_file)
        return None
    except FileNotFoundError:
        return "msgfmt not found. Please install gettext tools."
    except Exception as e:
        return f"Error executing msgfmt: {str(e)}"
    finally:
        if temp_file.exists():
            temp_file.unlink()


def compile_po_files():
    """Find, clean, and compile all ApiumSlicer_*.po files."""

    # Get the directory where this script is located
    script_dir = Path(__file__).resolve().parent

    compiled_count = 0
    cleanup_failed_files = []
    failed_files = []

    print("=" * 60)
    print("ApiumSlicer PO to MO Compiler (incl. Duplicate Cleanup)")
    print("=" * 60)
    print(f"Script directory: {script_dir}\n")

    # Search for all ApiumSlicer_*.po files in subdirectories
    for po_file in sorted(script_dir.rglob("ApiumSlicer_*.po")):
        try:
            lang_dir = po_file.parent
            mo_file = lang_dir / "ApiumSlicer.mo"

            # Step 1: Remove duplicates
            print(f"Cleaning duplicates: {po_file.relative_to(script_dir)}")
            cleanup_error = remove_duplicates(po_file)
            if cleanup_error is not None:
                print(f"  Warning: {cleanup_error}")
                cleanup_failed_files.append((po_file.name, cleanup_error))

            # Step 2: Compile
            print(f"Compiling: {po_file.relative_to(script_dir)}")
            compile_error = compile_po_file(po_file, mo_file)
            if compile_error is None:
                print(f"  Successfully created: {mo_file.relative_to(script_dir)}")
                compiled_count += 1
            else:
                print(f"  {compile_error}")
                failed_files.append((po_file.name, compile_error))
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            print(f"  {error_msg}")
            failed_files.append((po_file.name, error_msg))

    # Print summary
    print("\n" + "=" * 60)
    print("Compilation Summary")
    print("=" * 60)
    print(f"Successfully compiled: {compiled_count} file(s)")

    if cleanup_failed_files:
        print(f"Cleanup failed: {len(cleanup_failed_files)} file(s)")
        for filename, error in cleanup_failed_files:
            print(f"  - {filename}: {error}")

    if failed_files:
        print(f"Compilation failed: {len(failed_files)} file(s)")
        for filename, error in failed_files:
            print(f"  - {filename}: {error}")

    if cleanup_failed_files or failed_files:
        return 1

    print("All files cleaned and compiled successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(compile_po_files())

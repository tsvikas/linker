"""Softlink Installation Utility

This module provides functionality to safely install softlinks (symbolic links)
to a list of files and directories while preserving backups of any existing
files. It's particularly useful for managing dotfiles or other configuration
files that need to be linked from a central location to various places in the
filesystem.

Features:
- Read link specifications from TOML configuration files
- Create softlinks while safely backing up existing files
- Remove files (with backup) when needed
- Provide various levels of verbosity for operation feedback

Example usage:
    # From command line:
    ``` bash
    $ python softlink_installer.py ~/my-dotfiles
    $ python softlink_installer.py ~/my-dotfiles -d /custom/install/path -qq
    ```

    # As a module:
    ```python
    from pathlib import Path
    from softlink_installer import install_links

    locations = {Path.home() / ".config/app"): Path("config/app")}
    install_links(locations, Path.home() / "my-dotfiles", Path.home())
    ```

Configuration:
    The locations.toml file should be structured as follows:
    ```toml
    # Link destination = Link source (relative to toml file location)
    ".bashrc" = "rcfiles/bashrc"
    ".config/app" = "config_folder_for_app"
    ".local/bin/my-script" = "my-script.py"
    # Empty string means remove the file (with backup)
    ".oldfile" = ""
    ```

Notes:
    - All paths in the TOML file are relative to either the installation base
      directory (destinations) or the TOML file's parent directory (sources)
    - Existing files at destination paths are automatically backed up with
      .bkp_N suffixes where N is an incrementing number
"""

import argparse
import enum
import tomllib
from itertools import count
from pathlib import Path


class VerboseLevel(enum.IntEnum):
    """Enumeration of verbosity levels for operation feedback.

    Attributes:
        NOTHING (0): No output
        RENAME_FILE (1): Show file rename operations
        CREATE_LINK (2): Show as above, plus link creation operations.
        LINK_OK (3): Show as above, plus specify existing links that don't need to be changed.
    """

    NOTHING = 0
    RENAME_FILE = 1
    CREATE_LINK = 2
    LINK_OK = 3


MAX_VERBOSE = max(VerboseLevel)


def safe_remove(p: Path, verbose_level: VerboseLevel) -> Path:
    """Safely rename a file or directory to a backup name.

    Creates a backup by appending .bkp_N to the filename, where N is an incrementing
    number starting from 0, continuing until an unused name is found.

    Args:
        p: Path to the file or directory to be renamed
        verbose_level: Controls the amount of feedback printed during operation

    Returns:
        Path: The new path where the file/directory was moved to
    """
    p = p.absolute()
    assert p.exists(follow_symlinks=False)
    for i in count():
        p_backup = Path(f"{p}.bkp_{i}")
        if not p_backup.exists(follow_symlinks=False):
            break
    if verbose_level >= VerboseLevel.RENAME_FILE:
        print(f"renaming {p} -> {p_backup}")
    p.rename(p_backup)
    assert not p.exists(follow_symlinks=False)
    return p_backup


def safe_link(src: Path, dst: Path, verbose_level: VerboseLevel) -> None:
    """Create a symbolic link from dst to src, safely handling existing files.

    If dst already exists, it will be backed up using safe_remove() before
    creating the new link, unless dst is already a correct symlink to src,
    in which case no action is taken.

    Args:
        src: Path to the source file/directory to link to
        dst: Path where the symbolic link should be created
        verbose_level: Controls the amount of feedback printed during operation
    """
    src = src.absolute()
    dst = dst.absolute()
    is_dir = "/" if src.is_dir() else ""
    if not src.exists(follow_symlinks=True):
        # TODO: maybe here i want to mv dst -> src instead?
        raise ValueError(f"src {src} not found")
    if dst.is_symlink() and dst.readlink() == src:
        if verbose_level >= VerboseLevel.LINK_OK:
            print(f"exists   {dst} <- {src}{is_dir}")
        return
    if dst.exists(follow_symlinks=False):
        safe_remove(dst, verbose_level)
    if verbose_level >= VerboseLevel.CREATE_LINK:
        print(f"linking  {dst} <- {src}{is_dir}")
    dst.parent.mkdir(exist_ok=True, parents=True)
    dst.symlink_to(src)


def install_links(
    locations: dict[Path, Path | None],
    src_dir: Path,
    dst_dir: Path = Path.home(),
    verbose_level: VerboseLevel = MAX_VERBOSE,
) -> None:
    """Install symbolic links according to the locations dictionary.

    For each entry in locations, creates a symbolic link from the destination
    (key) to the source (value). If the value is None, the destination file
    is removed (with backup).

    Args:
        locations: Dictionary mapping destination paths to source paths
        src_dir: Base directory containing source files
        dst_dir: Base directory where links will be created (default: user's home)
        verbose_level: Controls the amount of feedback printed
    """
    # resolve locations
    locations_full = {
        dst_dir / dst.expanduser(): src and src_dir / src
        for dst, src in locations.items()
    }
    # check locations
    for dst, src in locations_full.items():
        if dst_dir not in dst.parents:
            raise ValueError(f"only linking files into {dst_dir}, not {dst}")
        if src is not None and src_dir not in src.parents:
            raise ValueError(f"only linking files from {src_dir}, not {src}")
    # create links
    for dst, src in locations_full.items():
        if src is None:
            if dst.exists(follow_symlinks=False):
                safe_remove(dst, verbose_level)
        else:
            safe_link(src, dst, verbose_level)


def read_locations_file(toml_file: Path) -> dict[Path, Path | None]:
    """Read link specifications from a TOML file.

    The TOML file should contain key-value pairs where:
    - Keys are destination paths (relative to dst_dir)
    - Values are source paths (relative to src_dir) or "" to remove

    Args:
        toml_file: Path to the TOML configuration file

    Returns:
        Dictionary mapping destination Paths to source Paths or None

    Example TOML content:
        ```toml
        ".bashrc" = "rcfiles/bashrc"
        ".config/app" = "config_folder_for_app"
        ".local/bin/my-script" = "my-script.py"
        ".oldfile" = ""
        ```
    """
    data = tomllib.load(Path(toml_file).open("rb"))
    return {Path(dst): Path(src) if src else None for dst, src in data.items()}


def main() -> None:
    """Command-line interface for the link installer.

    Provides a command-line interface to read a locations.toml file and install
    the specified links. The source directory must contain a locations.toml file
    specifying the links to create.

    Command-line Arguments:
        SRC_DIR: Directory containing source files and locations.toml
        -d/--dest_dir: Directory to install links into (default: home directory)
        -q/--quiet: Reduce verbosity (can be specified multiple times)
    """
    parser = argparse.ArgumentParser(description="install links to a list of files")
    parser.add_argument(
        "SRC_DIR",
        help="Path containing the targets. Must contain `locations.toml`. default: user home dir",
        type=Path,
    )
    parser.add_argument(
        "-d",
        "--dest_dir",
        help="Path to install the links into",
        type=Path,
        default=Path.home(),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="count",
        default=0,
        help=f"Increase quietness level (can be repeated up to {int(MAX_VERBOSE)} times)",
    )
    args = parser.parse_args()
    src_dir = args.SRC_DIR
    locations = read_locations_file(src_dir / "locations.toml")
    dst_dir = args.dest_dir
    verbose_level = VerboseLevel(MAX_VERBOSE - args.quiet)
    install_links(locations, src_dir, dst_dir, verbose_level)


if __name__ == "__main__":
    main()

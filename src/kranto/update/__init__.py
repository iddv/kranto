"""Kranto updates: the check, the staged wheel sets, the backup and the
helper that restarts Kranto on a new version.

- ``sources``: where releases come from (GitHub Releases; the main channel's commits);
- ``check``: the daily check, the cache in ``<home>/data/update.json``, the status lines;
- ``backup``: ``kranto backup DIR`` (both databases, the configs, the unit, the receipt);
- ``apply``: standard library only; the helper and what it shares with the check.
"""

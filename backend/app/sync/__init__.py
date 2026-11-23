"""Multi-device sync building blocks (ARCHITECTURE §6.13).

Phase 0 ships the pieces every later feature relies on: sortable unique ids
(ULIDs) for rows a phone may create, and a hybrid logical clock for ordering
edits made on different devices. Push/pull endpoints arrive in Phase 9.
"""

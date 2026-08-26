"""Registry of open-data imagery programs — the licensing gate for source
provenance.

Only imagery captured from a program listed here may be auto-attributed on
published datasets. The registry's ``name``/``license`` are authoritative: any
client-supplied values on a ``SourceImageryRef`` are ignored, and references
whose ``programId`` is not registered are dropped. This makes attribution
fail-safe — if we cannot prove open-data provenance, we emit none.

Adding a new open-data program is one entry here (plus a source in the Open Data
Catalog explorer); the publish pipeline and STAC builder need no changes.
"""

from typing import Dict, List, Optional, Sequence

from ..models.publishing import SourceImageryRef

# programId -> canonical metadata. programId also keys the UI catalog sources.
OPEN_DATA_PROGRAMS: Dict[str, Dict[str, str]] = {
    "vantor-open-data": {
        "name": "Vantor Open Data Program",
        "license": "CC-BY-NC-4.0",
        "url": "https://vantor.com/company/open-data-program/",
    },
    "planet-open-data": {
        "name": "Planet Disaster Data",
        "license": "CC-BY-NC-4.0",
        "url": "https://www.planet.com/disasterdata/",
    },
}


def open_data_program(program_id: Optional[str]) -> Optional[Dict[str, str]]:
    """Return the registry entry for ``program_id``, or None if unregistered."""
    if not program_id:
        return None
    return OPEN_DATA_PROGRAMS.get(program_id)


def validate_source_refs(
    refs: Optional[Sequence[SourceImageryRef]],
) -> List[SourceImageryRef]:
    """Return only references from registered open-data programs.

    Drops any ref whose ``programId`` is not registered, stamps the registry's
    canonical ``programName``/``license`` and ``attributable=True`` (ignoring
    client-supplied values), and de-duplicates by ``(programId, href)``.
    """
    validated: List[SourceImageryRef] = []
    seen = set()
    for ref in refs or []:
        program = OPEN_DATA_PROGRAMS.get(ref.programId)
        if program is None:
            continue
        key = (ref.programId, ref.href)
        if key in seen:
            continue
        seen.add(key)
        validated.append(
            ref.model_copy(
                update={
                    "programName": program["name"],
                    "license": program["license"],
                    "attributable": True,
                }
            )
        )
    return validated

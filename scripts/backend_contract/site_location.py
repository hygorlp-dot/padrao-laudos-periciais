"""The inspected property's location, read locally from what the expert pastes.

A maps link or coordinate text is interpreted on this machine only: no map
provider, tile server or geocoder is ever contacted, and the pasted text is not
kept -- only the coordinates it states.  A short link (``maps.app.goo.gl``)
names no coordinates until a remote service resolves it, so it is refused with
guidance instead of being sent anywhere.  A location is a proposal until the
expert confirms it; only a confirmed location can enter the report.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum
import re
from urllib.parse import parse_qs, unquote, urlsplit

SITE_LOCATION_ARTIFACT_KIND = "SITE_LOCATION_V1"
SITE_LOCATION_ARTIFACT_ID = "SITE-LOCATION"

_SHORT_LINK_HOSTS = frozenset({"maps.app.goo.gl", "goo.gl", "g.co", "maps.google.com.br.goo.gl"})
_MAX_INPUT = 4000
_MAX_LABEL = 300
_MAX_NOTE = 1000


class LocationInputFormat(StrEnum):
    GOOGLE_MAPS_PLACE = "GOOGLE_MAPS_PLACE"
    GOOGLE_MAPS_QUERY = "GOOGLE_MAPS_QUERY"
    GOOGLE_MAPS_VIEWPORT = "GOOGLE_MAPS_VIEWPORT"
    OPENSTREETMAP = "OPENSTREETMAP"
    GEO_URI = "GEO_URI"
    DECIMAL = "DECIMAL"
    DEGREES_MINUTES_SECONDS = "DEGREES_MINUTES_SECONDS"


class SiteLocationState(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"


class LocationInputError(ValueError):
    """The pasted text states no coordinates this machine can read."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ParsedLocation:
    latitude: float
    longitude: float
    input_format: LocationInputFormat


_NUMBER = r"[-+]?\d{1,3}(?:\.\d+)?"
_PAIR = re.compile(rf"^\s*(?:loc:)?\s*({_NUMBER})\s*,\s*({_NUMBER})\s*$")
_PLACE_PIN = re.compile(rf"!3d({_NUMBER})!4d({_NUMBER})")
_VIEWPORT = re.compile(rf"@({_NUMBER}),({_NUMBER})(?:,|$|/|\?)")
_OSM_HASH = re.compile(rf"map=\d{{1,2}}/({_NUMBER})/({_NUMBER})")
_DECIMAL_DOT = re.compile(rf"^\s*({_NUMBER})\s*[,;\s]\s*({_NUMBER})\s*$")
_DECIMAL_COMMA = re.compile(r"^\s*([-+]?\d{1,3}(?:,\d+)?)\s*[;\s]\s*([-+]?\d{1,3}(?:,\d+)?)\s*$")
_DMS_PART = r"(\d{1,3})\s*[°º]\s*(?:(\d{1,2}(?:[.,]\d+)?)\s*['′’]\s*)?(?:(\d{1,2}(?:[.,]\d+)?)\s*(?:\"|″|”|''))?\s*([NSEWLOnsewlo])"
_DMS = re.compile(rf"^\s*{_DMS_PART}[\s,;]*{_DMS_PART}\s*$")


def _coordinates(latitude: float, longitude: float, input_format: LocationInputFormat) -> ParsedLocation:
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        raise LocationInputError("OUT_OF_RANGE")
    if latitude == 0.0 and longitude == 0.0:
        # "Null Island" is what an empty map pin reads as, never a property.
        raise LocationInputError("NO_COORDINATES")
    return ParsedLocation(round(latitude, 6), round(longitude, 6), input_format)


def _pair(value: str, input_format: LocationInputFormat) -> ParsedLocation | None:
    match = _PAIR.match(value)
    return _coordinates(float(match.group(1)), float(match.group(2)), input_format) if match else None


def _dms(match: re.Match) -> tuple[float, float]:
    values = []
    for offset in (0, 4):
        degrees, minutes, seconds, hemisphere = match.groups()[offset:offset + 4]
        value = float(degrees) + float((minutes or "0").replace(",", ".")) / 60 + float((seconds or "0").replace(",", ".")) / 3600
        values.append((value, hemisphere.upper()))
    (first, first_hemisphere), (second, second_hemisphere) = values
    if first_hemisphere in {"N", "S"} and second_hemisphere in {"E", "W", "L", "O"}:
        latitude, longitude = first, second
        latitude_hemisphere, longitude_hemisphere = first_hemisphere, second_hemisphere
    elif second_hemisphere in {"N", "S"} and first_hemisphere in {"E", "W", "L", "O"}:
        latitude, longitude = second, first
        latitude_hemisphere, longitude_hemisphere = second_hemisphere, first_hemisphere
    else:
        raise LocationInputError("NO_COORDINATES")
    # Portuguese writes west as O (oeste) and east as L (leste).
    return (-latitude if latitude_hemisphere == "S" else latitude, -longitude if longitude_hemisphere in {"W", "O"} else longitude)


def parse_location_input(text: object) -> ParsedLocation:
    """Coordinates stated by a maps link or coordinate text, read locally.

    A Google Maps place link carries the pin (``!3d…!4d…``) and a query link
    its ``q``/``ll`` pair; ``@lat,lng`` is only the map's centre and is
    reported as such so the expert checks it.  Anything else is refused.
    """
    if type(text) is not str or not text.strip() or len(text) > _MAX_INPUT:
        raise LocationInputError("NO_COORDINATES")
    value = unquote(text.strip())
    if re.match(r"^[a-z][a-z0-9+.-]*://", value, re.IGNORECASE) or value.lower().startswith(("www.", "maps.", "goo.gl")):
        url = urlsplit(value if "://" in value else f"https://{value}")
        host = (url.hostname or "").lower()
        if host in _SHORT_LINK_HOSTS or host.endswith(".app.goo.gl"):
            raise LocationInputError("SHORT_LINK_REQUIRES_NETWORK")
        if "openstreetmap" in host:
            query = parse_qs(url.query)
            if "mlat" in query and "mlon" in query:
                return _coordinates(float(query["mlat"][0]), float(query["mlon"][0]), LocationInputFormat.OPENSTREETMAP)
            match = _OSM_HASH.search(url.fragment) or _OSM_HASH.search(url.query)
            if match:
                return _coordinates(float(match.group(1)), float(match.group(2)), LocationInputFormat.OPENSTREETMAP)
            raise LocationInputError("NO_COORDINATES")
        if "google." not in host:
            raise LocationInputError("UNSUPPORTED_LINK")
        pins = _PLACE_PIN.findall(value)
        if pins:
            latitude, longitude = pins[-1]
            return _coordinates(float(latitude), float(longitude), LocationInputFormat.GOOGLE_MAPS_PLACE)
        query = parse_qs(url.query)
        for name in ("q", "query", "ll", "center", "destination", "daddr"):
            for candidate in query.get(name, ()):
                parsed = _pair(candidate, LocationInputFormat.GOOGLE_MAPS_QUERY)
                if parsed is not None:
                    return parsed
        match = _VIEWPORT.search(url.path + ("?" if url.query else ""))
        if match:
            return _coordinates(float(match.group(1)), float(match.group(2)), LocationInputFormat.GOOGLE_MAPS_VIEWPORT)
        raise LocationInputError("NO_COORDINATES")
    if value.lower().startswith("geo:"):
        parsed = _pair(value[4:].split(";", 1)[0].split("?", 1)[0], LocationInputFormat.GEO_URI)
        if parsed is None:
            raise LocationInputError("NO_COORDINATES")
        return parsed
    match = _DECIMAL_DOT.match(value)
    if match:
        return _coordinates(float(match.group(1)), float(match.group(2)), LocationInputFormat.DECIMAL)
    match = _DECIMAL_COMMA.match(value)
    if match:
        return _coordinates(float(match.group(1).replace(",", ".")), float(match.group(2).replace(",", ".")), LocationInputFormat.DECIMAL)
    match = _DMS.match(value)
    if match:
        latitude, longitude = _dms(match)
        return _coordinates(latitude, longitude, LocationInputFormat.DEGREES_MINUTES_SECONDS)
    raise LocationInputError("NO_COORDINATES")


def _optional_text(value: object, limit: int) -> bool:
    return value is None or (type(value) is str and bool(value.strip()) and value == value.strip() and len(value) <= limit)


def _timestamp(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("site location timestamp requires timezone")


@dataclass(frozen=True, slots=True)
class SiteLocation:
    schema_version: str
    workspace_id: str
    latitude: float
    longitude: float
    datum: str
    input_format: LocationInputFormat
    address_label: str | None
    note: str | None
    state: SiteLocationState
    confirmed_by: str | None
    confirmed_at: str | None

    def __post_init__(self):
        if self.schema_version != "1.0.0" or type(self.workspace_id) is not str or not self.workspace_id.strip() or self.datum != "WGS84":
            raise ValueError("site location identity is invalid")
        for name, low, high in (("latitude", -90.0, 90.0), ("longitude", -180.0, 180.0)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not low <= value <= high or round(value, 6) != value:
                raise ValueError("site location coordinates are invalid")
        if self.latitude == 0 and self.longitude == 0:
            raise ValueError("site location coordinates are invalid")
        if not _optional_text(self.address_label, _MAX_LABEL) or not _optional_text(self.note, _MAX_NOTE):
            raise ValueError("site location text is invalid")
        confirmed = self.state is SiteLocationState.CONFIRMED
        if confirmed != (self.confirmed_by is not None) or confirmed != (self.confirmed_at is not None):
            raise ValueError("site location confirmation is dishonest")
        if confirmed:
            if type(self.confirmed_by) is not str or not self.confirmed_by.strip():
                raise ValueError("site location confirmation is dishonest")
            _timestamp(self.confirmed_at)

    @property
    def coordinates_text(self) -> str:
        """``23,550520° S, 46,633308° O`` -- the way a Brazilian report writes it."""
        latitude = f"{abs(self.latitude):.6f}".replace(".", ",") + ("° S" if self.latitude < 0 else "° N")
        longitude = f"{abs(self.longitude):.6f}".replace(".", ",") + ("° O" if self.longitude < 0 else "° L")
        return f"{latitude}, {longitude}"


def site_location_to_mapping(value: SiteLocation) -> dict:
    if type(value) is not SiteLocation:
        raise TypeError("expected SiteLocation")
    mapping = asdict(value)
    mapping["input_format"] = value.input_format.value
    mapping["state"] = value.state.value
    return mapping


def site_location_from_mapping(value: object) -> SiteLocation:
    if type(value) is not dict or set(value) != {item.name for item in fields(SiteLocation)}:
        raise ValueError("SiteLocation mapping is invalid")
    data = dict(value)
    try:
        data["input_format"] = LocationInputFormat(data["input_format"])
        data["state"] = SiteLocationState(data["state"])
    except ValueError as exc:
        raise ValueError("SiteLocation mapping is invalid") from exc
    if type(data["latitude"]) is int or type(data["longitude"]) is int:
        data["latitude"], data["longitude"] = float(data["latitude"]), float(data["longitude"])
    return SiteLocation(**data)

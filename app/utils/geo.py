"""Small geography helper — currently just great-circle distance, used to
check how far a staff check-in was from the configured school location."""
from math import radians, sin, cos, sqrt, atan2

EARTH_RADIUS_M = 6_371_000


def haversine_distance_m(lat1, lng1, lat2, lng2):
    """Distance in meters between two lat/lng points."""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lng2 - lng1)

    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return EARTH_RADIUS_M * c

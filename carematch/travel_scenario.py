"""A transparent travel model, conditional on explicit transport assumptions."""
from math import isfinite


def arrival_share(km, minutes, speeds, detours, departure_delay=0):
    """Probability across equally likely speed/detour pairs. No clinical outcome labels."""
    if not isfinite(km) or km < 0 or minutes <= 0 or departure_delay < 0:
        raise ValueError('Invalid distance, time budget or delay')
    if not speeds or not detours or any(v <= 0 for v in speeds) or any(v < 1 for v in detours):
        raise ValueError('Speeds must be positive and road factors at least one')
    return sum(departure_delay + 60 * km * factor / speed <= minutes
               for factor in detours for speed in speeds) / (len(detours) * len(speeds))

"""Redblink-compatible emergency swap policy, independent of map RAM sizing.

Behavior reference: Red-Blink/dune-awakening-selfhost-docker c2797b11,
runtime/scripts/memory-swap{,-common,-host}.sh and MapsPanel selectedSwapValues.
This policy does not execute the Funcom Kubernetes experimental-swap preset.
"""
import math

GIB = 1024 ** 3
CONFIRM_ENABLE = 'ENABLE MEMORY SWAP'
CONFIRM_DISABLE = 'DISABLE MEMORY SWAP'


def validate(request):
    enabled = request.get('enabled')
    if type(enabled) is not bool:
        raise ValueError('Supply a JSON boolean for Memory Swap.')
    if request.get('confirmation') != (CONFIRM_ENABLE if enabled else CONFIRM_DISABLE):
        raise ValueError('Confirm the reviewed Memory Swap change.')
    if not enabled:
        return {'enabled': False, 'perServerGiB': 0, 'poolGiB': 0, 'swappiness': 10}
    allowance, pool, swappiness = (request.get('perServerGiB', 2),
                                  request.get('poolGiB'), request.get('swappiness', 10))
    for value, lower, upper, label in [(allowance, 1, 16, 'Per-map swap'),
                                      (pool, 0, 32, 'Managed swap pool'),
                                      (swappiness, 0, 100, 'Swappiness')]:
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f'{label} must be a whole number from {lower} to {upper}.')
    return {'enabled': True, 'perServerGiB': allowance, 'poolGiB': pool,
            'swappiness': swappiness}


def recommended_pool(allowance, running_servers, existing_swap_bytes):
    """Match upstream's whole-GiB rounding and minimum two-server recommendation."""
    existing = math.ceil(max(0, existing_swap_bytes) / GIB)
    return max(0, min(32, allowance * max(2, running_servers) - existing))


def total_limit(memory_bytes, policy=None):
    """Docker MemorySwap is a RAM-plus-swap ceiling, never a RAM replacement.

    Turning the custom feature off restores Docker's ordinary equal-to-RAM
    additional swap allowance, as Redblink does; it does not disable host swap.
    """
    if type(memory_bytes) is not int or memory_bytes <= 0:
        raise ValueError('A positive game RAM limit is required for swap allocation.')
    policy = policy or {}
    if policy.get('enabled') is not True:
        return memory_bytes * 2
    allowance = policy.get('perServerGiB')
    if type(allowance) is not int or not 1 <= allowance <= 16:
        raise ValueError('The saved Memory Swap allowance needs recovery.')
    return memory_bytes + allowance * GIB

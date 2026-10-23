"""Apply a per-process address-space ceiling inside the Linux runner."""

try:
    import resource
except ImportError:  # Local Windows tests do not have this module.
    resource = None


def limit_address_space(megabytes=512):
    if resource is None:
        return
    ceiling = megabytes * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))

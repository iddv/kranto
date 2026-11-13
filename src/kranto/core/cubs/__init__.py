"""The cub runtime: a cub is a folder with ``cub.yaml`` and a Python file, run as
its own process in bubblewrap, speaking ``cub/1`` over its pipes to a host that checks every
call against the grants the owner approved. This package holds the core's side: the ``cubs:``
settings (``settings``), and, as the runtime lands, the process, the host, the registry, the
install path, the brokers and the command line."""

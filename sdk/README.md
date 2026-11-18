# bears-cub-sdk

Write and test a cub for [Kranto](https://github.com/iddv/kranto). A cub is a folder with
`cub.yaml` and a Python file; Kranto runs it as its own sandboxed process and speaks `cub/1` to
it. This package is the cub's side: `Cub` and its decorators, the `ctx` each handler gets,
`fence` for strangers' text, and `bears_cub.testing.FakeHost` to test a cub without Kranto.

The guide is `docs/cubs.md` in Kranto's repository; to start, copy one of the cubs Kranto ships
(the folder `kranto paths examples` prints). Check a folder with `python -m bears_cub.check path/to/cub`.

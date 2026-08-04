"""
oasis-sustain - is optimizing this website worth the carbon it costs?

Most web-carbon tooling will happily produce a number for any URL you give it.
This one is built to say no. It runs a cheap sample pass, measures what a real
optimizer actually achieves on the site's real bytes, works out how long the
one-time cost takes to pay back, and returns one of five verdicts, two of which
are refusals. It also meters itself, because a tool that audits other people's
energy and hides its own has no standing.

Public surface:

    from oasis_sustain import carbon, meter
    carbon.per_view(1_600_000)          # model figure AND conservative bound
    carbon.model_footer()               # model, version, grid, date

    from oasis_sustain.preflight import preflight
    from oasis_sustain.optimize import optimize

CLI:

    oasis-sustain check <url> --i-own-this --monthly-views 5000
    oasis-sustain model
"""

__version__ = "1.0.0"

__all__ = ["carbon", "meter", "fetch", "optimize", "preflight", "report"]

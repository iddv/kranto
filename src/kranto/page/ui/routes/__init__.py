"""``api.handle``'s routes, one module per area. ``ROUTES`` is every area's in
turn; no two areas' patterns overlap, so only the order within an area decides anything
(tests/page/test_api_routes.py pins every route). The handlers call ``api.App``; a new area adds a
module here. The builds, the loop, projects, maintenance, GitHub, the factory's prompts and the
build settings left with the factory (cut 3): their paths answer 404."""
from . import activity, details, feedback, page, static, term
from .trace import ROUTES as TRACE

ROUTES = [*static.ROUTES, *activity.ROUTES, *details.ROUTES, *page.ROUTES, *feedback.ROUTES,
          *term.ROUTES, *TRACE]

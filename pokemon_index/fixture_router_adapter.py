"""Explicit synthetic-only integration of the source router with CommerceLoop.

No real adapters, live network, configuration wiring or quote providers are
enabled by this bridge. Detail is limited to listings discovered in this run.
"""
from .source_router import SourceRouter


class FixtureRouterCrawler:
    mode = 'synthetic_fixture'

    def __init__(self, router):
        if type(router) is not SourceRouter:
            raise ValueError('exact synthetic router required')
        self._router = router

    def search(self, source, query, limit=5):
        return {'status': 'synthetic_fixture',
                'listings': self._router.search(source, query, limit=limit)}

    def detail(self, url):
        return self._router.detail(url)

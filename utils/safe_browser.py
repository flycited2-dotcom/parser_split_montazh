"""Жизненный цикл Chromium context — periodic recreate против memory leak.

Chromium тащит pages в RAM. Через ~200-300 страниц 1-2 GB.
Recreate каждые N страниц — память возвращается, прогресс не теряется
(пишем CSV сразу на каждой записи).
"""

from utils.browser import create_browser_context


class SafeContext:
    def __init__(self, playwright, headless: bool = True, recreate_every: int = 100):
        self.playwright = playwright
        self.headless = headless
        self.recreate_every = recreate_every
        self._pages_opened = 0
        self.browser = None
        self.context = None

    async def __aenter__(self):
        await self._open()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._close()

    async def _open(self) -> None:
        self.browser, self.context = await create_browser_context(
            self.playwright, headless=self.headless
        )
        self.context.set_default_timeout(30_000)
        self.context.set_default_navigation_timeout(30_000)

    async def _close(self) -> None:
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        self.browser = None
        self.context = None

    async def maybe_recreate(self) -> None:
        self._pages_opened += 1
        if self._pages_opened % self.recreate_every == 0:
            print(f" [safe] пересоздаём Chromium context (после {self._pages_opened} страниц)")
            await self._close()
            await self._open()

    async def new_page(self):
        return await self.context.new_page()

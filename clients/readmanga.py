import json
import re
from typing import List, AsyncIterable
from urllib.parse import urlparse, urljoin

from aiohttp import ClientResponse
from bs4 import BeautifulSoup
from bs4.element import PageElement

from clients.client import MangaClient, MangaCard, MangaChapter, LastChapter


class ReadMangaClient(MangaClient):

    base_url = urlparse('https://readmanga.live/')
    search_url = urljoin(base_url.geturl(), 'search/suggestion')
    search_param = 'query'

    pre_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0'
    }

    def __init__(self, *args, name='ReadManga', **kwargs):
        super().__init__(*args, name=name, headers=self.pre_headers, **kwargs)

    def mangas_from_page(self, page: bytes):
        dt = json.loads(page)
        mangas = dt['suggestions']

        names = [manga.get('value') for manga in mangas]
        url = [urljoin(self.base_url.geturl(), manga.get('link').strip()) for manga in mangas]
        images = [manga.get('thumbnail') for manga in mangas]
        additional = [manga.get('additional') for manga in mangas]

        return list(map(lambda x: MangaCard(self, x[0], x[1], x[2], x[3], []), zip(names, url, images, additional)))

    def chapters_from_page(self, page: bytes, manga: MangaCard = None):
        bs = BeautifulSoup(page, 'html.parser')

        div = bs.find('div', {'class': 'chapters'})

        items = div.find_all('a', {'class': 'chapter-link'})

        links = [urljoin(self.base_url.geturl(), item.get('href')) for item in items]
        texts = [item.contents[0].strip() for item in items]

        return list(map(lambda x: MangaChapter(self, x[0], x[1], manga, []), zip(texts, links)))

    def updates_from_page(self, page: bytes):
        bs = BeautifulSoup(page, 'html.parser')

        div = bs.find('div', {'id': 'last-updates'})

        manga_items: List[PageElement] = div.find_all('div', {'class': 'tile'})

        urls = dict()

        for manga_item in manga_items:

            manga_url = urljoin(self.base_url.geturl(), manga_item.find_next('div', {'class': 'desc'}).findNext('a').get('href'))

            chapter_item = manga_item.findNext('div', {'class': 'chapters-text'}).findNext('strong')
            chapter_url = urljoin(self.base_url.geturl(), chapter_item.findNext('a').get('href'))

            urls[manga_url] = chapter_url

        return urls

    async def set_pictures(self, manga_chapter: MangaChapter) -> MangaChapter:
        requests_url = manga_chapter.url

        response = await self.get(f'{requests_url}?mtr=true')

        content = await response.read()

        manga_chapter.pictures = await self.pictures_from_chapters(content, response)

        return manga_chapter

    async def pictures_from_chapters(self, content: bytes, response: ClientResponse = None):
        regex = rb"\[['\"](.*?)['\"],['\"]['\"],['\"](.*?)['\"],\d+,\d+\]"

        for item in content.split(b'\n'):
            if b'rm_h.readerDoInit' in item:
                images_url = [f'{a[0].decode()}{a[1].decode()}' for a in re.findall(regex, item)]

                return images_url

    async def search(self, query: str = '', page: int = 1) -> List[MangaCard]:
        request_url = self.search_url

        if query:
            request_url += f'?{self.search_param}={query}&types[]=CREATION'

        content = await self.get_url(request_url)

        return self.mangas_from_page(content)[(page - 1) * 20:page * 20]

    async def set_chapters(self, manga_card: MangaCard) -> MangaCard:
        request_url = f'{manga_card.url}'

        content = await self.get_url(request_url)

        manga_card.chapters = self.chapters_from_page(content, manga_card)

        return manga_card

    async def iter_chapters(self, manga_url: str, manga_name) -> AsyncIterable[MangaChapter]:
        manga_card = MangaCard(self, manga_name, manga_url, '', '', [])

        request_url = f'{manga_card.url}'

        content = await self.get_url(request_url)

        for ch in self.chapters_from_page(content, manga_card):
            yield ch

    async def contains_url(self, url: str):
        return url.startswith(self.base_url.geturl())

    async def check_updated_urls(self, last_chapters: List[LastChapter]):
        content = await self.get_url(self.base_url.geturl())

        updates = self.updates_from_page(content)

        updated = [lc.url for lc in last_chapters if updates.get(lc.url) and updates.get(lc.url) != lc.chapter_url]
        not_updated = [lc.url for lc in last_chapters if not updates.get(lc.url) or updates.get(lc.url) == lc.chapter_url]

        return updated, not_updated
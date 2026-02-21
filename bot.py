class EventBot:

    def __init__(self):
        self.session = None
        self.posted = load_posted()

    async def get_session(self):
        ...

    async def parse_channel(self, channel: Dict):
        ...

    # 🔥 ВОТ ТАК — с 4 пробелами
    async def parse_site(self, site: Dict) -> List[Dict]:

        html = await self.fetch(site["url"])
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        events = []

        for link in soup.find_all("a", href=True)[:80]:
            try:
                href = link.get("href", "")
                title_raw = link.get_text(strip=True)

                if not href or not title_raw or len(title_raw) < 15:
                    continue

                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(site["url"], href)

                href = normalize_link(href)

                if href.rstrip("/") == normalize_link(site["url"]).rstrip("/"):
                    continue

                if href in self.posted:
                    continue

                if is_site_trash(title_raw):
                    continue

                if not is_real_event(title_raw):
                    continue

                parent = link.find_parent(["div", "article", "li", "section"])
                context = parent.get_text(separator=" ", strip=True) if parent else title_raw
                dt = parse_date(context)

                if not is_future(dt):
                    continue

                image_url = None
                img = link.find("img", src=True) or (parent.find("img", src=True) if parent else None)

                if img:
                    src = img.get("src", "")
                    if src and not src.startswith("http"):
                        from urllib.parse import urljoin
                        src = urljoin(site["url"], src)
                    image_url = src or None

                title_clean = (
                    clean_title_deterministic(title_raw)
                    or strip_emoji(dedup_title(title_raw))[:120]
                )

                events.append(
                    {
                        "title": title_clean,
                        "date": format_date(dt),
                        "location": extract_location(context) or "",
                        "venue": extract_venue(context),
                        "link": href,
                        "source": site["name"],
                        "image_url": image_url,
                    }
                )

                if len(events) >= 5:
                    break

            except Exception:
                continue

        return events

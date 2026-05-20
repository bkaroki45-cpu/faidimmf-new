import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Submit public site URLs to IndexNow."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            default="www.faidii.com",
            help="Public host name without protocol.",
        )
        parser.add_argument(
            "--scheme",
            default="https",
            choices=["http", "https"],
            help="Public URL scheme.",
        )

    def handle(self, *args, **options):
        host = options["host"]
        scheme = options["scheme"]
        base_url = f"{scheme}://{host}"
        urls = [
            f"{base_url}/",
            f"{base_url}/about/",
            f"{base_url}/contacts/",
            f"{base_url}/sitemap.xml",
        ]
        payload = {
            "host": host,
            "key": settings.INDEXNOW_KEY,
            "keyLocation": f"{base_url}/{settings.INDEXNOW_KEY_PATH}",
            "urlList": urls,
        }
        request = urllib.request.Request(
            "https://api.indexnow.org/indexnow",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"IndexNow accepted {len(urls)} URL(s): HTTP {response.status}"
                    )
                )
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise SystemExit(f"IndexNow failed: HTTP {error.code} {details}")
        except urllib.error.URLError as error:
            raise SystemExit(f"IndexNow failed: {error.reason}")

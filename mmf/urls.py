from django.contrib import admin
from django.urls import path, include
from core.views import favicon, indexnow_key, robots_txt, site_webmanifest, sitemap_xml
from django.conf import settings
from django.views.generic.base import RedirectView  # ✅ for redirect

# Optional: preserve query string in redirect
class RegisterRedirectWithQuery(RedirectView):
    url = '/user/register/'
    permanent = False
    query_string = True  # ✅ keep ?ref=XYZ

urlpatterns = [
    path('admin/', admin.site.urls),
    path('favicon.ico', favicon),
    path('site.webmanifest', site_webmanifest),
    path('robots.txt', robots_txt),
    path('sitemap.xml', sitemap_xml),
    path(settings.INDEXNOW_KEY_PATH, indexnow_key),
    path('', include('core.urls')),  # Core pages
    path('user/', include(('user.urls', 'user'), namespace='user')),
    path('finance/', include(('finance.urls', 'finance'), namespace='finance')),

    # Preserve referral code in redirect
    path('register/', RegisterRedirectWithQuery.as_view()),
]
